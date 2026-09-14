"""Causal adapter tests use synthetic fixtures, never report trading results."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.alpha.l1_ridge import L1Ridge
from app.alpha.l1_state_models import QueueImbalanceModel, TransitionMicroprice
from app.alpha.paper_l1_alpha import PAPER_L1_FEATURES, VERSION, enhanced_l1_features
from app.research.l1_policy_overlay import build_l1_policy_record


def quotes(n=1200, trades=False):
    index = pd.date_range("2026-09-01 09:30", periods=n, freq="s", tz="America/New_York")
    mid = np.resize([100., 100., 100.01, 100.01, 100., 100., 100.01, 100.01], n)
    size = np.resize([8, 8, 2, 2, 6, 6, 4, 4], n)
    raw = pd.DataFrame(dict(event_type="quote", source="alpaca_stock_historical", symbol="AAA",
                            market_depth="L1", feed="iex", quote_size_unit="round_lots",
                            bid_price=mid-.005, ask_price=mid+.005, bid_size=size, ask_size=10-size), index=index)
    if trades:
        prints = raw.iloc[::5].copy()
        prints.index += pd.Timedelta("500ms")
        prints["event_type"], prints["market_depth"] = "trade", "trade_print"
        prints["price"], prints["size"] = prints.ask_price, 100
        raw = pd.concat([raw, prints]).sort_index(kind="stable")
    return raw


def base():
    return SimpleNamespace(mu={"AAA": .0012}, covariance=np.array([[.0002]]), symbols=["AAA"])


def record(raw=None, *, forecast=None, **kwargs):
    options = dict(decision_time="2026-09-01T09:40:00-04:00", horizon_seconds=300,
                   base_target="next_open_to_horizon_close_gross_return",
                   expected_contracts={"AAA": dict(feed="iex", source="alpaca_stock_historical",
                                                    clock="historical_exchange_latency_unverified")},
                   max_quote_age="5s")
    options.update(kwargs)
    return build_l1_policy_record(base() if forecast is None else forecast,
                                  {} if raw is None else {"AAA": raw}, **options)


def test_base_forecast_is_untouched_and_only_last_completed_bucket_used():
    raw, forecast = quotes(), base()
    result = record(raw, forecast=forecast, decision_time="2026-09-01T09:40:45-04:00")
    assert result.base_mu is forecast.mu
    assert result.covariance is forecast.covariance
    assert result.base_mu == {"AAA": .0012}
    assert result.candidate_mu is None
    assert result.l1["AAA"]["bucket_end"] == "2026-09-01T09:40:00-04:00"
    expected = enhanced_l1_features(raw, as_of=result.decision_time).iloc[-1]
    assert result.l1["AAA"]["features"]["l1_ofi_raw"] == pytest.approx(expected.l1_ofi_raw)
    assert result.l1["AAA"]["missing_features"] == ["l1_signed_trade_imbalance"]
    output = json.loads(json.dumps(result.to_dict(), allow_nan=False))
    assert output["covariance"] == [[.0002]]
    assert output["active_forecast"] == "base_mu"
    assert output["l1"]["AAA"]["features"]["l1_signed_trade_imbalance"] is None


@pytest.mark.parametrize("problem", ["missing", "stale", "wrong_feed", "proxy", "wrong_symbol"])
def test_unavailable_l1_never_drops_or_alters_base_forecast(problem):
    raw = quotes()
    if problem == "missing":
        raw = None
    elif problem == "stale":
        raw = raw.iloc[:590]
    elif problem == "wrong_feed":
        raw["feed"] = "sip"
    elif problem == "proxy":
        raw["source"] = "ohlcv_proxy"
    else:
        raw["symbol"] = "OTHER"
    forecast = base()
    result = record(raw, forecast=forecast)
    assert result.l1["AAA"]["status"] == "unavailable"
    assert result.l1["AAA"]["reason"]
    assert result.base_mu is forecast.mu
    assert result.covariance is forecast.covariance
    assert result.candidate_mu is None


def test_future_quotes_and_late_websocket_arrivals_do_not_change_decision():
    raw = quotes()
    before = record(raw)
    future = raw.copy()
    future.loc[future.index >= before.decision_time, ["bid_price", "ask_price"]] *= 10
    assert record(future).to_dict() == before.to_dict()
    raw["source"] = "alpaca_stock_websocket"
    raw["received_at"] = (raw.index+pd.Timedelta("100ms")).astype(str)
    # A pre-decision exchange quote received after the decision is excluded.
    raw.loc[raw.index[599], "received_at"] = "2026-09-01T09:40:01-04:00"
    websocket = dict(expected_contracts={"AAA": dict(feed="iex", source="alpaca_stock_websocket",
                                                     clock="recorded_arrival")})
    snapshot = record(raw, **websocket)
    changed = raw.copy()
    changed.loc[raw.index[599], ["bid_price", "ask_price"]] *= 10
    assert record(changed, **websocket).to_dict() == snapshot.to_dict()
    assert snapshot.l1["AAA"]["latest_quote_time"] == "2026-09-01T09:39:58.100000-04:00"


def test_recent_arrival_of_old_exchange_quotes_does_not_look_fresh():
    raw = quotes()
    raw["source"] = "alpaca_stock_websocket"
    raw["received_at"] = raw.index.astype(str)
    raw.index -= pd.Timedelta("10min")
    result = record(raw, expected_contracts={"AAA": dict(feed="iex", source="alpaca_stock_websocket",
                                                        clock="recorded_arrival")})
    assert result.l1["AAA"]["status"] == "unavailable"
    assert result.l1["AAA"]["quote_age_seconds"] == 1
    assert result.l1["AAA"]["exchange_quote_age_seconds"] == 601
    assert result.base_mu == {"AAA": .0012}


@pytest.mark.parametrize("invalid", ["locked", "zero_depth"])
def test_latest_invalid_book_does_not_revive_a_recent_valid_quote(invalid):
    raw = quotes()
    invalid_quote = raw.iloc[[599]].copy()
    invalid_quote.index += pd.Timedelta("500ms")
    if invalid == "locked":
        invalid_quote[["bid_price", "ask_price"]] = 100.
    else:
        invalid_quote[["bid_size", "ask_size"]] = 0.
    raw = pd.concat([raw, invalid_quote]).sort_index(kind="stable")
    result = record(raw, max_quote_age="2s")
    assert result.l1["AAA"]["status"] == "unavailable"
    assert "Latest observed quote" in result.l1["AAA"]["reason"]
    assert result.base_mu == {"AAA": .0012}
    assert result.candidate_mu is None


def test_qi_microprice_and_ridge_keep_distinct_targets_without_changing_bar_mu():
    raw = quotes()
    before = raw.index[200]
    models = dict(qi=QueueImbalanceModel().fit(raw, before=before),
                  microprice=TransitionMicroprice().fit(raw, before=before),
                  ridge_5s=L1Ridge().fit(raw, before=before, horizon="5s"))
    result = record(raw, l1_models={"AAA": models})
    diagnostics = result.l1["AAA"]["models"]
    assert all(item["status"] == "available" for item in diagnostics.values())
    assert 0 <= diagnostics["qi"]["value"] <= 1
    assert diagnostics["qi"]["target"] == "next_iex_mid_move_up"
    assert diagnostics["qi"]["horizon_seconds"] is None
    assert diagnostics["ridge_5s"]["horizon_seconds"] == 5
    assert diagnostics["ridge_5s"]["target"] == "future_iex_mid_return_not_executable_pnl"
    assert "transition_correction_bps" in diagnostics["microprice"]["value"]
    assert result.horizon_seconds == 300
    assert result.base_mu == {"AAA": .0012}
    assert result.candidate_mu is None


@pytest.mark.parametrize("problem", ["future_training", "clock", "schema", "target", "immature_labels"])
def test_incompatible_l1_models_are_diagnostics_unavailable_not_trading_vetoes(problem):
    raw = quotes()
    model = L1Ridge().fit(raw, before=raw.index[200])
    if problem == "future_training":
        model.artifact["trained_before"] = "2026-09-02T09:30:00-04:00"
    elif problem == "clock":
        model.artifact["contract"]["clock"] = "recorded_arrival"
    elif problem == "schema":
        model.artifact["feature_version"] = "wrong"
    elif problem == "target":
        model.artifact["target"] = "next_open_to_horizon_close_gross_return"
    else:
        model.artifact["last_label_end"] = model.artifact["trained_before"]
    result = record(raw, l1_models={"AAA": {"ridge": model}})
    assert result.l1["AAA"]["status"] == "available"
    assert result.l1["AAA"]["models"]["ridge"]["status"] == "unavailable"
    assert result.base_mu == {"AAA": .0012}
    assert result.candidate_mu is None


def test_unsupported_latest_microprice_state_does_not_backfill_older_prediction():
    raw = quotes()
    model = TransitionMicroprice().fit(raw, before=raw.index[200])
    raw.loc[raw.index[599], ["bid_price", "ask_price"]] = [99., 101.]
    result = record(raw, l1_models={"AAA": {"microprice": model}})
    assert result.l1["AAA"]["models"]["microprice"]["status"] == "unavailable"
    assert "finite" in result.l1["AAA"]["models"]["microprice"]["reason"]


class FusionProtocolFixture:
    """A protocol stub for unit tests, not a fitted or published trading model."""
    def __init__(self, snapshot):
        self.calls = 0
        self.artifact = dict(
            schema_version=1, model="calibrated_l1_fusion", feature_version=VERSION,
            calibration_status="fitted", calibration_method="unit_test_protocol_fixture",
            deployment="research_only", performance_verified=False,
            target=snapshot.base_target, forecast_horizon_seconds=300,
            frequency="5min", features=list(PAPER_L1_FEATURES), symbols=["AAA"],
            trained_before="2026-08-31T16:00:00-04:00", last_label_end="2026-08-31T15:59:59-04:00",
            contracts={"AAA": snapshot.l1["AAA"]["contract"]},
        )

    def predict(self, *, base_mu, features, decision_time, horizon_seconds):
        self.calls += 1
        assert features.index.tolist() == ["AAA"]
        assert features.columns.tolist() == list(PAPER_L1_FEATURES)
        assert features.notna().all().all()
        base_mu["AAA"] = .0008  # A malicious/mutating caller cannot alter the base dict.
        return base_mu


def test_fusion_requires_explicit_compatible_artifact_and_stays_separate():
    raw, forecast = quotes(trades=True), base()
    model = FusionProtocolFixture(record(raw))
    result = record(raw, forecast=forecast, fusion_model=model)
    assert model.calls == 1
    assert result.fusion["status"] == "available"
    assert result.fusion["performance_verified"] is False
    assert result.candidate_mu == {"AAA": .0008}
    assert result.base_mu is forecast.mu
    assert result.base_mu == {"AAA": .0012}
    assert result.to_dict()["active_forecast"] == "base_mu"


@pytest.mark.parametrize("field,value", [
    ("target", "future_iex_mid_return_not_executable_pnl"),
    ("forecast_horizon_seconds", 5), ("feature_version", "wrong"),
    ("trained_before", "2026-09-02T00:00:00-04:00"),
    ("calibration_status", "not_fitted"), ("performance_verified", None),
    ("features", list(reversed(PAPER_L1_FEATURES))),
])
def test_incompatible_fusion_never_runs_or_overwrites_base(field, value):
    raw = quotes(trades=True)
    model = FusionProtocolFixture(record(raw))
    model.artifact = deepcopy(model.artifact)
    model.artifact[field] = value
    result = record(raw, fusion_model=model)
    assert result.fusion["status"] == "unavailable"
    assert result.fusion["reason"]
    assert result.candidate_mu is None
    assert model.calls == 0
    assert result.base_mu == {"AAA": .0012}


def test_missing_current_bucket_does_not_block_fresh_quote_model_but_cannot_fuse():
    raw = quotes()
    model = L1Ridge().fit(raw, before=raw.index[200])
    # Only a fresh partial bucket after a gap remains at the decision.
    raw = pd.concat([raw.iloc[:300], raw.iloc[600:]])
    result = record(raw, decision_time="2026-09-01T09:40:05-04:00", l1_models={"AAA": {"ridge": model}})
    assert result.l1["AAA"]["status"] == "available"
    assert result.l1["AAA"]["models"]["ridge"]["status"] == "available"
    assert result.l1["AAA"]["bucket_is_latest_complete"] is False
    assert result.candidate_mu is None


def test_missing_explicit_base_contract_or_naive_decision_cannot_create_a_record():
    with pytest.raises(ValueError, match="base_target"):
        record(quotes(), base_target="")
    with pytest.raises(ValueError, match="timezone-aware"):
        record(quotes(), decision_time="2026-09-01 09:40")
