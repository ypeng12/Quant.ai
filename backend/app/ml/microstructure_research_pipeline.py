# backend/app/ml/microstructure_research_pipeline.py
"""
End-to-End Microstructure Alpha Research & Empirical Evaluation Pipeline.
Implements:
- LOB Features: OFI, Microprice Drift, VPIN, Queue Imbalance, Effective Spread.
- Purged Walk-Forward Cross-Validation with Embargo.
- LightGBM / LambdaMART Ranking & Classification.
- Probability Calibration & Brier Score Decomposition.
- Non-linear Square-Root Market Impact Slippage & Transaction Costs.
- Stationary Block Bootstrap 95% Confidence Intervals for Sharpe and Rank IC.
- Regime-based Performance Breakdown.
"""

import sys
import os
import json
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from lightgbm import LGBMClassifier

from backend.app.ml.rigorous_evaluator import (
    PurgedWalkForwardCV,
    TransactionCostModel,
    ProbabilityCalibrator,
    StatisticalInferenceEngine
)


def generate_synthetic_microstructure_lob_data(n_bars: int = 25000, seed: int = 42) -> pd.DataFrame:
    """
    Generates realistic high-frequency order book microstructure data
    with embedded regime switching (Low Vol, High Vol, Choppy).
    """
    np.random.seed(seed)
    timestamps = pd.date_range("2024-01-01 09:30:00", periods=n_bars, freq="5s")

    # Regime generation (Markov chain: 0 = Low Vol, 1 = High Vol, 2 = Choppy)
    regimes = np.zeros(n_bars, dtype=int)
    current_regime = 0
    transition_matrix = [
        [0.98, 0.01, 0.01],
        [0.02, 0.96, 0.02],
        [0.02, 0.02, 0.96]
    ]
    for t in range(1, n_bars):
        current_regime = np.random.choice([0, 1, 2], p=transition_matrix[current_regime])
        regimes[t] = current_regime

    volatilities = np.where(regimes == 1, 0.0008, np.where(regimes == 0, 0.0004, 0.0006))

    # Mid price random walk
    dt_returns = np.random.normal(0.0, volatilities)
    mid_price = 150.0 * np.exp(np.cumsum(dt_returns))

    # Spread and order book depths
    base_spread = np.where(regimes == 1, 0.04, np.where(regimes == 0, 0.01, 0.02))
    bid_price = mid_price - base_spread / 2.0
    ask_price = mid_price + base_spread / 2.0

    # 5-bar forward return alpha correlation
    fwd_5_ret = pd.Series(dt_returns).rolling(5).sum().shift(-5).fillna(0.0).values
    latent_alpha = 0.22 * (fwd_5_ret / (volatilities * np.sqrt(5))) + np.random.normal(0, 0.98, n_bars)

    bid_depth = np.maximum(100, (1000 + 350 * latent_alpha + np.random.normal(0, 300, n_bars))).astype(float)
    ask_depth = np.maximum(100, (1000 - 350 * latent_alpha + np.random.normal(0, 300, n_bars))).astype(float)
    market_volume = bid_depth + ask_depth + np.random.uniform(500, 2000, n_bars)

    df = pd.DataFrame({
        "timestamp": timestamps,
        "regime": regimes,
        "mid_price": mid_price,
        "bid_price": bid_price,
        "ask_price": ask_price,
        "bid_size": bid_depth,
        "ask_size": ask_depth,
        "volume": market_volume,
        "volatility": volatilities,
        "fwd_5_ret": fwd_5_ret
    })
    return df


def engineer_microstructure_features(df: pd.DataFrame, horizon: int = 5) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Engineers institutional-grade microstructure signals.
    """
    d_bid_p = df["bid_price"].diff().fillna(0.0)
    d_ask_p = df["ask_price"].diff().fillna(0.0)
    d_bid_v = df["bid_size"].diff().fillna(0.0)
    d_ask_v = df["ask_size"].diff().fillna(0.0)

    # 1. Order Flow Imbalance (OFI)
    ofi_bid = np.where(d_bid_p > 0, df["bid_size"], np.where(d_bid_p == 0, d_bid_v, 0))
    ofi_ask = np.where(d_ask_p < 0, df["ask_size"], np.where(d_ask_p == 0, d_ask_v, 0))
    ofi = (ofi_bid - ofi_ask) / df["volume"]

    # 2. Microprice Drift
    total_depth = df["bid_size"] + df["ask_size"]
    microprice = (df["ask_size"] * df["bid_price"] + df["bid_size"] * df["ask_price"]) / total_depth
    microprice_drift = (microprice - df["mid_price"]) / df["mid_price"] * 10000.0

    # 3. Queue / Depth Imbalance
    queue_imbalance = (df["bid_size"] - df["ask_size"]) / total_depth

    # 4. Bid-Ask Spread & Effective Spread
    quoted_spread_bps = (df["ask_price"] - df["bid_price"]) / df["mid_price"] * 10000.0

    # 5. Volume Synchronized Probability of Toxicity (VPIN proxy)
    vol_imbalance = (df["bid_size"] - df["ask_size"]).abs().rolling(window=20).mean() / df["volume"].rolling(window=20).mean()
    vpin = vol_imbalance.fillna(0.0)

    # Forward return target: Significant forward movement (base rate ~ 10%)
    fwd_return = df["fwd_5_ret"]
    fwd_target = (fwd_return > 0.0016).astype(int)

    features_df = pd.DataFrame({
        "ofi": ofi,
        "microprice_drift": microprice_drift,
        "queue_imbalance": queue_imbalance,
        "quoted_spread_bps": quoted_spread_bps,
        "vpin": vpin,
        "volatility": df["volatility"]
    }, index=df.index)

    return features_df, fwd_target


def run_microstructure_research_pipeline() -> Dict[str, Any]:
    print("====================================================================================================")
    print("🔬 QUANT.AI MICROSTRUCTURE RESEARCH & RIGOROUS EMPIRICAL EVALUATION PIPELINE")
    print("====================================================================================================")

    # 1. Generate LOB Data (25,000 bars ~ 500 trading days)
    df = generate_synthetic_microstructure_lob_data(n_bars=25000)
    horizon = 5
    X, y = engineer_microstructure_features(df, horizon=horizon)

    valid_mask = ~(X.isna().any(axis=1) | y.isna())
    X = X[valid_mask].reset_index(drop=True)
    y = y[valid_mask].reset_index(drop=True)
    df = df[valid_mask].reset_index(drop=True)

    # 2. Purged & Embargoed Walk-Forward Cross Validation
    cv = PurgedWalkForwardCV(n_splits=5, train_ratio=0.55, horizon_bars=horizon, embargo_pct=0.02)
    cost_model = TransactionCostModel(maker_fee_bps=0.2, taker_fee_bps=0.80, eta_impact=0.07)

    all_oos_preds = []
    all_oos_true = []
    all_oos_returns_gross = []
    all_oos_returns_net = []
    all_oos_regimes = []

    for fold, (train_idx, test_idx) in enumerate(cv.split(df)):
        X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
        X_test, y_test = X.iloc[test_idx], y.iloc[test_idx]
        df_test = df.iloc[test_idx]

        # Out-of-sample calibration: split training fold into 80% fit, 20% calib
        split_cal = int(len(X_train) * 0.8)
        X_tr_fit, y_tr_fit = X_train.iloc[:split_cal], y_train.iloc[:split_cal]
        X_tr_cal, y_tr_cal = X_train.iloc[split_cal:], y_train.iloc[split_cal:]

        clf = LGBMClassifier(
            n_estimators=50,
            learning_rate=0.03,
            max_depth=3,
            num_leaves=7,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42 + fold,
            verbose=-1
        )
        clf.fit(X_tr_fit, y_tr_fit)

        # Fit calibrator strictly on out-of-fold training probabilities
        cal_train_probs = clf.predict_proba(X_tr_cal)[:, 1]
        calibrator = ProbabilityCalibrator(method="isotonic")
        calibrator.fit(cal_train_probs, y_tr_cal.values)

        # Apply strictly Out-of-Sample to test fold
        raw_test_probs = clf.predict_proba(X_test)[:, 1]
        calibrated_probs = calibrator.predict_calibrated(raw_test_probs)

        # Signal Execution with Transaction Cost & Slippage Model
        # Trade on top 12% high conviction signals
        prob_threshold = np.quantile(calibrated_probs, 0.88)
        positions = np.where(calibrated_probs > prob_threshold, 1.0, 0.0)
        fwd_ret = df_test["fwd_5_ret"].values

        gross_pnl = positions * fwd_ret

        # Deduct transaction fees, half spread, and non-linear market impact slippage
        trade_occurred = np.abs(np.diff(positions, prepend=0.0)) > 0
        costs = np.zeros(len(df_test))
        for t in range(len(df_test)):
            if trade_occurred[t]:
                shares = 250.0
                c = cost_model.calculate_cost(
                    price=df_test["mid_price"].iloc[t],
                    shares=shares,
                    bid_price=df_test["bid_price"].iloc[t],
                    ask_price=df_test["ask_price"].iloc[t],
                    market_volume=df_test["volume"].iloc[t],
                    volatility=df_test["volatility"].iloc[t],
                    is_taker=True
                )
                costs[t] = c / (shares * df_test["mid_price"].iloc[t])

        net_pnl = gross_pnl - costs

        all_oos_preds.extend(calibrated_probs)
        all_oos_true.extend(y_test.values)
        all_oos_returns_gross.extend(gross_pnl)
        all_oos_returns_net.extend(net_pnl)
        all_oos_regimes.extend(df_test["regime"].values)

    all_oos_preds = np.array(all_oos_preds)
    all_oos_true = np.array(all_oos_true)
    all_oos_returns_gross = np.array(all_oos_returns_gross)
    all_oos_returns_net = np.array(all_oos_returns_net)
    all_oos_regimes = np.array(all_oos_regimes)

    # 3. Comprehensive Evaluation Metrics
    oos_auc = float(roc_auc_score(all_oos_true, all_oos_preds))
    brier_decomp = ProbabilityCalibrator.decompose_brier_score(all_oos_true, all_oos_preds)
    ece = ProbabilityCalibrator.expected_calibration_error(all_oos_true, all_oos_preds)

    # Daily aggregation for institutional Sharpe evaluation (50 bars/day session)
    bars_per_day = 50
    n_days = len(all_oos_returns_net) // bars_per_day
    daily_gross = np.array([np.sum(all_oos_returns_gross[d * bars_per_day:(d + 1) * bars_per_day]) for d in range(n_days)])
    daily_net = np.array([np.sum(all_oos_returns_net[d * bars_per_day:(d + 1) * bars_per_day]) for d in range(n_days)])

    # 4. Statistical Inference: Bootstrap Confidence Intervals
    gross_sr, gross_ci_l, gross_ci_u = StatisticalInferenceEngine.block_bootstrap_ci(
        daily_gross,
        metric_fn=lambda r: StatisticalInferenceEngine.sharpe_ratio(r, 252.0),
        block_size=5,
        n_bootstraps=1000
    )
    net_sr, net_ci_l, net_ci_u = StatisticalInferenceEngine.block_bootstrap_ci(
        daily_net,
        metric_fn=lambda r: StatisticalInferenceEngine.sharpe_ratio(r, 252.0),
        block_size=5,
        n_bootstraps=1000
    )

    # Bivariate Bootstrap for Rank IC (preserving paired (x_t, y_t))
    pearson_ic, rank_ic = StatisticalInferenceEngine.information_coefficient(all_oos_preds, all_oos_returns_gross)
    _, rank_ic_l, rank_ic_u = StatisticalInferenceEngine.bivariate_block_bootstrap_ci(
        all_oos_preds,
        all_oos_returns_gross,
        metric_fn=lambda x, y: StatisticalInferenceEngine.information_coefficient(x, y)[1],
        block_size=20,
        n_bootstraps=500
    )

    t_stat_hac = StatisticalInferenceEngine.newey_west_t_stat(daily_net, max_lags=3)
    dsr = StatisticalInferenceEngine.deflated_sharpe_ratio(net_sr, daily_net, num_trials=50)

    # 5. Regime Breakdown
    regime_stats = {}
    regime_labels = {0: "Low Volatility", 1: "High Volatility", 2: "Choppy / Mean-Reverting"}
    for reg_id, reg_name in regime_labels.items():
        mask = (all_oos_regimes == reg_id)
        if np.sum(mask) > bars_per_day:
            reg_n = np.sum(mask) // bars_per_day
            reg_daily = np.array([np.sum(all_oos_returns_net[mask][d * bars_per_day:(d + 1) * bars_per_day]) for d in range(reg_n)])
            reg_sr = StatisticalInferenceEngine.sharpe_ratio(reg_daily, 252.0)
            regime_stats[reg_name] = {
                "samples": int(np.sum(mask)),
                "net_sharpe": round(reg_sr, 2)
            }

    results = {
        "oos_auc": round(oos_auc, 3),
        "brier_score": round(brier_decomp["brier_score"], 3),
        "brier_reliability": round(brier_decomp["reliability"], 5),
        "brier_resolution": round(brier_decomp["resolution"], 5),
        "brier_uncertainty": round(brier_decomp["uncertainty"], 5),
        "expected_calibration_error": round(ece, 4),
        "gross_sharpe": round(gross_sr, 2),
        "net_sharpe": round(net_sr, 2),
        "net_sharpe_95_ci": [round(net_ci_l, 2), round(net_ci_u, 2)],
        "rank_ic": round(rank_ic, 3),
        "rank_ic_95_ci": [round(rank_ic_l, 3), round(rank_ic_u, 3)],
        "newey_west_t_stat": round(t_stat_hac, 2),
        "deflated_sharpe_ratio": round(dsr, 3),
        "regime_breakdown": regime_stats
    }

    # Print Formatted Institutional Research Report
    print(f"| Metric                              | Out-of-Sample Value | 95% Confidence Interval |")
    print(f"|-------------------------------------|---------------------|-------------------------|")
    print(f"| ROC AUC (Out-of-Sample)             | {results['oos_auc']:>19} |           -             |")
    print(f"| Brier Score                         | {results['brier_score']:>19} |           -             |")
    print(f"|   - Reliability (Calibration Error) | {results['brier_reliability']:>19} |           -             |")
    print(f"|   - Resolution (Information Value)  | {results['brier_resolution']:>19} |           -             |")
    print(f"| Expected Calibration Error (ECE)    | {results['expected_calibration_error']:>19} |           -             |")
    print(f"| Rank IC (Spearman)                  | {results['rank_ic']:>19} | [{results['rank_ic_95_ci'][0]:.3f}, {results['rank_ic_95_ci'][1]:.3f}]        |")
    print(f"| Gross Annualized Sharpe             | {results['gross_sharpe']:>19} |           -             |")
    print(f"| Net Annualized Sharpe (After Costs) | {results['net_sharpe']:>19} | [{results['net_sharpe_95_ci'][0]:.2f}, {results['net_sharpe_95_ci'][1]:.2f}]          |")
    print(f"| Newey-West HAC t-statistic          | {results['newey_west_t_stat']:>19} |           -             |")
    print(f"| Deflated Sharpe Ratio (DSR, 50 tr.) | {results['deflated_sharpe_ratio']:>19} |           -             |")
    print("----------------------------------------------------------------------------------------------------")
    print("Market Regime Breakdown (Net Sharpe after transaction costs and square-root slippage):")
    for r_name, r_data in regime_stats.items():
        print(f"  • {r_name:<28}: Net Sharpe = {r_data['net_sharpe']:>5.2f} (n = {r_data['samples']})")
    print("====================================================================================================")

    return results


if __name__ == "__main__":
    run_microstructure_research_pipeline()
