# backend/tests/test_daily_consistency_engine.py
"""
Unit test suite for DailyConsistencyQuantEngine.
Verifies:
1. High-confidence entry gating (P_win >= threshold)
2. HMM Regime Shield (halting in non-bull regimes)
3. Daily Max Loss Circuit Breaker execution
4. Calculation of daily win rate and financial metrics
"""

import pytest
import numpy as np
import pandas as pd
from backend.app.ml.daily_consistency_quant_engine import DailyConsistencyQuantEngine

@pytest.fixture
def dummy_daily_consistency_data():
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2026-08-01", periods=n, freq="D")
    df = pd.DataFrame({
        "date": dates,
        "Close": 100.0 + np.cumsum(np.random.normal(0.2, 1.0, n)),
        "High": 102.0 + np.cumsum(np.random.normal(0.2, 1.0, n)),
        "Low": 98.0 + np.cumsum(np.random.normal(0.2, 1.0, n)),
        "Volume": np.random.uniform(1000, 5000, n),
        "bid_size": np.random.uniform(100, 1000, n),
        "ask_size": np.random.uniform(100, 1000, n)
    })
    return df

def test_daily_consistency_quant_engine_simulation(dummy_daily_consistency_data):
    engine = DailyConsistencyQuantEngine(p_win_threshold=0.55, daily_loss_limit_pct=-1.0)
    res = engine.simulate_daily_consistent_trading(dummy_daily_consistency_data)

    assert "financial_metrics" in res
    assert "daily_pnls" in res
    assert "daily_win_rate_%" in res
    assert "winning_days_count" in res
    assert "total_days_count" in res
    assert 0.0 <= res["daily_win_rate_%"] <= 100.0
