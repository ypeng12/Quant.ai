# backend/tests/test_alpha_engine.py
"""
Unit tests for Institutional Alpha Engine (OFI, Micro-Price, OU Stat-Arb, Lead-Lag Alphas).
"""

import unittest
from backend.app.alpha_engine import InstitutionalAlphaEngine


class TestInstitutionalAlphaEngine(unittest.TestCase):
    def setUp(self):
        self.engine = InstitutionalAlphaEngine()

    def test_ofi_alpha_positive(self):
        row = {"Close": 110.0, "High": 110.5, "Low": 108.5, "Open": 108.8, "Volume": 50000, "RVOL": 2.0}
        prev = {"Close": 108.8, "High": 109.0, "Low": 108.0, "Open": 108.2, "Volume": 30000, "RVOL": 1.0}
        ofi = self.engine.compute_ofi_alpha(row, prev)
        self.assertGreater(ofi, 0.0)

    def test_micro_price_alpha_upper_wick_rejection(self):
        # Long upper wick: High=110.89, Close=109.20, Open=108.80 -> Heavy Ask wall
        row = {"Close": 109.20, "High": 110.89, "Low": 108.50, "Open": 108.80, "ATR": 1.5, "bid_size": 50, "ask_size": 300}
        micro = self.engine.compute_micro_price_alpha(row)
        self.assertLess(micro, 0.0)  # Negative Micro Alpha (Short bias)

    def test_ou_stat_arb_overbought_in_range(self):
        # Price 115.0 vs VWAP 109.0 (ATR 1.5) -> Overbought by 4 ATRs in Range ADX=15
        row = {"Close": 115.0, "VWAP": 109.0, "ATR": 1.5}
        ou = self.engine.compute_ou_stat_arb_alpha(row, adx=15.0)
        self.assertLess(ou, -0.4)  # Strong Short Mean Reversion Signal

    def test_lead_lag_alpha_catch_up(self):
        # Sector returned +1.5%, stock momentum 3d is -0.2% -> Catch up Long Alpha
        row = {"momentum_3_pct": -0.20}
        lead_lag = self.engine.compute_lead_lag_alpha(row, sector_return_pct=1.50)
        self.assertGreater(lead_lag, 0.50)

    def test_evaluate_composite_alpha(self):
        row = {"Close": 110.0, "High": 110.5, "Low": 108.5, "Open": 108.8, "Volume": 50000, "VWAP": 109.0, "ATR": 1.5, "RVOL": 2.0}
        prev = {"Close": 108.8, "High": 109.0, "Low": 108.0, "Open": 108.2, "Volume": 30000, "RVOL": 1.0}
        res = self.engine.evaluate_composite_alpha(row, prev_row=prev, sector_return_pct=1.0, adx=18.0)
        self.assertIn("composite_alpha_score", res)
        self.assertIn("alpha_ofi", res)
        self.assertIn("alpha_micro", res)


if __name__ == "__main__":
    unittest.main()
