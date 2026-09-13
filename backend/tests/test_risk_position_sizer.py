"""Check that computed quantities respect existing budgets, without broker imports."""

from pathlib import Path
import sys
import unittest


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.broker.risk_position_sizer import RiskPositionSizer


class RiskPositionSizerTests(unittest.TestCase):
    def setUp(self):
        self.sizer = RiskPositionSizer()
        self.params = {
            "buying_power_utilization_pct": 0.95,
            "max_single_position_equity_pct": 0.70,
            "max_trade_risk_pct": 0.035,
            "staged_entry_enabled": True,
            "tier1_size_ratio": 0.40,
            "tier2_size_ratio": 0.60,
            "starter_buying_power_pct": 0.60,
        }
        self.opportunity = {"score": 60.0, "win_probability": 0.60, "_atr": 1.0, "_stop_pct": 0.01}

    def test_one_share_does_not_override_insufficient_buying_power(self):
        account = {"equity": 1000.0, "cash": 950.0, "buying_power": 950.0}
        for method in (self.sizer.size_aggressive_entry, self.sizer.size_probe_entry):
            with self.subTest(method=method.__name__):
                result = method(account, 1000.0, self.opportunity, self.params)
                self.assertEqual(result["shares"], 0)
                self.assertEqual(result["notional"], 0.0)

    def test_explicit_zero_risk_budget_cannot_be_rounded_up(self):
        account = {"equity": 100000.0, "buying_power": 100000.0}
        params = {**self.params, "max_trade_risk_pct": 0.0}
        for tier in (1, 2):
            with self.subTest(tier=tier):
                result = self.sizer.size_aggressive_entry(
                    account, 1000.0, self.opportunity, params, tier=tier
                )
                self.assertEqual(result["shares"], 0)
                self.assertEqual(result["risk_budget"], 0.0)

    def test_fractional_atr_budget_means_zero_whole_shares(self):
        result = self.sizer.size_aggressive_entry(
            {"equity": 10000.0, "buying_power": 10000.0},
            100.0,
            {**self.opportunity, "_atr": 1000.0},
            {**self.params, "max_trade_risk_pct": 0.001},
        )
        self.assertEqual(result["shares"], 0)

    def test_normal_entry_remains_within_notional_and_risk_budgets(self):
        result = self.sizer.size_aggressive_entry(
            {"equity": 100000.0, "buying_power": 100000.0},
            100.0, self.opportunity, self.params,
        )
        self.assertGreater(result["shares"], 0)
        self.assertLessEqual(result["notional"], 70000.0 * 0.40)
        self.assertLessEqual(result["notional"], 100000.0 * 0.95)
        self.assertLessEqual(result["notional"] * result["stop_pct"], 3500.0 * 0.40)
        self.assertLessEqual(result["shares"] * 1.50, 3500.0 * 0.40)


if __name__ == "__main__":
    unittest.main()
