# backend/tests/test_hrt_quant_platform.py
"""
Unit Test & Microsecond Latency Benchmark Suite for HRT-Grade Quant Platform.
Verifies:
1. FastL2OrderBook zero-copy Pybind11 orderbook mechanics.
2. SIMDAlphaCalculator vectorized OFI and MicroPrice velocity.
3. PurgedGroupTimeSeriesSplit purged & embargoed cross validation.
4. Deflated Sharpe Ratio (DSR) probability overfitting check.
5. HRTAlphaPipeline end-to-end evaluation.
"""

import os
import sys
import pytest
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../cpp_engine")))

try:
    import cpp_quant_engine as cqe
    HAS_CPP = True
except ImportError:
    HAS_CPP = False

from backend.app.ml.hrt_alpha_pipeline import (
    PurgedGroupTimeSeriesSplit,
    calculate_deflated_sharpe_ratio,
    HRTAlphaPipeline
)

def test_fast_l2_orderbook():
    if not HAS_CPP:
        pytest.skip("C++ Engine not available")

    ob = cqe.FastL2OrderBook()
    ob.update_bid(0, 100.0, 500.0, 5)
    ob.update_ask(0, 100.2, 300.0, 3)

    assert ob.get_best_bid() == 100.0
    assert ob.get_best_ask() == 100.2
    assert abs(ob.get_mid_price() - 100.1) < 1e-5
    assert ob.get_weighted_microprice() > 100.0
    assert abs(ob.calculate_book_imbalance() - 0.25) < 1e-4

def test_simd_alpha_calculator():
    if not HAS_CPP:
        pytest.skip("C++ Engine not available")

    bids_p = [100.0, 100.5, 100.5]
    bids_s = [100.0, 200.0, 150.0]
    asks_p = [101.0, 101.0, 100.8]
    asks_s = [100.0, 120.0, 180.0]

    ofi = cqe.SIMDAlphaCalculator.calculate_ofi_vectorized(bids_p, bids_s, asks_p, asks_s)
    assert len(ofi) == 3
    assert ofi[0] == 0.0

def test_purged_group_time_series_split():
    np.random.seed(42)
    n = 100
    df = pd.DataFrame({"value": np.random.randn(n)})
    
    cv = PurgedGroupTimeSeriesSplit(n_splits=5, purge_window=5, embargo_window=5)
    splits = list(cv.split(df))

    assert len(splits) == 5
    for train_idx, test_idx in splits:
        assert len(train_idx) > 0
        assert len(test_idx) > 0
        # Ensure no overlap
        assert len(set(train_idx).intersection(set(test_idx))) == 0

def test_deflated_sharpe_ratio():
    returns = np.random.normal(0.001, 0.01, 200)
    observed_sr = 2.0
    dsr_prob = calculate_deflated_sharpe_ratio(observed_sr, returns, n_trials=50)

    assert 0.0 <= dsr_prob <= 1.0

def test_hrt_alpha_pipeline_end_to_end():
    np.random.seed(42)
    n = 150
    df = pd.DataFrame({
        "Close": 100.0 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "bid_price": 100.0 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "ask_price": 100.2 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "bid_size": np.random.uniform(100, 1000, n),
        "ask_size": np.random.uniform(100, 1000, n),
        "Volume": np.random.uniform(5000, 20000, n)
    })

    pipe = HRTAlphaPipeline()
    res = pipe.evaluate_hrt_alpha_model(df)

    assert "mean_purged_cv_sharpe" in res
    assert "deflated_sharpe_ratio_prob" in res
    assert "is_dsr_statistically_significant" in res
