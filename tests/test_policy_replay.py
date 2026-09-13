"""Accounting, causality and selection tests, never used as research input data."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.quant_policy import PolicySpec, integer_targets
from backend.app.research.causal_week_replay import regular_index
from backend.app.research.policy_replay import (
    ExecutionConfig, ShareLedger, complete_universe, fixed_order_cost_stress,
    replay_day,
)


def bars(day="2026-09-08", start=100.0, slope=0.0):
    opens = start + np.arange(78) * slope
    close = opens + slope / 2
    return pd.DataFrame({
        "Open": opens, "High": np.maximum(opens, close) + 0.01,
        "Low": np.minimum(opens, close) - 0.01, "Close": close,
        "Volume": np.full(78, 1000.0),
    }, index=regular_index(day))


def sizer(weights, prices, equity):
    return integer_targets(weights, prices, equity, PolicySpec("test"))


def test_shares_are_not_implicitly_rebalanced_as_prices_change():
    frame = bars(slope=0.1)
    ledger = ShareLedger(["A"], ExecutionConfig(slippage_bps=0))
    daily = replay_day(ledger, {"A": frame}, "2026-09-08", None, sizer, {"A": 0.5})
    assert len(ledger.fills) == 2
    assert ledger.fills[0]["quantity"] == 500
    assert ledger.fills[1]["quantity"] == -500
    assert ledger.fills[1]["fill_time"] == "2026-09-08T15:55:00-04:00"
    assert daily["net_pnl"] == pytest.approx(500 * (frame.Open.iloc[-1] - frame.Open.iloc[0]))
    assert ledger.cash == daily["ending_equity"]
    holding_marks = [m for m in ledger.marks if m["A_shares"] != 0]
    assert set(m["A_shares"] for m in holding_marks) == {500}
    assert holding_marks[-1]["A_weight"] != holding_marks[0]["A_weight"]


def test_completed_bar_signal_fills_next_open_and_not_its_own_open():
    frame = bars(slope=1.0)
    ledger = ShareLedger(["A"], ExecutionConfig(slippage_bps=0))
    replay_day(ledger, {"A": frame}, "2026-09-08", lambda i, w: {"A": 0.5}, sizer)
    first = ledger.fills[0]
    assert first["fill_time"] == "2026-09-08T09:35:00-04:00"
    assert first["signal_data_cutoff"] == first["fill_time"]
    assert first["reference_price"] == frame.Open.iloc[1]
    assert first["reference_price"] != frame.Open.iloc[0]


def test_gap_does_not_resize_integer_intent_fixed_at_signal_close():
    frame = bars()
    frame.iloc[1:, :4] *= 1.25
    ledger = ShareLedger(["A"], ExecutionConfig(slippage_bps=0))
    replay_day(ledger, {"A": frame}, "2026-09-08",
               lambda i, w: {"A": 0.5} if i == 0 else w, sizer)
    first = ledger.fills[0]
    assert first["reference_price"] == 125
    assert first["quantity"] == 500  # 100k * .5 / known 100 close, not 125 future open.


def test_short_proceeds_do_not_create_extra_buying_power_and_all_costs_reconcile():
    config = ExecutionConfig(slippage_bps=2, commission_bps=1)
    ledger = ShareLedger(["A", "B"], config)
    prices, time = {"A": 100.0, "B": 100.0}, pd.Timestamp("2026-09-08 10:00", tz="America/New_York")
    ledger.execute_targets({"A": -700, "B": 700}, prices, time, time, "2026-09-08")
    state = ledger.state(prices)
    assert ledger.cash > 100_000
    assert state["gross_exposure"] <= config.gross_limit + 1e-12
    assert max(abs(w) for w in state["weights"].values()) <= config.symbol_limit + 1e-12
    assert sum(abs(q) for q in ledger.shares.values()) < 1_000
    ledger.execute_targets({"A": 0, "B": 0}, prices, time, None, "2026-09-08")
    assert ledger.cash == pytest.approx(config.starting_equity - ledger.costs)
    assert sum(ledger.symbol_cash.values()) == pytest.approx(-ledger.costs)
    assert sum(f["slippage_cost"] for f in ledger.fills) == pytest.approx(
        2 * sum(f["commission_cost"] for f in ledger.fills))


def test_reductions_release_capital_before_additions_and_never_force_one_share():
    config = ExecutionConfig(slippage_bps=0)
    ledger = ShareLedger(["A", "B"], config)
    prices, time = {"A": 100.0, "B": 100.0}, pd.Timestamp("2026-09-08 10:00", tz="America/New_York")
    ledger.execute_targets({"A": 700, "B": 0}, prices, time, None, "2026-09-08")
    ledger.execute_targets({"A": 0, "B": 700}, prices, time, time, "2026-09-08")
    assert [(r["symbol"], r["quantity"]) for r in ledger.fills] == [("A", 700), ("A", -700), ("B", 700)]
    tiny = ShareLedger(["A"], config, starting_equity=1)
    tiny.execute_targets({"A": 1}, {"A": 100.0}, time, time, "2026-09-08")
    assert tiny.shares["A"] == 0 and not tiny.fills and tiny.cash == 1


def test_portfolio_pnl_reconciles_to_each_symbol_with_long_short_reversal():
    frames = {"A": bars(slope=0.1), "B": bars(start=150, slope=-0.15)}
    ledger = ShareLedger(["A", "B"], ExecutionConfig(slippage_bps=2))

    def targets(i, weights):
        return {"A": 0.4 if i < 30 else -0.3, "B": -0.4 if i < 30 else 0.3}

    day = replay_day(ledger, frames, "2026-09-08", targets, sizer)
    assert day["net_pnl"] == pytest.approx(day["A_net_pnl"] + day["B_net_pnl"])
    assert day["costs"] == pytest.approx(day["A_costs"] + day["B_costs"])
    assert all(q == 0 for q in ledger.shares.values())
    assert day["max_drawdown"] < 0
    assert day["ending_cash"] == day["ending_equity"]
    # A risk cap may drift with prices; the ledger measures real holdings rather
    # than silently multiplying equity by an idealized target return sequence.
    assert day["max_gross_exposure"] < 1


def test_missing_exact_date_is_rejected_with_no_substitution():
    with pytest.raises(ValueError, match="missing/incomplete"):
        complete_universe({"A": bars()}, ["2026-09-09"])
    with pytest.raises(ValueError, match="missing/incomplete"):
        complete_universe({"A": bars(), "B": bars().iloc[:-1]}, ["2026-09-08"])


def test_fixed_order_stress_preserves_quantities_and_accounts_for_extra_costs():
    config = ExecutionConfig(slippage_bps=2)
    ledger = ShareLedger(["A"], config)
    replay_day(ledger, {"A": bars()}, "2026-09-08", None, sizer, {"A": 0.5})
    quantities = [r["quantity"] for r in ledger.fills]
    stress = fixed_order_cost_stress(ledger.fills, ledger.marks,
                                   ExecutionConfig(slippage_bps=5))
    assert stress["same_quantities_and_reference_prices"]
    assert quantities == [r["quantity"] for r in ledger.fills]
    assert stress["extra_cost"] == pytest.approx(ledger.turnover_dollars * 3 / 10_000)
    assert stress["ending_equity"] == pytest.approx(ledger.cash - stress["extra_cost"])
    assert stress["net_pnl"] == pytest.approx(-stress["costs"])


def test_selection_uses_only_preceding_declared_dates_not_target_results():
    path = Path(__file__).resolve().parents[1] / "scripts/run_policy_research.py"
    spec = importlib.util.spec_from_file_location("research_script_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    history = {
        "A": [{"date": "2026-08-28", "net_return": 0.01}, {"date": "2026-08-31", "net_return": -0.99}],
        "B": [{"date": "2026-08-28", "net_return": 0.005}, {"date": "2026-08-31", "net_return": 20}],
    }
    best, scores = module.select_on_past(history, "2026-08-31", ["2026-08-28"], ["A", "B"])
    assert best == "A"
    history["B"][-1]["net_return"] = 1_000_000
    assert module.select_on_past(history, "2026-08-31", ["2026-08-28"], ["A", "B"]) == (best, scores)
    with pytest.raises(ValueError, match="must precede"):
        module.select_on_past(history, "2026-08-31", ["2026-08-31"], ["A", "B"])
    assert len(module.candidate_grid(2)) == 12


def test_later_session_prices_cannot_change_earlier_fills():
    frame = bars(slope=0.1)
    changed = frame.copy()
    changed.iloc[30:, :4] *= 1.1

    def run(data):
        ledger = ShareLedger(["A"], ExecutionConfig(slippage_bps=0))
        # Deliberately uses only observed row i; future prices never enter size
        # or completed-bar signal before the corresponding execution timestamp.
        replay_day(ledger, {"A": data}, "2026-09-08",
                   lambda i, w: {"A": 0.4 if data.Close.iloc[i] > 101 else 0}, sizer)
        return [f for f in ledger.fills if f["fill_time"] < frame.index[30].isoformat()]

    assert run(frame) == run(changed)
