# backend/tests/test_auto_reflection_engine.py
"""
Unit test suite for AutoReflectionEngine.
Verifies:
1. Loading daily trade logs
2. Analyzing trade attribution & mistake taxonomy
3. Autonomous parameter self-tuning & RL Q-table retrain
4. Markdown reflection report generation
"""

import os
import pytest
import pandas as pd
from backend.app.ml.auto_reflection_engine import AutoReflectionEngine

@pytest.fixture
def dummy_trade_log():
    return pd.DataFrame([
        {"pnl": 15.5, "action": "buy", "ticker": "SNDK"},
        {"pnl": -2.5, "action": "buy", "ticker": "SNDK"},
        {"pnl": -8.0, "action": "buy", "ticker": "MU"},
        {"pnl": 3.2, "action": "sell", "ticker": "NVDA"},
        {"pnl": -12.0, "action": "buy", "ticker": "TSLA"}
    ])

def test_trade_attribution(dummy_trade_log):
    engine = AutoReflectionEngine()
    attr = engine.analyze_trade_attribution(dummy_trade_log)

    assert attr["total_trades"] == 5
    assert attr["winning_trades"] == 2
    assert attr["losing_trades"] == 3
    assert attr["win_rate_%"] == 40.0
    assert "taxonomy_breakdown" in attr
    assert attr["taxonomy_breakdown"]["Optimal_Profit"] == 1
    assert attr["taxonomy_breakdown"]["False_Breakout_Whipsaw"] == 2

def test_autonomous_param_tuning(dummy_trade_log):
    engine = AutoReflectionEngine()
    attr = engine.analyze_trade_attribution(dummy_trade_log)
    tuning = engine.autonomous_param_self_tuning(attr)

    assert "p_win_threshold" in tuning
    assert "atr_stop_multiplier" in tuning
    assert "rl_q_table_retrained" in tuning
    assert tuning["rl_q_table_retrained"] is True

def test_full_reflection_run():
    engine = AutoReflectionEngine()
    path, attr = engine.run_daily_reflection("2026-08-12")
    assert os.path.exists(path)
