"""Causal and capital invariants for the fixed A/C/B price candidate."""

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.quant_policy import NY
from app.research.sentiment_alpha_candidate import PriceCandidate, TextReturnAdjustment, prior_scale


def session(day, seed):
    rng = np.random.default_rng(seed)
    opening = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, 78)))
    close = opening * np.exp(rng.normal(0.0001, 0.001, 78))
    return pd.DataFrame({
        "open": opening, "high": np.maximum(opening, close) * 1.001,
        "low": np.minimum(opening, close) * 0.999, "close": close,
        "volume": rng.integers(100, 2000, 78),
    }, index=pd.date_range(f"{day} 09:30", periods=78, freq="5min", tz=NY))


@pytest.fixture(scope="module")
def histories():
    days = pd.bdate_range("2026-08-03", periods=17).strftime("%Y-%m-%d")
    return {s: pd.concat([session(day, offset + i) for i, day in enumerate(days)])
            for s, offset in (("AAA", 20), ("BBB", 50))}


def test_scale_never_amplifies_or_flips_forecasts():
    assert prior_scale([1, 2], [2, 4]) == 1.0
    assert prior_scale([1, 2], [.5, 1]) == .5
    assert prior_scale([1, 2], [-1, -2]) == 0.0
    assert prior_scale([0, 0], [1, -1]) == 0.0
    with pytest.raises(ValueError, match="Finite"):
        prior_scale([1, np.nan], [1, 2])


def test_future_prices_and_missing_future_bars_cannot_change_fit(histories):
    before = "2026-08-25"
    first = PriceCandidate.fit(histories, before)
    changed = {}
    for s, frame in histories.items():
        item = frame.copy()
        future = item.index >= pd.Timestamp(before, tz=NY)
        item.loc[future, ["open", "high", "low", "close"]] *= 100
        changed[s] = item.drop(item.index[future][-5:])
    second = PriceCandidate.fit(changed, before)
    assert first.audit == second.audit
    assert first.base.estimators == second.base.estimators
    np.testing.assert_array_equal(first.base.covariance, second.base.covariance)
    assert first.audit["base_last_training_session"] < first.audit["calibration_days"][0]
    assert first.audit["calibration_days"][-1] < before
    assert pd.Timestamp(first.audit["last_calibration_label_end"]) < pd.Timestamp(before, tz=NY)


def test_calibration_prices_do_not_enter_base_estimator(histories):
    base = PriceCandidate.fit(histories, "2026-08-25")
    changed = {}
    first_calibration_day = base.audit["calibration_days"][0]
    for s, frame in histories.items():
        item = frame.copy()
        calibration = item.index.date >= pd.Timestamp(first_calibration_day).date()
        item.loc[calibration, ["open", "high", "low", "close"]] *= 7
        changed[s] = item
    other = PriceCandidate.fit(changed, "2026-08-25")
    assert base.base.estimators == other.base.estimators
    np.testing.assert_array_equal(base.base.covariance, other.base.covariance)


def test_prefix_prediction_and_traded_subset_contract(histories):
    model = PriceCandidate.fit(histories, "2026-08-25", traded_symbols=("BBB",))
    day = {s: frame.loc["2026-08-25"] for s, frame in histories.items()}
    full = model.forecast_frames(day)
    prefix = model.forecast_frames({s: frame.iloc[:25] for s, frame in day.items()})
    assert set(full) == {"BBB"}
    pd.testing.assert_series_equal(prefix["BBB"], full["BBB"].iloc[:25])
    assert model.covariance_at(day["AAA"].index[24]).shape == (1, 1)
    with pytest.raises(ValueError, match="overlaps"):
        model.forecast_frames({s: frame.loc["2026-08-24"] for s, frame in histories.items()})


def test_missing_history_does_not_silently_shorten_calibration(histories):
    shortened = {s: frame.loc[:"2026-08-20"] for s, frame in histories.items()}
    with pytest.raises(ValueError, match="ten complete"):
        PriceCandidate.fit(shortened, "2026-08-25")


def test_candidate_preserves_portfolio_limits_shortability_and_close(histories):
    model = PriceCandidate.fit(histories, "2026-08-25")
    stamp = pd.Timestamp("2026-08-25 10:00", tz=NY)
    weights = model.weights(stamp, {}, {"AAA": .05, "BBB": -.05},
                            shortable={"AAA": True, "BBB": False})
    assert weights["BBB"] >= 0
    assert max(map(abs, weights.values())) <= .70 + 1e-10
    assert sum(map(abs, weights.values())) <= .95 + 1e-10
    close = model.weights(pd.Timestamp("2026-08-25 15:50", tz=NY),
                          {"AAA": .3}, {"AAA": .05, "BBB": -.05})
    assert close == {"AAA": 0.0, "BBB": 0.0}


def test_text_adjustment_requires_same_horizon_and_completed_prediction(histories):
    model = PriceCandidate.fit(histories, "2026-08-25")
    stamp = pd.Timestamp("2026-08-25 15:45", tz=NY)
    mu = {"AAA": 0.0, "BBB": 0.0}
    delta = {"AAA": .006, "BBB": -.006}
    valid = TextReturnAdjustment(delta, "2026-08-25T15:50:00-04:00", 6)
    adjusted = model.weights(stamp, {}, mu, text_adjustment=valid)
    # Only five executable minutes remain: full30m text returns scale by1/6.
    expected = model.weights(stamp, {}, {s: value / 6 for s, value in delta.items()})
    assert adjusted == pytest.approx(expected)
    with pytest.raises(ValueError, match="six-bar"):
        model.weights(stamp, {}, mu, text_adjustment=TextReturnAdjustment(delta, valid.available_at, 1))
    with pytest.raises(ValueError, match="available"):
        model.weights(stamp, {}, mu, text_adjustment=TextReturnAdjustment(delta, "2026-08-25T15:50:01-04:00", 6))
