# backend/tests/test_max_profit_optimizer.py
"""
Unit test suite for MaxProfitQuantOptimizer.
Verifies:
1. Cross-sectional Alpha ranking and capital concentration allocation.
2. Dynamic pyramid position scaling on floating profit.
3. Total dollar profit calculation and portfolio optimization.
"""

import pytest
import numpy as np
import pandas as pd
from backend.app.ml.max_profit_quant_optimizer import MaxProfitQuantOptimizer

@pytest.fixture
def dummy_portfolio_dfs():
    np.random.seed(42)
    n = 60
    dts = pd.date_range("2026-08-16", periods=n, freq="5min")
    
    dfs = {}
    for t in ["SNDK", "TSLA", "NVDA"]:
        dfs[t] = pd.DataFrame({
            "date": dts,
            "Close": 100.0 + np.cumsum(np.random.normal(0.1, 0.5, n)),
            "High": 101.0 + np.cumsum(np.random.normal(0.1, 0.5, n)),
            "Low": 99.0 + np.cumsum(np.random.normal(0.1, 0.5, n)),
            "Volume": np.random.uniform(5000, 20000, n),
            "bid_size": np.random.uniform(100, 1000, n),
            "ask_size": np.random.uniform(100, 1000, n)
        })
    return dfs

def test_cross_sectional_ranking(dummy_portfolio_dfs):
    opt = MaxProfitQuantOptimizer()
    ranked = opt.rank_cross_sectional_alpha(dummy_portfolio_dfs)
    
    assert len(ranked) == 3
    assert ranked[0][0] in dummy_portfolio_dfs

def test_pyramid_scaled_trading(dummy_portfolio_dfs):
    opt = MaxProfitQuantOptimizer(pyramid_multiplier=1.5)
    df_sndk = dummy_portfolio_dfs["SNDK"]
    res = opt.simulate_pyramid_scaled_trading(df_sndk, capital=100000.0)

    assert "dollar_pnl" in res
    assert "net_return_%" in res
    assert "pyramid_positions" in res
    assert max(res["pyramid_positions"]) <= 1.5

def test_max_profit_portfolio_optimization(dummy_portfolio_dfs):
    opt = MaxProfitQuantOptimizer()
    res = opt.run_max_profit_portfolio_optimization(dummy_portfolio_dfs, total_capital=300000.0)

    assert "total_capital_$" in res
    assert "total_dollar_pnl_$" in res
    assert "total_portfolio_return_%" in res
    assert len(res["ticker_breakdown"]) == 3
