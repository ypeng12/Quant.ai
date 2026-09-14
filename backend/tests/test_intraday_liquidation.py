from types import SimpleNamespace

import pandas as pd
import pytest

from app.broker.intraday_liquidation import extended_session, liquidation_plan, quote_limit
from test_research_execution import runner_type, closing_runner


def calendar(day="2026-09-14", close="16:00"):
    return [dict(date=day, open="09:30", close=close, session_open="0400", session_close="2000")]


def quote(now="2026-09-14T16:01:00-04:00", bid=100, ask=100.02):
    return dict(timestamp=now, bid_price=bid, ask_price=ask)


def plan(positions, orders=(), quotes=None, now="2026-09-14T16:01:00-04:00", session=None):
    return liquidation_plan(positions, orders, quotes or {"TSLA": quote(now)}, now=now,
                            session=session or {"kind": "afterhours", "trade_date": "2026-09-14"})


def position(qty=-10):
    return [dict(ticker="TSLA", shares=qty, current_price=100)]


def test_half_day_weekend_and_sunday_overnight_sessions():
    assert extended_session("2026-11-27T13:05:00-05:00", calendar("2026-11-27", "13:00"))["kind"] == "afterhours"
    assert extended_session("2026-09-12T16:27:00-04:00", calendar())["kind"] == "closed"
    assert extended_session("2026-09-13T20:00:03-04:00", calendar())["kind"] == "overnight"
    assert extended_session("2026-09-14T02:00:00-04:00", calendar())["kind"] == "overnight"
    assert extended_session("2026-09-14T04:00:00-04:00", calendar())["kind"] == "premarket"
    # No calendar session after a holiday evening means no fabricated overnight opening.
    assert extended_session("2026-09-06T20:01:00-04:00", calendar("2026-09-08"))["kind"] == "closed"


def test_flat_account_cancels_old_sell_instead_of_opening_short():
    order = dict(order_id="old-sell", ticker="TSLA", side="sell", qty=10, filled_qty=0,
                 status="accepted", limit_price=300, type="limit", extended_hours=True)
    result = plan([], [order], session={"kind": "closed", "trade_date": "2026-09-12"})
    assert result["cancel"] == ["old-sell"] and result["submit"] == []
    assert not result["flat_confirmed"]


def test_short_cover_and_fractional_long_exit_use_actual_quantities():
    cover = plan(position())["submit"][0]
    assert (cover["side"], cover["quantity"], cover["limit_price"], cover["position_intent"]) == ("buy", 10, 100.02, "buy_to_close")
    sell = plan(position(.25))["submit"][0]
    assert (sell["side"], sell["quantity"], sell["position_intent"]) == ("sell", .25, "sell_to_close")


def test_queued_market_close_is_canceled_before_extended_limit_replacement():
    order = dict(order_id="queued-market", client_order_id="QP-EXIT-old", ticker="TSLA", qty=10,
                 filled_qty=0, side="buy", status="accepted", type="market", extended_hours=False)
    result = plan(position(), [order])
    assert result["cancel"] == ["queued-market"] and result["submit"] == []
    # An additional fill while cancellation is pending is reflected in the next snapshot.
    assert plan(position(-7))["submit"][0]["quantity"] == 7


def test_one_partial_close_is_preserved_but_two_overlapping_closes_are_canceled():
    order = dict(order_id="working", client_order_id="QP-EXIT-old", ticker="TSLA", qty=10,
                 filled_qty=3, side="buy", status="partially_filled", type="limit", extended_hours=True,
                 limit_price=100.02, updated_at="2026-09-14T16:01:00-04:00")
    result = plan(position(-7), [order])
    assert not result["cancel"] and not result["submit"] and not result["flat_confirmed"]
    result = plan(position(-7), [order, {**order, "order_id": "duplicate"}])
    assert set(result["cancel"]) == {"working", "duplicate"} and not result["submit"]


def test_unmarketable_limit_is_canceled_then_resized_after_broker_confirmation():
    order = dict(order_id="stale-limit", client_order_id="QP-EXIT-old", ticker="TSLA", qty=10,
                 filled_qty=0, side="buy", status="accepted", type="limit", extended_hours=True,
                 limit_price=99, updated_at="2026-09-14T16:00:00-04:00")
    result = plan(position(), [order])
    assert result["cancel"] == ["stale-limit"] and not result["submit"]


def test_stale_missing_or_crossed_quotes_never_use_position_mark():
    for bad in [quote("2026-09-11T16:00:00-04:00"), quote(bid=101, ask=100), {}]:
        result = plan(position(), quotes={"TSLA": bad})
        assert not result["submit"] and result["waiting"]["TSLA"] == "awaiting_fresh_quote"
    with pytest.raises(ValueError):
        quote_limit(quote(), "buy", pd.Timestamp("2026-09-14 16:01"), 30)


def afterhours_runner(runner_type, positions, orders, submit):
    runner, canceled = closing_runner(runner_type, positions, orders, lambda *a, **k: pytest.fail("No market order outside regular hours"))
    runner.adapter.get_clock = lambda: dict(success=True, is_open=False,
        timestamp="2026-09-14T16:01:00-04:00", next_close="2026-09-15T16:00:00-04:00")
    runner.adapter.get_liquidation_session = lambda now: dict(kind="afterhours", trade_date="2026-09-14")
    runner.adapter.get_liquidation_quote = lambda symbol, session: quote()
    runner.adapter.submit_limit_order = submit
    return runner, canceled


def test_runner_continues_after_close_and_never_reports_submission_as_flat(runner_type):
    calls = []
    positions = position()
    runner, _ = afterhours_runner(runner_type, positions, [],
        lambda *a, **k: calls.append((a, k)) or dict(success=True, status="accepted"))
    runner._run_quant_policy_cycle()
    runner._run_quant_policy_cycle()
    assert len(calls) == 1 and calls[0][0][:3] == ("TSLA", 10, "buy")
    assert calls[0][1]["position_intent"] == "buy_to_close"
    assert runner._quant_status["state"] == "session_close_pending" and runner.trade_history == []


def test_submission_timeout_is_persisted_before_send_and_survives_restart(runner_type, tmp_path):
    calls = []
    runner, _ = afterhours_runner(runner_type, position(), [], lambda *a, **k: calls.append(k) or dict(success=False, error="timeout"))
    runner._liquidation_state_file = tmp_path / "pending.json"
    runner._run_quant_policy_cycle()
    import json
    saved = json.loads(runner._liquidation_state_file.read_text())["submissions"]
    assert len(saved) == 1 and next(iter(saved.values()))["status"] == "submission_unknown"
    restarted, _ = afterhours_runner(runner_type, position(), [], lambda *a, **k: pytest.fail("Duplicate after restart"))
    restarted._quant_submissions = saved
    restarted._run_quant_policy_cycle()
    assert len(calls) == 1


def test_fully_flat_requires_no_pending_unknown_submissions(runner_type):
    pending = [dict(ticker="TSLA", qty=10, filled_qty=0, side="buy", status="submission_unknown")]
    assert not plan([], pending)["flat_confirmed"]
    assert plan([])["flat_confirmed"]


def test_manual_extended_sell_cannot_reopen_a_flat_account(runner_type):
    runner, _ = afterhours_runner(runner_type, [], [], lambda *a, **k: pytest.fail("Opened a position"))
    result = runner.submit_extended_hours_order("TSLA", 10, "sell", 300)
    assert result["success"] is False and "不能开仓" in result["error"]


def test_failed_cancel_does_not_prevent_other_symbols_cleanup(runner_type):
    orders = [dict(order_id="failed-entry", ticker="NVDA", qty=2, filled_qty=0, side="buy", status="accepted")]
    calls = []
    runner, _ = afterhours_runner(runner_type, position(), orders,
        lambda *a, **k: calls.append(a) or dict(status="accepted"))
    def fail_cancel(order_id):
        raise TimeoutError("cancel outcome unknown")
    runner.adapter.client.cancel_order_by_id = fail_cancel
    runner._run_quant_policy_cycle()
    assert calls[0][:3] == ("TSLA", 10, "buy")
    assert runner._quant_status["cancellation_errors"] == {"failed-entry": "TimeoutError"}
    assert runner._quant_status["waiting"]["NVDA"] == "awaiting_order_reconciliation"


def test_regular_close_cancels_two_orders_that_could_overclose(runner_type):
    orders = [dict(order_id=name, client_order_id="QP-EXIT-" + name, ticker="TSLA", qty=10,
                   filled_qty=0, side="buy", status="accepted") for name in ["first", "second"]]
    runner, canceled = closing_runner(runner_type, position(), orders,
        lambda *a, **k: pytest.fail("Must reconcile both closes before submitting"))
    runner._run_quant_policy_cycle()
    assert set(canceled) == {"first", "second"}


def test_stale_iex_after_close_does_not_report_flat_or_submit(runner_type):
    runner, _ = afterhours_runner(runner_type, position(), [], lambda *a, **k: pytest.fail("Stale quote used"))
    runner.adapter.get_liquidation_quote = lambda *args: quote("2026-09-14T16:00:00-04:00")
    runner._run_quant_policy_cycle()
    assert runner._quant_status["state"] == "session_close_pending"
    assert runner._quant_status["waiting"]["TSLA"] == "awaiting_fresh_quote"


def test_delayed_or_invalid_quote_time_never_becomes_execution_price():
    for timestamp in [None, "NaT", "2026-09-14T15:46:00-04:00"]:
        result = plan(position(), quotes={"TSLA": quote(timestamp)})
        assert not result["submit"]


def test_manual_extended_close_obeys_existing_paper_authorization(runner_type):
    runner, _ = afterhours_runner(runner_type, position(), [], lambda *a, **k: pytest.fail("Live mutation"))
    runner.adapter.is_paper = False
    assert runner.submit_extended_hours_order("TSLA", 10, "buy", 101)["success"] is False


def test_confirmed_empty_position_and_orders_report_flat(runner_type):
    runner, _ = afterhours_runner(runner_type, [], [], lambda *a, **k: pytest.fail("Unneeded close"))
    runner._run_quant_policy_cycle()
    assert runner._quant_status["state"] == "session_flat"


def test_cancel_pending_close_is_not_reissued_or_cancelled_again():
    order = dict(order_id="canceling", client_order_id="QP-EXIT-old", ticker="TSLA", qty=10,
                 filled_qty=0, side="buy", status="pending_cancel", type="limit", extended_hours=True,
                 limit_price=99, updated_at="2026-09-14T16:00:00-04:00")
    result = plan(position(), [order])
    assert not result["submit"] and not result["cancel"]


def test_adapter_extended_close_payload_and_unknown_fill_price(monkeypatch):
    from app.broker.alpaca_adapter import AlpacaAdapter
    from alpaca.trading.enums import PositionIntent, TimeInForce
    requests = []
    adapter = AlpacaAdapter.__new__(AlpacaAdapter)
    def submit(order_data):
        requests.append(order_data)
        return SimpleNamespace(id="order", client_order_id="close-id", status="accepted", filled_qty="0", filled_avg_price=None)
    adapter.client = SimpleNamespace(submit_order=submit)
    result = adapter.submit_limit_order("TSLA", .25, "sell", 100.02, client_order_id="close-id", position_intent="sell_to_close")
    assert requests[0].extended_hours and requests[0].time_in_force == TimeInForce.DAY
    assert requests[0].position_intent == PositionIntent.SELL_TO_CLOSE and requests[0].qty == .25
    assert result["filled_avg_price"] is None and result["filled_qty"] == 0


def test_persisted_unknown_submission_is_reconciled_by_broker_after_restart(runner_type, monkeypatch, tmp_path):
    import json
    source = tmp_path / "backend/app/broker/live_runner.py"
    monkeypatch.setitem(runner_type._load_liquidation_submissions.__globals__, "__file__", str(source))
    owner = {"account_number": "test-paper-account", "equity": 1000, "buying_power": 1000, "success": True}
    original = runner_type.__new__(runner_type)
    original.adapter = SimpleNamespace(base_url="https://paper-api.alpaca.markets")
    original._quant_submissions = {}
    original._load_liquidation_submissions(owner)
    original._quant_submissions["QP-EXIT-unknown"] = dict(client_order_id="QP-EXIT-unknown", base_client_order_id="QP-EXIT-unknown",
        ticker="TSLA", side="buy", qty=10, filled_qty=0, status="submission_unknown", opening_signed_qty=-10)
    original._save_liquidation_submissions()
    assert json.loads(original._liquidation_state_file.read_text())["submissions"]
    restarted = runner_type.__new__(runner_type)
    restarted._quant_submissions = {}
    looked_up = []
    def lookup(client_id):
        looked_up.append(client_id)
        return dict(id="confirmed", client_order_id=client_id, symbol="TSLA", side="buy", qty="10", filled_qty="10", status="filled")
    restarted.adapter = SimpleNamespace(base_url="https://paper-api.alpaca.markets", get_account_summary=lambda: owner,
        client=SimpleNamespace(get_orders=lambda **kw: [], get_order_by_client_id=lookup, get_all_positions=lambda: []))
    orders, positions, _ = restarted._quant_broker_snapshot()
    assert looked_up == ["QP-EXIT-unknown"] and orders == [] and positions == []
    assert restarted._quant_submissions["QP-EXIT-unknown"]["resolved"]
    assert restarted._quant_submissions["QP-EXIT-unknown"]["position_reconciled"]


def test_market_close_between_snapshot_and_submission_never_queues_market_order(runner_type):
    runner, _ = closing_runner(runner_type, position(), [], lambda *a, **k: pytest.fail("Market order queued after close"))
    clocks = iter([
        dict(success=True, is_open=True, timestamp="2026-09-14T15:59:59-04:00", next_close="2026-09-14T16:00:00-04:00"),
        dict(success=True, is_open=False, timestamp="2026-09-14T16:00:01-04:00", next_close="2026-09-15T16:00:00-04:00")])
    runner.adapter.get_clock = lambda: next(clocks)
    runner._run_quant_policy_cycle()
    assert runner._quant_status["state"] == "session_boundary_recheck"
    assert runner._quant_submissions == {}


def test_quote_age_uses_broker_time_after_slow_quote_fetch(runner_type):
    calls = []
    runner, _ = afterhours_runner(runner_type, position(), [], lambda *a, **k: calls.append(k) or dict(status="accepted"))
    times = iter(["2026-09-14T16:01:00-04:00", "2026-09-14T16:01:15-04:00"])
    runner.adapter.get_clock = lambda: dict(success=True, is_open=False, timestamp=next(times), next_close="2026-09-15T16:00:00-04:00")
    runner.adapter.get_liquidation_quote = lambda *args: quote("2026-09-14T16:01:14-04:00")
    runner._run_quant_policy_cycle()
    assert len(calls) == 1
    assert runner._quant_status["exchange_clock"] == "2026-09-14T16:01:15-04:00"
