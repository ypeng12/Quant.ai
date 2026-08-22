# backend/tests/test_advanced_ml_models.py
"""
Unit test suite for Advanced Machine Learning & Microstructure Alpha Models:
1. LOBMicrostructureMLEngine (OFI, Microprice Drift, Queue Imbalance)
2. TemporalAttentionAlphaModel (Self-Attention over temporal sequences)
"""

import pytest
import numpy as np
import pandas as pd
from backend.app.ml.lob_microstructure_ml import LOBMicrostructureMLEngine
from backend.app.ml.transformer_alpha_model import TemporalAttentionAlphaModel

@pytest.fixture
def dummy_lob_data():
    np.random.seed(42)
    n = 60
    return pd.DataFrame({
        "Close": 100.0 + np.cumsum(np.random.normal(0, 0.5, n)),
        "bid_price": 99.9 + np.cumsum(np.random.normal(0, 0.5, n)),
        "ask_price": 100.1 + np.cumsum(np.random.normal(0, 0.5, n)),
        "bid_size": np.random.uniform(100, 1000, n),
        "ask_size": np.random.uniform(100, 1000, n),
        "Volume": np.random.uniform(1000, 5000, n),
        "label_win_long": np.random.choice([0, 1], size=n)
    })

def test_lob_microstructure_ml_engine(dummy_lob_data):
    engine = LOBMicrostructureMLEngine()
    df_feat = engine.build_microstructure_features(dummy_lob_data)
    
    assert "feature_ofi" in df_feat.columns
    assert "feature_micro_drift" in df_feat.columns
    assert "feature_queue_imbalance" in df_feat.columns

    engine.fit(dummy_lob_data)
    probs = engine.predict_microstructure_alpha(dummy_lob_data)
    assert len(probs) == len(dummy_lob_data)
    assert all(0.0 <= p <= 1.0 for p in probs)

def test_temporal_attention_alpha_model():
    np.random.seed(42)
    n = 30
    df = pd.DataFrame({
        "f1": np.random.normal(0, 1, n),
        "f2": np.random.normal(0, 1, n),
        "f3": np.random.normal(0, 1, n),
        "f4": np.random.normal(0, 1, n)
    })
    
    model = TemporalAttentionAlphaModel(sequence_length=5, feature_dim=4)
    res = model.predict(df, feature_cols=["f1", "f2", "f3", "f4"])
    
    assert "transformer_return_pred" in res
    assert "attention_uncertainty" in res
    assert len(res["transformer_return_pred"]) == n
    assert len(res["attention_uncertainty"]) == n
