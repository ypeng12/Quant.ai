import copy
import pytest

from scripts.audit_trade_ledger import audit_fills


def fill(action, qty, price, minute, order_id=None):
    return {"ticker": "TEST", "action": action, "shares": qty, "price": price,
            "time": f"2026-09-11 10:{minute:02d}:00", "order_id": order_id, "pnl": 0}


def test_short_cover_is_profitable_and_preserves_source():
    rows = [fill("SHORT", 10, 100, 0), fill("COVER", 10, 90, 5)]
    original = copy.deepcopy(rows)
    summary, matched = audit_fills(rows)
    assert summary["fifo_realized_before_fees"] == 100
    assert summary["net_flat_cashflow_before_fees"] == 100
    assert matched[0]["direction"] == "short"
    assert rows == original


def test_partial_close_add_and_flip_conserve_cashflow():
    rows = [fill("BUY", 10, 100, 0), fill("TIER2_ADD_BUY", 5, 110, 1),
            fill("SELL", 20, 120, 2), fill("PYRAMID_SHORT", 5, 115, 3),
            fill("PARTIAL_COVER", 3, 100, 4), fill("COVER", 7, 90, 5)]
    summary, _ = audit_fills(rows)
    assert summary["net_quantity_change"] == 0
    assert summary["fifo_realized_before_fees"] == 495
    assert summary["cashflow"] == 495


def test_open_inventory_cannot_be_reported_as_full_pnl():
    summary, _ = audit_fills([fill("BUY", 10, 100, 0)])
    assert summary["cashflow"] == -1000
    assert summary["net_flat_cashflow_before_fees"] is None


def test_duplicate_snapshot_not_double_counted_and_conflict_rejected():
    entry = fill("SHORT", 10, 100, 0, "order-1")
    summary, _ = audit_fills([entry, copy.deepcopy(entry)])
    assert summary["fills"] == 1
    assert summary["duplicates_ignored"] == 1
    with pytest.raises(ValueError, match="Conflicting"):
        audit_fills([entry, {**entry, "shares": 11}])
