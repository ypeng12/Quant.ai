"""No constructor startup, credentials, network or broker side effects."""
import ast
import datetime
import math
import json
import threading
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional

import pandas as pd
import numpy as np
import pytest
import pytz

from app.broker.research_execution import closed_bars, plan_rebalance, recalculate_fifo


def bars(day="2026-09-14", periods=8):
    index = pd.date_range(f"{day} 09:30", periods=periods, freq="5min", tz="America/New_York")
    return pd.DataFrame({"Open": 100., "High": 101., "Low": 99., "Close": 100., "Volume": 1000.}, index=index)


def test_current_partial_bar_is_excluded_and_old_session_rejected():
    result = closed_bars(bars(periods=2), pd.Timestamp("2026-09-14 09:37", tz="America/New_York"))
    assert result.index[-1].minute == 30
    with pytest.raises(ValueError, match="current-session"):
        closed_bars(bars(day="2026-09-11"), pd.Timestamp("2026-09-14 10:05", tz="America/New_York"))
    with pytest.raises(ValueError, match="Stale"):
        closed_bars(bars(periods=2), pd.Timestamp("2026-09-14 10:05", tz="America/New_York"))


def plan(targets, positions=(), orders=(), equity=1000, buying_power=1000):
    return plan_rebalance(targets, positions, {"A": 100, "B": 100}, orders,
                          equity=equity, buying_power=buying_power, gross_limit=.95,
                          buying_power_utilization=.95, cycle_id="bar1")


def test_cannot_invent_capital_or_force_one_share():
    assert plan({"A": 1}, equity=99, buying_power=99) == []
    result = plan({"A": 9, "B": 9})
    assert sum(item.quantity * 100 for item in result) <= 950


def test_reductions_precede_entries_and_reversal_waits_for_confirmed_flat():
    positions = [{"ticker": "A", "shares": 5, "current_price": 100}]
    first = plan({"A": -5, "B": 4}, positions)
    assert len(first) == 1 and first[0].symbol == "A" and first[0].reducing
    assert first[0].side == "sell" and first[0].quantity == 5
    second = plan({"A": -5, "B": 4})
    assert second[0].side == "sell" and not second[0].reducing


def test_pending_orders_reserve_exposure_and_prevent_duplicate_symbol_order():
    pending = [{"ticker": "A", "qty": 6, "filled_qty": 2, "status": "partially_filled", "side": "buy"}]
    result = plan({"A": 9, "B": 9}, [{"ticker": "A", "shares": 2, "current_price": 100}], pending)
    assert all(item.symbol != "A" for item in result)
    assert sum(item.quantity * 100 for item in result) <= 350


def test_fractional_old_holding_closes_without_truncation():
    result = plan({"A": 0}, [{"ticker": "A", "shares": -.25, "current_price": 100}])
    assert result[0].quantity == .25 and result[0].side == "buy"


def test_authoritative_position_mark_is_not_overwritten_by_stale_bar_close():
    result = plan({"A": 4, "B": 9}, [{"ticker": "A", "shares": 4, "current_price": 200}])
    assert len(result) == 1 and result[0].symbol == "B" and result[0].quantity == 1


def test_symbol_cap_includes_current_marks_and_execution_costs():
    result = plan_rebalance({"A": 7}, [{"ticker": "A", "shares": 3, "current_price": 120}], {"A": 100}, [],
                            equity=1000, buying_power=1000, gross_limit=.95, symbol_limit=.7,
                            buying_power_utilization=.95, cost_bps=5, cycle_id="one")
    assert len(result) == 1 and result[0].quantity == 2
    assert 5 * 120 <= .7 * (1000 - 2 * 120 * .0005)


def test_completed_partial_target_gets_distinct_id_for_same_quantity_same_bar():
    first = plan({"A": 4}, buying_power=220)
    second = plan({"A": 4}, [{"ticker": "A", "shares": 2, "current_price": 100}], buying_power=220)
    assert first[0].quantity == second[0].quantity == 2
    assert first[0].client_order_id != second[0].client_order_id


def test_duplicate_bars_are_rejected():
    frame = bars(periods=2)
    with pytest.raises(ValueError, match="Duplicate"):
        closed_bars(pd.concat([frame, frame]), pd.Timestamp("2026-09-14 09:40", tz="America/New_York"))


def test_short_fifo_crosses_sessions_and_preserves_broker_action_and_quantity():
    rows = [
        {"time": "2026-09-10 14:00", "ticker": "A", "action": "SHORT", "shares": 2.5, "price": 100},
        {"time": "2026-09-11 10:00", "ticker": "A", "action": "PARTIAL_COVER", "shares": 1.5, "price": 90},
        {"time": "2026-09-11 11:00", "ticker": "A", "action": "BUY_TO_COVER", "shares": 1, "price": 80},
    ]
    recalculate_fifo(rows)
    assert [row["pnl"] for row in rows] == [0, 15, 20]
    assert rows[1]["action"] == "PARTIAL_COVER" and rows[1]["shares"] == 1.5
    assert all(row["pnl_complete"] for row in rows)


def test_tier_two_short_and_buy_aliases_participate_in_fifo():
    rows = [
        {"time": "1", "ticker": "A", "action": "TIER2_ADD_SHORT", "shares": 2, "price": 100},
        {"time": "2", "ticker": "A", "action": "BUY", "shares": 2, "price": 90},
        {"time": "3", "ticker": "B", "action": "TIER2_ADD_BUY", "shares": 1, "price": 90},
        {"time": "4", "ticker": "B", "action": "SELL", "shares": 1, "price": 100},
    ]
    recalculate_fifo(rows)
    assert rows[1]["pnl"] == 20 and rows[1]["matched_closing_qty"] == 2
    assert rows[3]["pnl"] == 10


def test_unknown_opening_basis_is_not_fabricated_and_unfilled_order_not_counted():
    rows = [
        {"time": "2026-09-11 10:00", "ticker": "A", "action": "COVER", "shares": 2, "price": 90},
        {"time": "2026-09-11 11:00", "ticker": "B", "action": "BUY", "shares": 1, "price": 100, "order_status": "accepted"},
        {"time": "2026-09-11 12:00", "ticker": "B", "action": "SELL", "shares": 1, "price": 150},
    ]
    recalculate_fifo(rows)
    assert rows[0]["unknown_basis_qty"] == 2 and not rows[0]["pnl_complete"]
    assert rows[1]["accounting_status"] == "unconfirmed_order"
    assert rows[2]["pnl"] == 0 and not rows[2]["pnl_complete"]


@pytest.fixture
def runner_type():
    # Importing the service's dependency tree loads environment/broker helpers.
    # Compile the class only and never execute its auto-starting constructor.
    source = Path(__file__).parents[1] / "app/broker/live_runner.py"
    node = next(item for item in ast.parse(source.read_text()).body if isinstance(item, ast.ClassDef))
    namespace = {"Dict": Dict, "List": List, "Optional": Optional, "pd": pd, "json": json, "threading": threading, "__file__": str(source),
                 "datetime": datetime, "math": math, "os": os, "pytz": pytz,
                 "MockAlpacaAdapter": type("Mock", (), {}), "closed_bars": closed_bars,
                 "plan_rebalance": plan_rebalance, "TERMINAL_STATUSES": {"filled", "rejected", "canceled"},
                 "recalculate_fifo": recalculate_fifo,
                 "load_watchlist": lambda: ["A"],
                 "fetch_and_prepare_data": lambda *args, **kwargs: bars()}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["LiveTradingRunner"]


def test_runner_accepted_order_does_not_fabricate_fill_and_repeated_bar_forecasts_once(runner_type):
    from app.quant_policy import PolicySpec
    runner = runner_type.__new__(runner_type)
    submitted, calls = [], []
    spec = PolicySpec(name="test")

    def submit(symbol, qty, side, **kwargs):
        submitted.append({"ticker": symbol, "qty": qty, "side": side,
                          "status": "accepted", "client_order_id": kwargs["client_order_id"]})
        return {"success": True, "status": "accepted", "order_id": "order-1"}

    def forecast(frames):
        calls.append(True)
        return SimpleNamespace(mu={"A": .01}, covariance=np.eye(1) * .001)

    runner.adapter = SimpleNamespace(is_paper=True,
        get_clock=lambda: {"success": True, "is_open": True, "timestamp": "2026-09-14T10:05:00-04:00", "next_close": "2026-09-14T16:00:00-04:00"},
        client=SimpleNamespace(get_asset=lambda symbol: SimpleNamespace(shortable=True)), submit_market_order=submit)
    runner.strategy_params = runner_type._quant_policy_defaults()
    runner._quant_broker_snapshot = lambda: (submitted, [], {"equity": 1000., "buying_power": 1000., "shorting_enabled": True})
    runner._quant_model = lambda: SimpleNamespace(symbols=("A",), trained_before="2026-09-12", spec=spec,
        forecast=forecast, target=lambda *args: {"A": .5})
    runner._quant_model_key = ("test", 1)
    runner._quant_submissions, runner._quant_status = {}, {}
    runner._quant_last_bar = None
    runner.trade_history = []
    runner.add_log = lambda message: None
    runner._run_quant_policy_cycle()
    runner._run_quant_policy_cycle()
    assert len(submitted) == 1 and len(calls) == 1
    assert runner.trade_history == []
    assert runner._quant_status["state"] == "ready"
    assert runner.ticker_scores == {}
    # Removing a symbol during the same bar must recompute a flat target, and
    # must not restore the model's old universe on the next cycle.
    runner_type._run_quant_policy_cycle.__globals__["load_watchlist"] = lambda: []
    submitted.clear()
    runner._quant_broker_snapshot = lambda: ([], [{"ticker": "A", "shares": 2, "current_price": 100}], {"equity": 1000., "buying_power": 1000., "shorting_enabled": True})
    runner._run_quant_policy_cycle()
    assert runner._quant_targets == {"A": 0} and runner.active_tickers == []
    assert submitted[-1]["side"] == "sell" and submitted[-1]["qty"] == 2


def test_legacy_settings_are_migrated_without_old_score_filters(runner_type):
    params = runner_type._normalize_quant_params({"strategy_mode": "aggressive_intraday", "entry_score_min": 95, "buying_power_utilization_pct": .6})
    assert params["strategy_mode"] == "quant_policy"
    assert "entry_score_min" not in params
    assert params["buying_power_utilization_pct"] == .6


def test_daily_summary_recognizes_buy_to_cover_and_does_not_invent_official_pnl(runner_type):
    today = datetime.datetime.now(pytz.timezone("America/New_York")).date()
    yesterday = today - datetime.timedelta(days=1)
    runner = runner_type.__new__(runner_type)
    runner.trade_history = recalculate_fifo([
        {"time": f"{yesterday} 10:00", "ticker": "A", "action": "SHORT", "shares": 2, "price": 100},
        {"time": f"{today} 10:00", "ticker": "A", "action": "BUY", "shares": 2, "price": 110},
        {"time": f"{today} 11:00", "ticker": "B", "action": "COVER", "shares": 1, "price": 100},
    ])
    runner.adapter = SimpleNamespace(get_open_positions=lambda: [])
    runner.get_cached_account_summary = lambda: {"success": False}
    result = runner.get_today_summary()
    assert result["closed_trades"] == 1 and result["realized_pnl"] == -20
    assert result["unknown_basis_trades"] == 1 and not result["realized_pnl_complete"]
    assert result["alpaca_official_pnl"] is None and result["official_pnl_source"] == "unavailable"


def closing_runner(runner_type, positions, orders, submit):
    runner = runner_type.__new__(runner_type)
    cancellations = []
    runner.adapter = SimpleNamespace(is_paper=True,
        get_clock=lambda: {"success": True, "is_open": True, "timestamp": "2026-09-14T15:55:00-04:00", "next_close": "2026-09-14T16:00:00-04:00"},
        client=SimpleNamespace(cancel_order_by_id=lambda order_id: cancellations.append(order_id)),
        submit_market_order=submit)
    runner.strategy_params = runner_type._quant_policy_defaults()
    runner._quant_broker_snapshot = lambda: (orders, positions, {"equity": 1000., "buying_power": 1000.})
    runner._quant_submissions, runner._quant_status = {}, {}
    runner._quant_targets = {}
    runner.trade_history = []
    runner.add_log = lambda message: None
    return runner, cancellations


def test_eod_cancels_pending_entry_then_reconciles_partial_fill_before_closing(runner_type):
    positions = [{"ticker": "A", "shares": 2, "current_price": 100}]
    orders = [{"order_id": "working-entry", "ticker": "A", "qty": 5, "filled_qty": 2, "status": "partially_filled", "side": "buy"}]
    submitted = []
    runner, cancellations = closing_runner(runner_type, positions, orders,
        lambda *args, **kwargs: submitted.append(args) or {"success": True, "status": "accepted"})
    runner._run_quant_policy_cycle()
    assert cancellations == ["working-entry"] and submitted == []
    orders.clear()
    positions[0]["shares"] = 3  # One more actual fill before cancellation confirmation.
    runner._run_quant_policy_cycle()
    assert submitted[0][:3] == ("A", 3, "sell")
    assert runner.trade_history == []


def test_terminal_eod_rejection_retries_with_new_id_but_unknown_outcome_does_not(runner_type):
    positions = [{"ticker": "A", "shares": 2, "current_price": 100}]
    client_ids = []

    def submit(*args, **kwargs):
        client_ids.append(kwargs["client_order_id"])
        return {"success": False, "status": "rejected"} if len(client_ids) == 1 else {"success": False, "error": "timeout"}

    runner, _ = closing_runner(runner_type, positions, [], submit)
    runner._run_quant_policy_cycle()
    runner._run_quant_policy_cycle()
    runner._run_quant_policy_cycle()
    assert len(client_ids) == 2 and client_ids[0] != client_ids[1]


def test_eod_does_not_cancel_its_own_working_close(runner_type):
    positions = [{"ticker": "A", "shares": 2, "current_price": 100}]
    orders = [{"order_id": "closing", "client_order_id": "QP-EXIT-test", "ticker": "A", "qty": 2, "filled_qty": 0, "status": "accepted", "side": "sell"}]
    submitted = []
    runner, cancellations = closing_runner(runner_type, positions, orders,
        lambda *args, **kwargs: submitted.append(args) or {"success": True, "status": "accepted"})
    runner._run_quant_policy_cycle()
    runner._run_quant_policy_cycle()
    assert cancellations == [] and submitted == []


def test_paper_only_authorization_applies_to_eod_cancellations_too(runner_type):
    positions = [{"ticker": "A", "shares": 2, "current_price": 100}]
    orders = [{"order_id": "entry", "ticker": "A", "qty": 2, "filled_qty": 0, "status": "accepted", "side": "buy"}]
    submitted = []
    runner, cancellations = closing_runner(runner_type, positions, orders,
        lambda *args, **kwargs: submitted.append(args) or {"success": True, "status": "accepted"})
    runner.adapter.is_paper = False
    runner._run_quant_policy_cycle()
    assert cancellations == [] and submitted == []
    assert runner._quant_status["state"] == "execution_not_authorized"


def test_adapter_distinguishes_known_rejection_from_timeout_and_duplicate():
    import json
    from alpaca.common.exceptions import APIError
    from app.broker.alpaca_adapter import AlpacaAdapter
    refused = APIError(json.dumps({"code": 40310000, "message": "insufficient buying power"}),
                       SimpleNamespace(response=SimpleNamespace(status_code=403)))
    duplicate = APIError(json.dumps({"code": 42210000, "message": "client_order_id must be unique"}),
                         SimpleNamespace(response=SimpleNamespace(status_code=422)))
    assert AlpacaAdapter._submission_error_status(refused) == "rejected"
    assert AlpacaAdapter._submission_error_status(TimeoutError("connection timed out")) == "submission_unknown"
    assert AlpacaAdapter._submission_error_status(duplicate) == "submission_unknown"


def test_regular_session_forecast_reaches_targets_and_submission_without_recording_fake_fill(runner_type):
    from app.quant_policy import PolicySpec
    submitted = []
    runner, _ = closing_runner(runner_type, [], [],
        lambda *a, **k: submitted.append((a, k)) or {"success": True, "status": "accepted"})
    runner.adapter.get_clock = lambda: dict(success=True, is_open=True, timestamp="2026-09-14T10:10:00-04:00", next_close="2026-09-14T16:00:00-04:00")
    runner.adapter.client.get_asset = lambda symbol: SimpleNamespace(shortable=True)
    runner._quant_broker_snapshot = lambda: ([], [], {"equity": 1000., "buying_power": 1000., "shorting_enabled": True})
    model = SimpleNamespace(symbols=("A",), trained_before="2026-09-12", spec=PolicySpec(name="test", feature_set="price_volume"),
                            forecast=lambda frames: SimpleNamespace(mu={"A": .02}, covariance=np.array([[.0001]])))
    runner._quant_model = lambda: model
    runner._quant_model_key, runner._quant_last_bar = ("fixture", 1), None
    runner._run_quant_policy_cycle()
    assert runner._quant_status["state"] == "ready"
    assert runner._quant_targets["A"] > 0 and len(submitted) == 1
    assert runner.trade_history == []
    runner._run_quant_policy_cycle()
    assert len(submitted) == 1  # Unknown/working order outcome still reserves the intent.


def test_old_order_filled_today_is_assigned_to_fill_day(runner_type):
    runner = runner_type.__new__(runner_type)
    order = runner._serialize_alpaca_order(dict(id="old", symbol="SNDK", side="buy", qty="17", filled_qty="17", status="filled",
        submitted_at="2026-09-11T20:00:04+00:00", filled_at="2026-09-14T13:33:40+00:00"))
    assert order["date"] == "2026-09-14" and order["time"] == "2026-09-14 09:33:40"
    assert order["filled_qty"] == 17


def test_order_sync_updates_partial_fill_without_duplicate_or_limit_price_pnl(runner_type):
    runner = runner_type.__new__(runner_type)
    runner.adapter = SimpleNamespace(is_paper=True)
    runner.trade_history = [dict(order_id="entry", time="2026-09-11 15:00:00", ticker="TSLA",
                                action="SHORT", shares=10, price=100, order_status="filled")]
    runner.save_trade_history = lambda: None
    runner.add_log = lambda message: None
    order = dict(order_id="cover", client_order_id="QP-EXIT-cover", ticker="TSLA", side="buy",
                 position_intent="buy_to_close", date="2026-09-14", time="2026-09-14 16:01:00",
                 status="accepted", filled_qty=0, filled_avg_price=None, limit_price=105)
    runner.sync_alpaca_orders_to_history(snapshot=dict(success=True, orders=[order]))
    assert len(runner.trade_history) == 1
    partial = {**order, "status": "partially_filled", "filled_qty": 3, "filled_avg_price": 90}
    assert runner.sync_alpaca_orders_to_history(snapshot=dict(success=True, orders=[partial]))["added"] == 1
    assert runner.trade_history[-1]["pnl"] == 30
    filled = {**partial, "status": "filled", "filled_qty": 10, "filled_avg_price": 91}
    runner.sync_alpaca_orders_to_history(snapshot=dict(success=True, orders=[filled]))
    runner.sync_alpaca_orders_to_history(snapshot=dict(success=True, orders=[filled]))
    assert len(runner.trade_history) == 2
    assert runner.trade_history[-1]["shares"] == 10
    assert runner.trade_history[-1]["price"] == 91
    assert runner.trade_history[-1]["pnl"] == 90
