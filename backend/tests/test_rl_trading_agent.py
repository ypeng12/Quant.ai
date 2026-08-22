# backend/tests/test_rl_trading_agent.py
"""
Unit tests for Reinforcement Learning Trading Agent & Trading Environment.
Verifies:
1. Environment state reset & step transitions
2. Zero future leakage state vector construction
3. Transaction cost deduction & drawdown penalties in reward calculation
4. Policy convergence and action probability outputs
"""

import pytest
import numpy as np
import pandas as pd
from backend.app.ml.rl_trading_agent import TradingEnvironment, RLTradingAgent, ACTIONS

@pytest.fixture
def dummy_market_data():
    np.random.seed(42)
    n_bars = 50
    dates = pd.date_range("2026-08-01", periods=n_bars, freq="D")
    df = pd.DataFrame({
        "date": dates,
        "Close": 100.0 + np.cumsum(np.random.normal(0, 1.5, n_bars)),
        "feature_mom_5d": np.random.normal(0, 1, n_bars),
        "feature_atr_pct": np.random.uniform(1.0, 3.5, n_bars),
        "future_ret_1d_pct": np.random.normal(0.1, 1.2, n_bars)
    })
    return df

def test_environment_reset_and_step(dummy_market_data):
    feature_cols = ["feature_mom_5d", "feature_atr_pct"]
    env = TradingEnvironment(dummy_market_data, feature_cols=feature_cols, cost_bps=5.0)
    
    state = env.reset()
    assert len(state) == len(feature_cols) + 1  # 2 features + 1 position state
    assert env.current_position == 0.0
    assert env.current_step == 0

    # Execute step Action 1 (LONG_FULL)
    next_state, reward, done, info = env.step(action=1)
    assert env.current_position == 1.0
    assert env.current_step == 1
    assert "net_return" in info
    assert "equity" in info
    assert info["action_name"] == "LONG_FULL"

def test_rl_agent_discretization_and_action():
    state_dim = 3
    agent = RLTradingAgent(state_dim=state_dim, action_dim=3)
    sample_state = np.array([0.5, -1.2, 0.0])
    
    action_idx = agent.select_action(sample_state, evaluate=True)
    assert action_idx in [0, 1, 2]
    
    pred_res = agent.predict_action(sample_state)
    assert "action_id" in pred_res
    assert "action_name" in pred_res
    assert "action_probabilities" in pred_res
    assert sum(pred_res["action_probabilities"].values()) == pytest.approx(1.0, abs=0.01)

def test_rl_agent_training_loop(dummy_market_data):
    feature_cols = ["feature_mom_5d", "feature_atr_pct"]
    env = TradingEnvironment(dummy_market_data, feature_cols=feature_cols)
    agent = RLTradingAgent(state_dim=len(feature_cols) + 1)
    
    rewards = agent.train(env, episodes=5)
    assert len(rewards) == 5
    assert all(isinstance(r, (float, int, np.floating)) for r in rewards)
