"""Causality and accounting tests; synthetic fixtures are never replay fallback."""

import json

import numpy as np
import pandas as pd
import pytest

from backend.app.research.causal_week_replay import (
    ReplayConfig, prepare_sessions, regular_index, run_ticker,
    session_features, simulate_session, strategy_positions, training_rows,
)


def make_bars(day, slope=0.02, start=100.0):
    opens = start + np.arange(78) * slope
    closes = opens + slope * 0.7
    return pd.DataFrame({
        "Open": opens, "High": np.maximum(opens, closes) + 0.01,
        "Low": np.minimum(opens, closes) - 0.01, "Close": closes,
        "Volume": np.arange(78) + 1000,
    }, index=regular_index(day))


def historical_fixture():
    days = pd.bdate_range("2026-08-03", periods=12).strftime("%Y-%m-%d").tolist()
    return days, pd.concat([make_bars(day, slope=0.02 if i % 3 else -0.01)
                           for i, day in enumerate(days)])


def test_future_bars_cannot_change_earlier_features_or_positions():
    bars = make_bars("2026-09-08")
    changed = bars.copy()
    changed.loc[changed.index[30:], ["Open", "High", "Low", "Close"]] *= 2
    changed.loc[changed.index[30:], "Volume"] *= 10
    pd.testing.assert_frame_equal(session_features(bars).iloc[:30], session_features(changed).iloc[:30])
    for strategy in ("trend_3", "trend_12", "reversal_3"):
        np.testing.assert_array_equal(strategy_positions(bars, strategy)[:31],
                                      strategy_positions(changed, strategy)[:31])


def test_signal_enters_at_next_open_not_signal_bar_open():
    bars = make_bars("2026-09-08")
    positions = strategy_positions(bars, "trend_3")
    assert np.all(positions[:4] == 0)
    assert positions[4] == 1
    _, trades = simulate_session(bars, positions, ReplayConfig())
    first = trades[0]
    assert first["fill_time"] == bars.index[4].isoformat()
    assert first["reference_price"] == bars["Open"].iloc[4]
    assert first["signal_data_cutoff"] == (bars.index[3] + pd.Timedelta(minutes=5)).isoformat()


def test_labels_start_next_open_and_end_within_session():
    bars = make_bars("2026-09-08")
    x, y = training_rows(bars)
    assert len(x) == len(y) == 77
    assert y.iloc[0] == pytest.approx(bars["Open"].iloc[2] / bars["Open"].iloc[1] - 1)
    assert y.iloc[-1] == pytest.approx(bars["Close"].iloc[-1] / bars["Open"].iloc[-1] - 1)
    assert x.index[-1].hour == 15 and x.index[-1].minute == 50


def test_missing_requested_day_never_uses_other_bars():
    bars = make_bars("2026-09-08")
    result = run_ticker("TEST", bars, ["2026-09-09"])
    assert result["daily"] == [{"ticker": "TEST", "date": "2026-09-09", "status": "missing",
                                 "selected_candidate": None, "net_return": None}]
    assert result["summary"]["evaluated_sessions"] == 0
    assert result["summary"]["selected_compounded_return_on_evaluated_sessions"] is None
    assert not result["candidate_daily"]


def test_incomplete_duplicate_naive_and_invalid_ohlcv_rejected():
    bars = make_bars("2026-09-08")
    sessions, coverage = prepare_sessions(bars.drop(bars.index[20]), ["2026-09-08"])
    assert not sessions and coverage[0]["status"] == "incomplete"
    assert coverage[0]["missing_bars"] == 1
    sessions, coverage = prepare_sessions(pd.concat([bars, bars.iloc[[20]]]), ["2026-09-08"])
    assert not sessions and coverage[0]["duplicate_bars"] == 1
    invalid = bars.copy()
    invalid.iloc[10, invalid.columns.get_loc("High")] = 0
    sessions, coverage = prepare_sessions(invalid, ["2026-09-08"])
    assert not sessions and coverage[0]["invalid_ohlcv"]
    with pytest.raises(ValueError, match="timezone-aware"):
        prepare_sessions(bars.tz_localize(None), ["2026-09-08"])


def test_costs_charge_entries_reversal_and_exit():
    bars = make_bars("2026-09-08", slope=0)
    positions = np.zeros(78)
    positions[1] = 1
    positions[2] = -1
    config = ReplayConfig(slippage_bps=2, commission_bps=1)
    result, trades = simulate_session(bars, positions, config)
    c = 0.0003
    assert result["net_return"] == pytest.approx((1 - c) ** 2 * (1 - 2 * c) - 1)
    assert result["gross_return"] == 0
    assert result["turnover"] == 4
    assert result["trade_count"] == 2
    assert len(trades) == 3
    assert result["cost_fraction_of_day_start_equity"] == pytest.approx(-result["net_return"])
    assert result["slippage_cost_fraction"] == pytest.approx(2 * result["commission_cost_fraction"])
    assert result["max_drawdown"] == pytest.approx(result["net_return"])


def test_benchmark_roundtrip_and_session_close_liquidation():
    bars = make_bars("2026-09-08")
    no_costs = ReplayConfig(slippage_bps=0, commission_bps=0)
    result, trades = simulate_session(bars, strategy_positions(bars, "buy_hold_session"), no_costs)
    assert result["net_return"] == pytest.approx(bars["Close"].iloc[-1] / bars["Open"].iloc[0] - 1)
    assert result["trade_count"] == 1 and len(trades) == 2
    assert trades[-1]["fill_time"] == "2026-09-08T16:00:00-04:00"
    assert trades[-1]["to_position"] == 0


def test_test_data_cannot_change_its_selection_or_validation():
    days, bars = historical_fixture()
    config = ReplayConfig(min_train_sessions=3, validation_sessions=2)
    baseline = run_ticker("TEST", bars, days[-3:], config)
    changed = bars.copy()
    final_day = changed.index.strftime("%Y-%m-%d") == days[-1]
    changed.loc[final_day, ["Open", "High", "Low", "Close"]] = make_bars(days[-1], slope=-0.3, start=150).iloc[:, :4].to_numpy()
    changed.loc[final_day, "Volume"] *= 100
    after = run_ticker("TEST", changed, days[-3:], config)
    assert baseline["daily"][:2] == after["daily"][:2]
    assert baseline["validation"] == after["validation"]
    assert baseline["daily"][-1]["selected_candidate"] == after["daily"][-1]["selected_candidate"]
    assert baseline["daily"][-1]["selection_score"] == after["daily"][-1]["selection_score"]
    for row in baseline["validation"]:
        assert row["validation_date"] < row["test_date"]
        if row["model_train_last_date"]:
            assert row["model_train_last_date"] < row["validation_date"]
    for row in baseline["candidate_daily"]:
        if row["model_train_last_date"]:
            assert row["model_train_last_date"] < row["date"]


def test_insufficient_history_is_unavailable_not_profitable_flat_result():
    result = run_ticker("TEST", make_bars("2026-09-08"), ["2026-09-08"])
    assert result["daily"][0]["status"] == "insufficient_validation"
    assert result["daily"][0]["net_return"] is None
    ml = next(row for row in result["candidate_daily"] if row["candidate"] == "ml_ridge")
    assert ml["status"] == "insufficient_training"
    assert "net_return" not in ml


def test_cost_stress_preserves_daily_choices_and_exposure_sequence():
    days, bars = historical_fixture()
    baseline = run_ticker("TEST", bars, days[-2:], ReplayConfig(slippage_bps=2))
    # CLI summaries must serialize native counts even when returns use NumPy.
    json.dumps(baseline["summary"])
    fixed = {row["date"]: row["selected_candidate"] for row in baseline["daily"]}
    stress = run_ticker("TEST", bars, days[-2:], ReplayConfig(slippage_bps=5), fixed_selections=fixed)
    assert [r["selected_candidate"] for r in stress["daily"]] == list(fixed.values())
    fields = ("date", "candidate", "fill_time", "from_position", "to_position", "reference_price")
    original_events = [tuple(r[key] for key in fields) for r in baseline["trades"] if r["is_selected"]]
    stressed_events = [tuple(r[key] for key in fields) for r in stress["trades"] if r["is_selected"]]
    assert original_events == stressed_events
    for base, high_cost in zip(baseline["daily"], stress["daily"]):
        assert high_cost["net_return"] <= base["net_return"]
        assert high_cost["selection_mode"] == "fixed_external_daily_choices"


@pytest.mark.parametrize("price_multiplier", [2.0, 3.0])
def test_insolvent_short_path_is_an_unsupported_model_case(price_multiplier):
    bars = make_bars("2026-09-08", slope=0)
    bars.iloc[1:, :4] *= price_multiplier
    with pytest.raises(ValueError, match="unsupported insolvent path"):
        simulate_session(bars, -np.ones(len(bars)), ReplayConfig())
