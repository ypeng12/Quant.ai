# backend/tests/test_simulation_engine.py
"""
Unit test suite for MultiStrategySimulationEngine and date filtering.
Verifies:
1. Arbitrary date range dataset filtering
2. Execution of 5 candidate trading paradigms
3. Generation of Strategy Leaderboard with Net Return, Sharpe, and Drawdown
"""

import pytest
import numpy as np
import pandas as pd
from backend.app.ml.simulation_engine import MultiStrategySimulationEngine

@pytest.fixture
def dummy_simulation_dataset():
    np.random.seed(42)
    n = 60
    dates = pd.date_range("2026-08-01", periods=n, freq="D")
    df = pd.DataFrame({
        "date": dates,
        "Close": 100.0 + np.cumsum(np.random.normal(0.2, 1.2, n)),
        "High": 102.0 + np.cumsum(np.random.normal(0.2, 1.2, n)),
        "Low": 98.0 + np.cumsum(np.random.normal(0.2, 1.2, n)),
        "Volume": np.random.uniform(1000, 5000, n),
        "bid_size": np.random.uniform(100, 1000, n),
        "ask_size": np.random.uniform(100, 1000, n)
    })
    return df

def test_date_range_filtering(dummy_simulation_dataset):
    engine = MultiStrategySimulationEngine()
    filtered = engine.filter_dataset_by_date(dummy_simulation_dataset, "2026-08-05", "2026-08-15")
    
    assert len(filtered) == 11
    assert filtered["date"].min() == pd.to_datetime("2026-08-05")
    assert filtered["date"].max() == pd.to_datetime("2026-08-15")

def test_multi_strategy_benchmark(dummy_simulation_dataset):
    engine = MultiStrategySimulationEngine()
    board = engine.run_multi_strategy_benchmark(dummy_simulation_dataset, "2026-08-01", "2026-08-20")

    assert len(board) == 5
    assert "Strategy" in board.columns
    assert "Net_Return_%" in board.columns
    assert "Sharpe_Ratio" in board.columns
    assert "Max_Drawdown_%" in board.columns
    assert "Win_Rate_%" in board.columns
    assert "Profit_Factor" in board.columns
