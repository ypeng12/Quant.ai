import pytest
import numpy as np
import pandas as pd
from backend.app.ml.rigorous_evaluator import (
    PurgedWalkForwardCV,
    TransactionCostModel,
    ProbabilityCalibrator,
    StatisticalInferenceEngine
)

def test_purged_walk_forward_cv_no_leakage():
    n_samples = 1000
    df = pd.DataFrame({
        "feature": np.random.randn(n_samples),
        "target": np.random.randint(0, 2, n_samples)
    })

    cv = PurgedWalkForwardCV(n_splits=4, train_ratio=0.5, horizon_bars=5, embargo_pct=0.02)
    splits = list(cv.split(df))
    assert len(splits) > 0

    for train_idx, test_idx in splits:
        # 1. No index overlap
        overlap = set(train_idx).intersection(set(test_idx))
        assert len(overlap) == 0

        # 2. Strict horizon purging
        assert np.max(train_idx) <= np.min(test_idx) - 5


def test_transaction_cost_model_market_impact():
    cost_model = TransactionCostModel(maker_fee_bps=1.0, taker_fee_bps=2.0, eta_impact=0.15)
    price = 100.0
    bid = 99.98
    ask = 100.02
    mkt_vol = 1000000.0
    volatility = 0.02

    cost_small = cost_model.calculate_cost(price, 100, bid, ask, mkt_vol, volatility, is_taker=True)
    cost_large = cost_model.calculate_cost(price, 10000, bid, ask, mkt_vol, volatility, is_taker=True)

    # Cost per share should increase due to non-linear square root impact
    cost_per_share_small = cost_small / 100
    cost_per_share_large = cost_large / 10000
    assert cost_per_share_large > cost_per_share_small


def test_probability_calibrator_brier_decomposition():
    np.random.seed(42)
    y_true = np.random.binomial(1, 0.55, 500)
    y_prob = np.clip(y_true * 0.4 + np.random.uniform(0.1, 0.5, 500), 0.01, 0.99)

    calibrator = ProbabilityCalibrator(method="isotonic")
    calibrator.fit(y_prob, y_true)
    y_cal = calibrator.predict_calibrated(y_prob)

    assert len(y_cal) == len(y_prob)
    assert np.all((y_cal >= 0.0) & (y_cal <= 1.0))

    brier = ProbabilityCalibrator.brier_score(y_true, y_cal)
    assert brier >= 0.0

    decomp = ProbabilityCalibrator.decompose_brier_score(y_true, y_cal)
    assert "reliability" in decomp
    assert "resolution" in decomp
    assert "uncertainty" in decomp
    assert decomp["reliability"] >= 0.0


def test_statistical_inference_bootstrap_ci():
    np.random.seed(42)
    # Generate daily returns with Sharpe ~ 1.5
    returns = np.random.normal(0.001, 0.01, 500)

    point_sr, ci_lower, ci_upper = StatisticalInferenceEngine.block_bootstrap_ci(
        returns,
        metric_fn=lambda r: StatisticalInferenceEngine.sharpe_ratio(r, 252.0),
        block_size=10,
        n_bootstraps=300
    )

    assert ci_lower <= point_sr <= ci_upper
    assert ci_upper - ci_lower > 0.0


def test_statistical_inference_bivariate_bootstrap_ci():
    np.random.seed(42)
    x = np.random.normal(0, 1, 500)
    y = 0.4 * x + np.random.normal(0, 0.9, 500)

    point_ic, ci_l, ci_u = StatisticalInferenceEngine.bivariate_block_bootstrap_ci(
        x, y,
        metric_fn=lambda a, b: StatisticalInferenceEngine.information_coefficient(a, b)[1],
        block_size=10,
        n_bootstraps=300
    )

    # Point estimate must be strictly inside empirical confidence interval
    assert ci_l <= point_ic <= ci_u
    assert ci_l > 0.0 # Positively correlated


def test_deflated_sharpe_ratio():
    returns = np.random.normal(0.001, 0.01, 250)
    sr = StatisticalInferenceEngine.sharpe_ratio(returns, 252.0)
    dsr = StatisticalInferenceEngine.deflated_sharpe_ratio(sr, returns, num_trials=20)
    assert 0.0 <= dsr <= 1.0
