# backend/tests/test_unified_pipeline.py
"""
Integration test suite for Unified Quant Strategy Pipeline.
Verifies end-to-end integration between:
1. MarketRegimeHMM
2. QuantMLModelZoo
3. RLTradingAgent
4. Unified Strategy Decision & Stop-Loss Engine
"""

import pytest
import numpy as np
import pandas as pd
from backend.app.ml.unified_strategy_pipeline import UnifiedQuantStrategyPipeline, FEATURE_COLS

@pytest.fixture
def synthetic_pipeline_dataset():
    np.random.seed(42)
    n_samples = 150
    data = {
        "Close": 100.0 + np.cumsum(np.random.normal(0.1, 1.2, n_samples)),
        "High": 102.0 + np.cumsum(np.random.normal(0.1, 1.2, n_samples)),
        "Low": 98.0 + np.cumsum(np.random.normal(0.1, 1.2, n_samples)),
        "Open": 100.0 + np.cumsum(np.random.normal(0.1, 1.2, n_samples)),
        "future_ret_1d_pct": np.random.normal(0.1, 1.5, n_samples),
        "label_win_long": np.random.choice([0, 1], size=n_samples, p=[0.5, 0.5])
    }
    for col in FEATURE_COLS:
        if col == "feature_atr_pct":
            data[col] = np.random.uniform(1.0, 3.5, n_samples)
        else:
            data[col] = np.random.normal(0, 1, n_samples)

    return pd.DataFrame(data)

def test_unified_pipeline_fit_and_predict(synthetic_pipeline_dataset):
    pipeline = UnifiedQuantStrategyPipeline(atr_multiplier=1.5)
    pipeline.fit_all(synthetic_pipeline_dataset)

    sample_feat = synthetic_pipeline_dataset.iloc[[-1]]
    decision = pipeline.predict_trade_decision("SNDK", sample_feat, current_price=1250.0)

    assert "symbol" in decision
    assert decision["symbol"] == "SNDK"
    assert decision["trade_action"] in ["CASH", "LONG_FULL", "LONG_HALF"]
    assert 0.0 <= decision["target_position_pct"] <= 100.0
    assert 0.0 <= decision["signal_confidence_pwin"] <= 100.0
    assert decision["stop_loss_price"] < 1250.0
    assert decision["take_profit_price"] > 1250.0
    assert len(decision["recommendation_reason"]) > 10
