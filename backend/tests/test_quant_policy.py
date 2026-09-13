"""Causality, timestamp, artifact, and joint-capital invariants for shared policy."""

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.quant_policy import (
    FEATURE_SETS, NY, PolicyModel, PolicySpec, feature_frame, horizon_fraction,
    integer_targets, labeled_frame, panel_feature_frames, target_weights,
)


def session(day="2026-09-08", seed=42):
    rng = np.random.default_rng(seed)
    opening = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, 78)))
    close = opening * np.exp(rng.normal(0.0001, 0.001, 78))
    return pd.DataFrame({
        "Open": opening, "High": np.maximum(opening, close) * 1.001,
        "Low": np.minimum(opening, close) * 0.999, "Close": close,
        "Volume": rng.integers(100, 2000, 78),
    }, index=pd.date_range(f"{day} 09:30", periods=78, freq="5min", tz=NY))


@pytest.fixture
def histories():
    return {
        "AAA": pd.concat([session("2026-09-08", 1), session("2026-09-09", 2), session("2026-09-10", 3)]),
        "BBB": pd.concat([session("2026-09-08", 4), session("2026-09-09", 5), session("2026-09-10", 6)]),
    }


def test_features_are_prefix_causal_and_reset_at_session_boundary():
    bars = session()
    full = feature_frame(bars)
    prefix = feature_frame(bars.iloc[:17])
    pd.testing.assert_frame_equal(prefix, full.iloc[:17])
    prior = session("2026-09-04", 77)
    pd.testing.assert_frame_equal(full, feature_frame(pd.concat([prior, bars])).loc[bars.index], check_freq=False)
    assert set(FEATURE_SETS["price"]) < set(FEATURE_SETS["price_volume"])
    assert not {"vwap_distance", "bar_relative_volume"}.intersection(FEATURE_SETS["price"])


def test_forward_labels_start_at_next_open_and_mature_before_operational_close():
    bars = session()
    spec = PolicySpec("test", horizon_bars=3)
    _, labels = labeled_frame(bars, spec)
    assert labels.iloc[0] == pytest.approx(bars.Close.iloc[3] / bars.Open.iloc[1] - 1)
    # t=15:35 enters15:40, exits15:55. Later signals do not have full h=3 labels.
    assert np.isfinite(labels.loc["2026-09-08 15:35"])
    assert labels.loc["2026-09-08 15:40":].isna().all()
    _, missing = labeled_frame(bars.drop(bars.index[2]), spec)
    assert np.isnan(missing.iloc[0])


def test_fit_excludes_future_and_incomplete_sessions(histories):
    spec = PolicySpec("causality")
    model = PolicyModel.fit(histories, "2026-09-10", spec)
    mutated = {symbol: frame.copy() for symbol, frame in histories.items()}
    for frame in mutated.values():
        frame.loc[frame.index.date >= pd.Timestamp("2026-09-10").date(), ["Open", "High", "Low", "Close"]] *= 50
    other = PolicyModel.fit(mutated, "2026-09-10", spec)
    assert model.estimators == other.estimators
    np.testing.assert_array_equal(model.covariance, other.covariance)
    assert model.trained_last_session == "2026-09-09"
    assert model.training_sessions == ["2026-09-08", "2026-09-09"]
    truncated = {symbol: frame.drop(frame.index[0]) for symbol, frame in histories.items()}
    incomplete_model = PolicyModel.fit(truncated, "2026-09-10", spec)
    assert incomplete_model.training_sessions == ["2026-09-09"]
    assert incomplete_model.excluded_training_sessions["AAA"] == ["2026-09-08"]


def test_batch_prediction_matches_live_prefix_and_end_horizon(histories):
    model = PolicyModel.fit(histories, "2026-09-10", PolicySpec("same", horizon_bars=6))
    day = {symbol: frame.loc["2026-09-10"] for symbol, frame in histories.items()}
    prefixes = {symbol: frame.iloc[:76] for symbol, frame in day.items()}
    live = model.forecast(prefixes)
    assert live.effective_horizon_bars == 1
    for symbol in model.symbols:
        assert live.mu[symbol] == pytest.approx(model.forecast_frame(symbol, day[symbol]).iloc[75])
    np.testing.assert_allclose(live.covariance, model.covariance / 6)
    closing = {symbol: frame.iloc[:77] for symbol, frame in day.items()}
    assert model.target(closing, {"AAA": 0.4, "BBB": -0.2}) == {"AAA": 0.0, "BBB": 0.0}
    assert horizon_fraction(pd.Timestamp("2026-09-10 15:45", tz=NY), model.spec) == 1 / 6


def test_artifact_roundtrip_and_schema_validation(histories, tmp_path):
    model = PolicyModel.fit(histories, "2026-09-10", PolicySpec("json"))
    path = tmp_path / "policy.json"
    model.save(path)
    restored = PolicyModel.load(path)
    for symbol in model.symbols:
        pd.testing.assert_series_equal(model.forecast_frame(symbol, histories[symbol]),
                                       restored.forecast_frame(symbol, histories[symbol]))
    payload = json.loads(path.read_text())
    payload["feature_names"].reverse()
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="feature schema"):
        PolicyModel.load(path)


def test_reject_timezone_guessing_and_misaligned_universe(histories):
    bars = session()
    bars.index = bars.index.tz_localize(None)
    with pytest.raises(ValueError, match="timezone-aware"):
        feature_frame(bars)
    with pytest.raises(ValueError, match="09:30"):
        feature_frame(session().iloc[1:])
    model = PolicyModel.fit(histories, "2026-09-10", PolicySpec("align"))
    with pytest.raises(ValueError, match="aligned"):
        model.forecast({"AAA": histories["AAA"].iloc[:-1], "BBB": histories["BBB"]})


def test_optimizer_signed_expectations_joint_budget_and_borrow():
    spec = PolicySpec("budget", cost_bps=0, risk_aversion=1, gross_limit=0.95, symbol_limit=0.7)
    symbols = ("A", "B", "C", "D")
    mu = {"A": 0.01, "B": -0.02, "C": 0.03, "D": -0.04}
    weights = target_weights(mu, np.eye(4) * 0.0001, {}, spec, symbols=symbols)
    assert sum(map(abs, weights.values())) <= spec.gross_limit + 1e-12
    assert max(map(abs, weights.values())) <= spec.symbol_limit + 1e-12
    assert weights["D"] < 0 and weights["C"] > 0
    restricted = target_weights(mu, np.eye(4) * 0.0001, {}, spec, shortable={symbol: False for symbol in symbols})
    assert all(weight >= 0 for weight in restricted.values())


def test_cost_discourages_unnecessary_turnover_without_a_signal_veto():
    covariance = np.array([[0.001]])
    current = {"A": 0.4}
    # Risk-adjusted optimum exactly equals current holdings, with nonzero mu.
    balanced = target_weights({"A": 0.0004}, covariance, current,
                              PolicySpec("hold", risk_aversion=1, cost_bps=5))
    assert balanced["A"] == pytest.approx(0.4, abs=1e-7)
    free = target_weights({"A": 0.0001}, covariance, current,
                          PolicySpec("free", risk_aversion=1, cost_bps=0))
    costly = target_weights({"A": 0.0001}, covariance, current,
                            PolicySpec("costly", risk_aversion=1, cost_bps=5))
    assert abs(costly["A"] - current["A"]) < abs(free["A"] - current["A"])
    assert costly["A"] == pytest.approx(0.4, abs=1e-7)


def test_optimizer_handles_coincident_turnover_and_gross_boundaries():
    # Regression: a valid active-set initial point previously made SLSQP report
    # incompatible inequalities despite the problem being feasible and convex.
    mu = {"A": 0.00117980381856386, "B": 0.00018232001604293567,
          "C": 0.0002581261303271478, "D": -0.00028487214131528037}
    current = {"A": 0.7, "B": 0.0, "C": 0.09462892840072368, "D": -0.1553710715992756}
    spec = PolicySpec("active-constraints", risk_aversion=10)
    result = target_weights(mu, np.eye(4) * 0.0001, current, spec)
    assert sum(map(abs, result.values())) <= spec.gross_limit + 1e-12

    def utility(weights):
        w = np.array(list(weights.values()))
        w0 = np.array(list(current.values()))
        return np.array(list(mu.values())) @ w - 0.5 * 10 * 0.0001 * w @ w - 0.0002 * abs(w - w0).sum()

    assert utility(result) >= utility(current) - 1e-10


def test_integer_rounding_respects_joint_equity_and_no_forced_share():
    spec = PolicySpec("capital")
    shares = integer_targets({"A": 0.7, "B": 0.7, "C": -0.7},
                             {"A": 100, "B": 200, "C": 300}, 10000, spec)
    gross = sum(abs(shares[symbol]) * price for symbol, price in {"A": 100, "B": 200, "C": 300}.items())
    assert gross <= 10000 * spec.gross_limit
    assert integer_targets({"A": 0.7}, {"A": 800}, 100, spec) == {"A": 0}
    assert integer_targets({"A": -0.7}, {"A": 800}, 100, spec) == {"A": 0}
    almost_integer = np.nextafter(100.0, 0.0)
    assert integer_targets({"A": almost_integer / 1000}, {"A": 1}, 1000, spec) == {"A": 100}
    assert integer_targets({"A": 99.9999 / 1000}, {"A": 1}, 1000, spec) == {"A": 99}
    with pytest.raises(ValueError, match="outside"):
        target_weights({"A": 0.1}, np.eye(1), {"UNMODELED": 0.2}, spec)


def test_artifact_rejects_future_cutoff_and_non_psd_covariance(histories, tmp_path):
    model = PolicyModel.fit(histories, "2026-09-10", PolicySpec("invalid"))
    path = tmp_path / "policy.json"
    model.save(path)
    payload = json.loads(path.read_text())
    payload["trained_before"] = "2026-09-09"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="cutoff"):
        PolicyModel.load(path)
    with pytest.raises(ValueError, match="positive semidefinite"):
        target_weights({"A": 0.01, "B": 0.02}, [[1, 2], [2, 1]], {}, model.spec)


def test_peer_panel_features_are_leave_one_out_and_prefix_causal(histories):
    current = {symbol: frame.loc["2026-09-10"].copy() for symbol, frame in histories.items()}
    frames = panel_feature_frames(current, "price_volume_peer")
    moment = current["AAA"].index[4]
    aaa_return = current["AAA"].Close.iloc[4] / current["AAA"].Close.iloc[3] - 1
    bbb_return = current["BBB"].Close.iloc[4] / current["BBB"].Close.iloc[3] - 1
    assert frames["AAA"].loc[moment, "peer_return_1"] == pytest.approx(bbb_return)
    assert frames["AAA"].loc[moment, "peer_residual_return_1"] == pytest.approx(aaa_return - bbb_return)
    altered = {symbol: frame.copy() for symbol, frame in current.items()}
    altered["BBB"].loc[altered["BBB"].index[20]:, "Close"] *= 2
    altered["BBB"]["High"] = np.maximum(altered["BBB"].High, altered["BBB"].Close)
    altered["BBB"]["Low"] = np.minimum(altered["BBB"].Low, altered["BBB"].Close)
    pd.testing.assert_frame_equal(frames["AAA"].iloc[:20],
                                  panel_feature_frames(altered, "price_volume_peer")["AAA"].iloc[:20])


def test_peer_panel_model_requires_joint_forecast_and_preserves_prefix(histories):
    spec = PolicySpec("peer", feature_set="price_volume_peer")
    model = PolicyModel.fit(histories, "2026-09-10", spec)
    day = {symbol: frame.loc["2026-09-10"] for symbol, frame in histories.items()}
    with pytest.raises(ValueError, match="require all fitted symbols"):
        model.forecast_frame("AAA", day["AAA"])
    full = model.forecast_frames(day)
    prefix = {symbol: frame.iloc[:25] for symbol, frame in day.items()}
    prefix_forecast = model.forecast(prefix)
    assert prefix_forecast.mu["AAA"] == pytest.approx(full["AAA"].iloc[24])
