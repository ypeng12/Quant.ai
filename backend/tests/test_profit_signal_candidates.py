"""Small synthetic causal/decision-contract tests; never real-data training."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from app.research.profit_signal_candidates import (
    CANDIDATES, INPUT_SYMBOLS, TRADED_SYMBOLS, ProfitSignalModel,
    SignalHoldingState, executable_open_labels, profit_signal_features,
)


@pytest.fixture(scope="module")
def bars():
    rng = np.random.default_rng(281026)
    days = pd.bdate_range("2026-08-03", periods=11)
    index = pd.DatetimeIndex([t for d in days for t in pd.date_range(
        f"{d.date()} 09:30", periods=78, freq="5min", tz="America/New_York")])
    output = {}
    for j, symbol in enumerate(INPUT_SYMBOLS):
        opening = (100 + 30 * j) * np.exp(np.cumsum(rng.normal(0, .0008, len(index))))
        close = opening * (1 + rng.normal(0, .0003, len(index)))
        output[symbol] = pd.DataFrame(dict(open=opening,
            high=np.maximum(opening, close) + .1, low=np.minimum(opening, close) - .1,
            close=close, volume=rng.integers(1000, 10000, len(index))), index=index)
    return output


@pytest.fixture(scope="module")
def fitted(bars):
    return ProfitSignalModel.fit(bars, "2026-08-17", CANDIDATES["ridge30_plan"])


def test_future_data_cannot_change_training_or_prefix_features(bars, fitted):
    cutoff = pd.Timestamp("2026-08-17", tz="America/New_York")
    changed = {s: f.copy() for s, f in bars.items()}
    for f in changed.values():
        f.loc[f.index >= cutoff, ["open", "high", "low", "close", "volume"]] *= 3
    other = ProfitSignalModel.fit(changed, cutoff, CANDIDATES["ridge30_plan"])
    assert other.models == fitted.models
    assert other.audit == fitted.audit
    np.testing.assert_array_equal(other.covariance, fitted.covariance)
    before = profit_signal_features(bars)
    after = profit_signal_features(changed)
    for s in TRADED_SYMBOLS:
        pd.testing.assert_frame_equal(before[s].loc[before[s].index < cutoff], after[s].loc[after[s].index < cutoff])
    assert len(fitted.feature_names) == 21
    assert all(pd.Timestamp(r["last_label_end"]) < cutoff for r in fitted.audit["training_fits"])


def test_labels_are_next_open_not_same_close_and_reject_gaps(bars):
    frame = bars["NVDA"].copy()
    labels, ends = executable_open_labels(frame, 6)
    assert labels.iloc[0] == pytest.approx(frame.open.iloc[7] / frame.open.iloc[1] - 1)
    assert ends.iloc[0] == frame.index[7]
    changed = frame.copy()
    changed["close"] = changed.open
    np.testing.assert_allclose(executable_open_labels(changed, 6)[0], labels, equal_nan=True)
    missing = frame.drop(frame.index[3])
    assert np.isnan(executable_open_labels(missing, 6)[0].iloc[0])
    assert labels.loc[labels.index.strftime("%H:%M") >= "15:25"].isna().all()


def _fixed_model(candidate):
    model = ProfitSignalModel()
    model.candidate, model.symbols = candidate, TRADED_SYMBOLS
    model.trained_before = pd.Timestamp("2026-08-17", tz="America/New_York")
    model.covariance = np.eye(candidate.max_hold_bars * len(TRADED_SYMBOLS)) * 1e-8
    return model


def _forecasts(candidate, nvda=0.012, sndk=0., tsla=0.):
    return {s: {h: value * h / candidate.max_hold_bars for h in candidate.horizons}
            for s, value in zip(TRADED_SYMBOLS, (nvda, sndk, tsla))}


@pytest.mark.parametrize("candidate", CANDIDATES.values())
def test_positive_edge_can_enter_but_below_roundtrip_edge_cannot(candidate):
    model = _fixed_model(candidate)
    stamp = pd.Timestamp("2026-08-17 10:00", tz="America/New_York")
    current = dict.fromkeys(TRADED_SYMBOLS, 0.)
    weights, detail = model.allocate(stamp, current, _forecasts(candidate), state=SignalHoldingState(), cost_bps=5.)
    assert weights["NVDA"] > .65
    assert sum(abs(v) for v in weights.values()) <= .95 + 1e-8
    assert max(abs(v) for v in weights.values()) <= .70 + 1e-8
    assert detail["round_trip_cost_bps"] == 10
    tiny, _ = model.allocate(stamp, current, _forecasts(candidate, nvda=.0005), state=SignalHoldingState(), cost_bps=5.)
    assert max(abs(v) for v in tiny.values()) < 1e-6


def test_expiry_is_per_stock_and_resize_does_not_restart_signal():
    candidate = CANDIDATES["ridge30_plan"]
    model, state = _fixed_model(candidate), SignalHoldingState()
    stamp = pd.Timestamp("2026-08-17 10:00", tz="America/New_York")
    forecast = _forecasts(candidate, sndk=.012)
    current = dict(NVDA=.2, SNDK=0., TSLA=0.)
    model.allocate(stamp, current, forecast, state=state)
    current.update(NVDA=.4, SNDK=.2)
    _, second = model.allocate(stamp + pd.Timedelta(minutes=10), current, forecast, state=state)
    assert second["signal_expires_at"]["NVDA"].endswith("10:30:00-04:00")
    assert second["signal_expires_at"]["SNDK"].endswith("10:40:00-04:00")
    weights, expired = model.allocate(stamp + pd.Timedelta(minutes=25), current, forecast, state=state)
    assert weights["NVDA"] == pytest.approx(0., abs=1e-8)
    assert weights["SNDK"] > .1
    assert expired["expired_symbols"] == ["NVDA"]
    # A failed close cannot silently renew an expired signal.
    still, _ = model.allocate(stamp + pd.Timedelta(minutes=30), current, forecast, state=state)
    assert still["NVDA"] == pytest.approx(0., abs=1e-8)
    current["NVDA"] = 0.
    reopened, _ = model.allocate(stamp + pd.Timedelta(minutes=35), current, forecast, state=state)
    assert reopened["NVDA"] > .1


def test_exit_can_precede_expiry_and_long_only_cannot_short():
    stamp = pd.Timestamp("2026-08-17 10:00", tz="America/New_York")
    current = dict(NVDA=.3, SNDK=0., TSLA=0.)
    candidate = CANDIDATES["ridge30_plan"]
    model = _fixed_model(candidate)
    weights, _ = model.allocate(stamp, current, _forecasts(candidate, nvda=-.012), state=SignalHoldingState())
    assert weights["NVDA"] < 0
    long = replace(candidate, name="long_fixture", long_only=True)
    weights, _ = _fixed_model(long).allocate(stamp, current, _forecasts(long, nvda=-.012), state=SignalHoldingState())
    assert min(weights.values()) >= -1e-8
    assert weights["NVDA"] == pytest.approx(0., abs=1e-8)


def test_forecast_prefix_and_single_vs_plan_share_the_same_model(bars, fitted):
    cutoff = pd.Timestamp("2026-08-17", tz="America/New_York")
    today = {s: f.loc[f.index >= cutoff] for s, f in bars.items()}
    prefix = {s: f.iloc[:20] for s, f in today.items()}
    all_predictions, first_predictions = fitted.forecast_frames(today), fitted.forecast_frames(prefix)
    for s in TRADED_SYMBOLS:
        pd.testing.assert_frame_equal(all_predictions[s].iloc[:20], first_predictions[s])
    single = ProfitSignalModel.fit(bars, cutoff, CANDIDATES["ridge30_single"])
    assert single.models == fitted.models
    np.testing.assert_array_equal(single.covariance, fitted.covariance)
    with pytest.raises(ValueError, match="overlaps training"):
        fitted.forecast_frames(bars)


def test_session_end_and_state_validation():
    c = CANDIDATES["ridge30_plan"]
    m, state = _fixed_model(c), SignalHoldingState()
    current = dict(NVDA=.2, SNDK=0., TSLA=0.)
    stamp = pd.Timestamp("2026-08-17 15:50", tz="America/New_York")
    weights, info = m.allocate(stamp, current, _forecasts(c), state=state)
    assert not any(weights.values())
    assert info["reason"] == "scheduled_session_close"
    with pytest.raises(ValueError, match="chronological"):
        m.allocate(stamp - pd.Timedelta(minutes=5), current, _forecasts(c), state=state)
    with pytest.raises(ValueError, match="start flat"):
        m.allocate(stamp + pd.Timedelta(days=1), current, _forecasts(c), state=state)
