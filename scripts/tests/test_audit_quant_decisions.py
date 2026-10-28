"""Evidence-level safeguards for the offline decision audit."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("audit_quant_decisions", Path(__file__).resolve().parents[1] / "audit_quant_decisions.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fill(identifier, action, quantity, price, minute=0):
    return {"order_id": identifier, "ticker": "TEST", "time": f"2026-09-01 10:{minute:02d}:00", "action": action,
            "shares": quantity, "price": price, "order_status": "filled", "reason": "Alpaca Broker Confirmed Fill"}


class DecisionEvidenceAuditTests(unittest.TestCase):
    def test_duplicate_archive_does_not_multiply_executions(self):
        rows = [fill("one", "BUY", 2, 100), fill("two", "SELL", 2, 101, 1)]
        audit = MODULE.build_audit([("ledger", rows), ("archive", rows)], "2026-09-01", "2026-09-30")
        self.assertEqual(audit["coverage"]["unique_operations_in_window"], 2)
        self.assertEqual(audit["deduplication"]["duplicates_removed"], 2)
        self.assertEqual(audit["conditional_gross_price_pnl_in_window"], 2)

    def test_conflicting_cumulative_order_snapshots_are_not_added(self):
        rows = [fill("one", "BUY", 2, 100), fill("one", "BUY", 3, 100)]
        accepted, diagnostic = MODULE.deduplicate([("source", rows)])
        self.assertEqual(accepted, [])
        self.assertEqual(len(diagnostic["conflicting_operations"]), 1)

    def test_reversal_matches_only_existing_inventory_then_opens_short(self):
        rows = [fill("one", "BUY", 2, 100), fill("two", "SELL", 3, 101, 1), fill("three", "BUY", 1, 99, 2)]
        audit = MODULE.build_audit([("source", rows)], "2026-09-01", "2026-09-30")
        self.assertEqual(audit["conditional_gross_price_pnl_in_window"], 4)
        self.assertEqual(audit["conditional_fifo_net_quantity_changes"], {"TEST": 0})
        self.assertFalse(audit["actual_account_return_verified"])

    def test_loss_does_not_become_proven_prediction_error(self):
        rows = [fill("one", "BUY", 1, 100), fill("two", "SELL", 1, 99, 10)]
        audit = MODULE.build_audit([("source", rows)], "2026-09-01", "2026-09-30")
        self.assertEqual(audit["conditional_outcomes"], {"adverse_realized_price_move": 1})
        self.assertFalse(audit["conditional_matches"][0]["prediction_error_proven"])
        self.assertIn("unverifiable", audit["operations"][1]["classifications"]["prediction_error"])

    def test_profitable_price_move_can_be_erased_only_under_cost_assumption(self):
        rows = [fill("one", "BUY", 1, 100), fill("two", "SELL", 1, 100.05, 10)]
        audit = MODULE.build_audit([("source", rows)], "2026-09-01", "2026-09-30")
        self.assertEqual(audit["cost_sensitivity"][0]["gross_winners_erased_by_assumed_cost"], 0)
        self.assertEqual(audit["cost_sensitivity"][1]["gross_winners_erased_by_assumed_cost"], 1)
        self.assertFalse(audit["fees_verified"])

    def test_prior_period_inventory_is_carried_into_requested_window(self):
        entry = fill("one", "BUY", 2, 100)
        entry["time"] = "2026-08-31 15:00:00"
        audit = MODULE.build_audit([("source", [entry, fill("two", "SELL", 2, 101, 1)])], "2026-09-01", "2026-09-30")
        self.assertEqual(audit["coverage"]["unique_operations_in_window"], 1)
        self.assertEqual(audit["conditional_gross_price_pnl_in_window"], 2)
        self.assertFalse(audit["opening_inventory_verified"])

    def test_negative_logged_expectation_is_not_a_calibrated_probability_or_fill(self):
        logs = ["[2026-09-11 10:49:17] [MSTR] BUY × 145 shs @ $134.94 | P_win=38.7% | E[PnL]=-0.09R | Submitting Order"]
        result = MODULE.audit_action_logs(logs)
        self.assertEqual(result["entries_with_negative_logged_expectation"], 1)
        self.assertFalse(result["entries"][0]["forecast_calibration_verified"])
        self.assertFalse(result["entries"][0]["link_to_actual_fill_verified"])

    def test_simultaneous_opposite_orders_flag_unknown_execution_order(self):
        audit = MODULE.build_audit([("source", [fill("one", "BUY", 1, 100), fill("two", "SELL", 1, 101)])], "2026-09-01", "2026-09-30")
        self.assertEqual(audit["deduplication"]["same_timestamp_opposite_side_groups"], 1)


if __name__ == "__main__":
    unittest.main()
