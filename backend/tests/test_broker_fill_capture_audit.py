"""Offline accounting invariants; only synthetic files and stdlib audit code."""
from copy import deepcopy
from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest


_path = Path(__file__).resolve().parents[2] / "scripts" / "audit_broker_fill_capture.py"
_spec = importlib.util.spec_from_file_location("broker_fill_audit_test_target", _path)
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)


def fill(id, side, qty, price, time, order="same-order"):
    return dict(id=id, order_id=order, activity_type="FILL", type="partial_fill", side=side,
                qty=str(qty), price=str(price), transaction_time=time, symbol="TEST")


def test_partial_fills_share_order_but_keep_distinct_activity_and_cross_day_fifo():
    first = fill("a", "sell", 2, 100, "2026-09-01T19:50:00Z")
    rows = [first, fill("b", "sell", 3, 102, "2026-09-01T19:50:01Z"),
            deepcopy(first), fill("c", "buy", 4, 90, "2026-09-02T13:35:00Z")]
    fills, duplicates = audit.normalize_fills(rows)
    assert len(fills) == 3 and duplicates == 1
    result = audit.fifo_scenario(fills)
    assert result["conditional_gross_realized_pnl"] == Decimal(44)
    assert result["net_quantity_change"] == {"TEST": Decimal(-1)}
    assert result["holding"]["overnight_fragments"] == 2
    assert result["daily"]["2026-09-02"]["conditional_fifo_realized_pnl"] == Decimal(44)
    assert result["opening_inventory"].startswith("unknown")


def test_conflicting_duplicate_fill_fails_instead_of_choosing_lucky_price():
    row = fill("a", "buy", 1, 100, "2026-09-01T13:35:00Z")
    changed = {**row, "price": "99"}
    with pytest.raises(ValueError, match="Conflicting"):
        audit.normalize_fills([row, changed])


def test_fixed_base_nav_and_period_fees_do_not_double_count_baseline_or_sum_cumulative_pnl():
    nontrade = [dict(id="before", activity_type="FEE", date="2026-08-31", net_amount="-8"),
                dict(id="during", activity_type="FEE", date="2026-09-01", net_amount="-2")]
    cash = audit.audit_cashflows(nontrade, "2026-08-31", "2026-09-02", unfiltered_complete=True)
    history = dict(timestamp=[1788220800, 1788307200, 1788393600], equity=[100, 110, 105],
                   profit_loss=[10, 20, 15], profit_loss_pct=[.111, .222, .166], base_value=90,
                   base_value_asof="2026-08-28", timeframe="1D")
    nav = audit.audit_nav(history, cash)
    assert cash["fee_amount"] == Decimal(-2)
    assert cash["excluded_baseline_day_or_outside_period"] == 1
    assert nav["baseline_session"] == "2026-08-31"
    assert nav["equity_change"] == Decimal(5)  # Neither 45 (summed P&L) nor 3 (fee twice).
    assert nav["return_without_external_flows"] == Decimal("0.05")
    assert nav["base_to_equity_pnl_reconciles"]


def test_filtered_activity_capture_or_unknown_adjustment_cannot_claim_verified_return():
    cash = audit.audit_cashflows([], "2026-08-31", "2026-09-02")
    assert not cash["external_flow_adjustment_verified"]
    cash = audit.audit_cashflows([dict(id="x", activity_type="UNRECOGNIZED", date="2026-09-01", net_amount=7)],
                                "2026-08-31", "2026-09-02", unfiltered_complete=True)
    assert not cash["external_flow_adjustment_verified"]
    assert cash["unknown_or_nonfinal_activity_types"] == ["UNRECOGNIZED"]


def test_flat_inventory_delta_reconciles_cash_but_does_not_prove_opening_inventory():
    fills, _ = audit.normalize_fills([
        fill("a", "buy", "1.25", "100.10", "2026-09-01T13:35:00Z"),
        fill("b", "sell", ".75", "99.90", "2026-09-01T13:40:00Z"),
        fill("c", "sell", ".5", "101.10", "2026-09-02T13:35:00Z"),
    ])
    result = audit.fifo_scenario(fills)
    assert result["net_quantity_change"] == {"TEST": Decimal(0)}
    assert result["conditional_gross_realized_pnl"] == Decimal(".35")
    assert result["by_symbol"]["TEST"]["trade_cash_change"] == Decimal(".35")
    assert "unknown" in result["opening_inventory"]
    assert result["matches"][0]["prediction_error"] == "unknown_no_linked_decision_receipt"


def test_offsetting_deposit_withdrawal_does_not_turn_equity_ratio_into_investment_return():
    cash = audit.audit_cashflows([
        dict(id="deposit", activity_type="CSD", date="2026-09-01", net_amount=100),
        dict(id="withdrawal", activity_type="CSW", date="2026-09-02", net_amount=-100),
    ], "2026-08-31", "2026-09-02", unfiltered_complete=True)
    history = dict(timestamp=[1788220800, 1788307200, 1788393600], equity=[100, 210, 115],
                   profit_loss=[0, 110, 15], profit_loss_pct=[0, 1.10, .15], base_value=100, timeframe="1D")
    nav = audit.audit_nav(history, cash)
    assert nav["recognized_flow_adjusted_change"] == Decimal(15)
    assert nav["return_without_external_flows"] is None
    assert nav["raw_drawdown_may_include_cashflows"]
