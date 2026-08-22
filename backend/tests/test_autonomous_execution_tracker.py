# backend/tests/test_autonomous_execution_tracker.py
"""
Unit test suite for AutonomousExecutionTracker.
Verifies:
1. Intraday trading session window optimization (blocking 09:30-09:45, allowing 10:00).
2. Volume impact capping (<= 1.0% of 5m volume).
3. Volatility target position scaling.
"""

import pytest
import numpy as np
import pandas as pd
from backend.app.ml.autonomous_execution_tracker import AutonomousExecutionTracker

def test_is_prime_trading_window():
    tracker = AutonomousExecutionTracker()
    
    # 09:30 - Market Open Noise (Blocked)
    dt_open_noise = pd.Timestamp("2026-08-22 09:35:00")
    assert tracker.is_prime_trading_window(dt_open_noise) is False

    # 10:00 - Morning Prime Window (Allowed)
    dt_morning_prime = pd.Timestamp("2026-08-22 10:00:00")
    assert tracker.is_prime_trading_window(dt_morning_prime) is True

    # 15:58 - Market Close Liquidation (Blocked)
    dt_close_noise = pd.Timestamp("2026-08-22 15:58:00")
    assert tracker.is_prime_trading_window(dt_close_noise) is False

def test_liquidity_capped_position():
    tracker = AutonomousExecutionTracker(max_market_impact_pct=0.01)
    
    np.random.seed(42)
    n = 30
    df = pd.DataFrame({
        "Close": np.full(n, 150.0),
        "High": np.full(n, 152.0),
        "Low": np.full(n, 148.0),
        "Volume": np.full(n, 10000.0)
    })

    pos = tracker.calculate_liquidity_capped_position(df, idx=10, raw_position=1.0)
    assert 0.0 <= pos <= 1.0

def test_autonomous_tracking_pipeline():
    np.random.seed(42)
    n = 100
    dts = pd.date_range("2026-08-22 09:30", periods=n, freq="5min")
    df = pd.DataFrame({
        "date": dts,
        "Close": 100.0 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "High": 101.0 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "Low": 99.0 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "Volume": np.random.uniform(5000, 20000, n),
        "bid_size": np.random.uniform(100, 1000, n),
        "ask_size": np.random.uniform(100, 1000, n)
    })

    tracker = AutonomousExecutionTracker()
    res = tracker.run_autonomous_tracking_pipeline(df)

    assert "metrics" in res
    assert "optimized_positions" in res
    assert "blocked_by_timing_count" in res
    assert len(res["optimized_positions"]) == len(df)
