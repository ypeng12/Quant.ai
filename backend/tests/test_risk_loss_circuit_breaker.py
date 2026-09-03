# backend/tests/test_risk_loss_circuit_breaker.py
import unittest
from app.broker.risk_position_sizer import RiskPositionSizer

class TestRiskLossCircuitBreaker(unittest.TestCase):
    def setUp(self):
        self.sizer = RiskPositionSizer()
        self.account = {
            "equity": 57000.0,
            "cash": 55000.0,
            "buying_power": 150000.0,
            "multiplier": 4.0
        }
        self.params = {
            "max_single_position_equity_pct": 0.20,
            "starter_buying_power_pct": 0.20,
            "buying_power_utilization_pct": 0.80,
            "max_trade_risk_pct": 0.010,
            "pyramid_multiplier": 0.35,
            "max_losses_per_ticker_session": 1,
            "max_dollar_loss_per_ticker": 250.0,
            "loss_reentry_cooldown_seconds": 1800,
        }
        self.opportunity = {
            "score": 80.0,
            "win_probability": 0.65,
            "_stop_pct": 0.010
        }

    def test_high_price_stock_strict_limit(self):
        # Ultra high price stock ($1530 SNDK)
        res = self.sizer.size_aggressive_entry(self.account, 1530.0, self.opportunity, self.params)
        self.assertLessEqual(res["shares"], 8, "High-price stock shares must not exceed 8 shares")
        self.assertLessEqual(res["notional"], 57000.0 * 0.25, "Notional must not exceed 25% of equity")

    def test_pyramid_sizing_never_exceeds_base_or_equity_cap(self):
        # Given initial position of 7 shares of SNDK
        pyr_res = self.sizer.size_pyramid_entry(self.account, 1530.0, self.opportunity, self.params, current_shares=7)
        # Combined shares must not breach max equity cap
        self.assertLessEqual(pyr_res["total_shares"] * 1530.0, 57000.0 * 0.25)
        self.assertLessEqual(pyr_res["shares"], 3, "Pyramid add-on must be strictly smaller than base position")

    def test_moderate_price_stock_sizing(self):
        # TSLA at $375
        res = self.sizer.size_aggressive_entry(self.account, 375.0, self.opportunity, self.params)
        self.assertLessEqual(res["notional"], 57000.0 * 0.20)
        self.assertGreater(res["shares"], 0)

if __name__ == "__main__":
    unittest.main()
