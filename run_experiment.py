"""
Quant.ai Experiment Runner & Out-of-Sample Evaluation Pipeline
One-command executable script for reproducible quantitative research experiments.
"""

import os
import sys
import pandas as pd
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.data.hf_loader import HuggingFaceETFLoader
from src.data.point_in_time import PointInTimeUniverseFilter
from src.data.manifest import create_manifest, save_manifest
from src.features.momentum import FeaturePipeline
from src.features.residual_momentum import calculate_residual_momentum
from src.labels.excess_returns import calculate_forward_excess_returns
from src.validation.purged_cv import PurgedWalkForwardCV
from src.validation.metrics import (
    calculate_rank_ic,
    calculate_ic_ir,
    calculate_financial_metrics,
    stationary_bootstrap_ci,
    deflated_sharpe_ratio,
)
from src.models.baselines import RawMomentumBaseline, VolAdjMomentumBaseline, LinearRidgeModel
from src.models.tree_models import LightGBMModel
from src.portfolio.risk_parity import RiskParityPortfolioManager, calculate_turnover
from src.execution.implementation_shortfall import TransactionCostModel
from src.monitoring.drift_monitor import FeatureDriftMonitor


def run_experiment(
    lookback_days: int = 20,
    holding_days: int = 5,
    cost_bps: float = 5.0,
    use_synthetic: bool = False,
):
    print("\n" + "=" * 80)
    print(f"  QUANT.AI OUT-OF-SAMPLE EXPERIMENT RUNNER")
    print(f"  Hypothesis: Volatility-Adjusted Momentum across Liquid U.S. ETFs")
    print(f"  Lookback: {lookback_days}d | Holding: {holding_days}d | Transaction Cost: {cost_bps} bps")
    print("=" * 80 + "\n")

    # 1. Ingestion
    loader = HuggingFaceETFLoader(cache_dir="data/raw")
    if use_synthetic:
        prices_df = loader.generate_synthetic_prices(loader.DEFAULT_UNIVERSE, num_days=1000)
    else:
        prices_df = loader.load_prices()

    print(f"[1/6] Loaded raw price data: {len(prices_df)} rows across {prices_df['symbol'].nunique()} tickers.")

    # 2. Point-in-Time Filtering
    pit_filter = PointInTimeUniverseFilter(min_price=5.0, min_adv20_usd=10_000_000.0, min_age_days=100)
    aligned_df, universe_dict = pit_filter.filter_universe(prices_df)
    print(f"[2/6] Point-in-time universe filtered across {len(universe_dict)} trading dates.")

    # 3. Features & Labels
    feat_pipeline = FeaturePipeline(lookback_windows=[5, 20, 60])
    df_feat = feat_pipeline.transform(aligned_df)
    df_feat = calculate_residual_momentum(df_feat, benchmark_symbol="SPY", window_reg=60, window_mom=20)

    label_col = f"label_excess_ret_{holding_days}d"
    df_dataset = calculate_forward_excess_returns(df_feat, horizons=[holding_days])

    feature_cols = [
        "cs_z_mom_5d", "cs_z_mom_20d", "cs_z_mom_60d",
        "cs_z_vol_adj_mom_5d", "cs_z_vol_adj_mom_20d", "cs_z_vol_adj_mom_60d",
        "cs_z_sortino_mom_20d", "cs_z_volume_z_20d", "cs_z_dist_52w_high",
        "residual_mom_20d"
    ]
    feature_cols = [c for c in feature_cols if c in df_dataset.columns]

    print(f"[3/6] Feature & Label matrix built: {len(df_dataset)} rows, {len(feature_cols)} features.")

    # 4. Purged Walk-Forward CV Setup
    # Train 500d (~2 yrs), Val 100d, Test 100d for dataset compatibility
    n_total_dates = df_dataset["date"].nunique()
    train_d = min(500, int(n_total_dates * 0.5))
    val_d = min(100, int(n_total_dates * 0.15))
    test_d = min(100, int(n_total_dates * 0.15))

    cv = PurgedWalkForwardCV(
        train_days=train_d, val_days=val_d, test_days=test_d, label_horizon=holding_days, embargo_days=5
    )

    portfolio_mgr = RiskParityPortfolioManager(top_quantile=0.20, max_asset_weight=0.20)
    tc_model = TransactionCostModel(cost_bps=cost_bps, slippage_bps=0.0)

    models_suite = {
        "Raw_Momentum_Baseline": RawMomentumBaseline(lookback_col="mom_20d"),
        "Vol_Adj_Momentum_Baseline": VolAdjMomentumBaseline(feature_col="vol_adj_mom_20d"),
        "Ridge_Linear": LinearRidgeModel(alpha=1.0),
        "LightGBM_Tree": LightGBMModel(max_depth=3, learning_rate=0.01, n_estimators=300),
    }

    results = {}
    
    print("\n[4/6] Executing Purged Walk-Forward Cross Validation across Model Hierarchy...")

    for model_name, model_obj in models_suite.items():
        oos_preds = []
        oos_returns = []
        prev_weights = {}

        for fold_idx, (train_df, val_df, test_df) in enumerate(cv.split(df_dataset)):
            # Fit model on training fold
            if hasattr(model_obj, "fit") and callable(getattr(model_obj, "fit")):
                if "Ridge" in model_name or "LightGBM" in model_name:
                    model_obj.fit(train_df, feature_cols, label_col)
                else:
                    model_obj.fit(train_df, label_col)

            # Predict on test fold
            if "Ridge" in model_name or "LightGBM" in model_name:
                test_df = test_df.copy()
                test_df["pred_score"] = model_obj.predict(test_df, feature_cols)
            else:
                test_df = test_df.copy()
                test_df["pred_score"] = model_obj.predict(test_df)

            oos_preds.append(test_df[["date", "symbol", "pred_score", label_col, f"fwd_ret_{holding_days}d", "vol_20d"]])

            # Simulate Out-of-Sample Portfolio Rebalancing
            for d, group in test_df.groupby("date"):
                target_weights = portfolio_mgr.construct_portfolio(group, score_col="pred_score", vol_col="vol_20d")
                turnover = calculate_turnover(prev_weights, target_weights)
                prev_weights = target_weights

                # Weighted gross forward return
                gross_ret = 0.0
                for sym, w in target_weights.items():
                    sub = group[group["symbol"] == sym]
                    if not sub.empty and not np.isnan(sub[f"fwd_ret_{holding_days}d"].values[0]):
                        gross_ret += w * sub[f"fwd_ret_{holding_days}d"].values[0]

                # Deduct transaction costs
                net_ret = tc_model.apply_cost_to_return(gross_ret, turnover)
                oos_returns.append({"date": d, "gross_return": gross_ret, "net_return": net_ret, "turnover": turnover})

        # Concatenate Out-of-Sample predictions and portfolio returns
        df_oos_preds = pd.concat(oos_preds, ignore_index=True)
        df_oos_returns = pd.DataFrame(oos_returns).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)

        # Statistical Metrics: Rank IC
        rank_ic_df = calculate_rank_ic(df_oos_preds, pred_col="pred_score", target_col=label_col)
        ic_stats = calculate_ic_ir(rank_ic_df)

        # Financial Metrics
        fin_stats = calculate_financial_metrics(df_oos_returns.set_index("date")["net_return"])
        
        # Stationary Bootstrap 95% Confidence Interval for Sharpe
        mean_sr, sr_ci_low, sr_ci_high = stationary_bootstrap_ci(df_oos_returns["net_return"], p=0.2, n_bootstrap=500)
        
        # Deflated Sharpe Ratio
        dsr_val = deflated_sharpe_ratio(
            observed_sr=fin_stats.get("sharpe_ratio", 0.0),
            sharpe_var=0.25,
            n_trials=len(models_suite),
            n_obs=len(df_oos_returns)
        )

        results[model_name] = {
            "ic_stats": ic_stats,
            "fin_stats": fin_stats,
            "sharpe_ci": (sr_ci_low, sr_ci_high),
            "dsr": dsr_val,
            "avg_turnover": float(df_oos_returns["turnover"].mean()),
        }

        print(f"  --> {model_name:28s} | OOS Rank IC: {ic_stats['mean_ic']:.4f} | Net Sharpe: {fin_stats.get('sharpe_ratio', 0.0):.2f} (95% CI: [{sr_ci_low:.2f}, {sr_ci_high:.2f}]) | MaxDD: {fin_stats.get('max_drawdown', 0.0)*100:.1f}%")

    print("\n[5/6] Feature Drift Audit (PSI & KS Test)...")
    drift_monitor = FeatureDriftMonitor()
    # Audit drift between first 30% and last 30% of timeline
    dates_sorted = sorted(df_dataset["date"].unique())
    ref_df = df_dataset[df_dataset["date"] <= dates_sorted[int(len(dates_sorted)*0.3)]]
    cur_df = df_dataset[df_dataset["date"] >= dates_sorted[int(len(dates_sorted)*0.7)]]
    drift_report = drift_monitor.audit_drift(ref_df, cur_df, feature_cols)
    
    for f, res in list(drift_report.items())[:3]:
        print(f"  Feature [{f:22s}] PSI: {res['psi']:.4f} ({res['status']})")

    # 6. Save Manifest
    manifest = create_manifest(
        asset_universe=prices_df["symbol"].unique().tolist(),
        lookback_days=lookback_days,
        holding_days=holding_days,
        transaction_cost_bps=cost_bps,
        feature_config={"features": feature_cols},
        model_hyperparams={"models": list(models_suite.keys())},
    )
    manifest.metrics_summary = {k: v["fin_stats"] for k, v in results.items()}
    manifest_path = save_manifest(manifest, f"reports/manifest_{manifest.experiment_id}.json")
    print(f"\n[6/6] Saved reproducible experiment manifest to {manifest_path}")

    print("\n" + "=" * 80)
    print("  EXPERIMENT COMPLETE - RESULTS SUMMARY")
    print("=" * 80)
    print(f"{'Model Name':28s} | {'Rank IC':8s} | {'Net Sharpe':10s} | {'MaxDD':8s} | {'Turnover':8s} | {'DSR':6s}")
    print("-" * 80)
    for m_name, res in results.items():
        ic = res["ic_stats"]["mean_ic"]
        sr = res["fin_stats"].get("sharpe_ratio", 0.0)
        mdd = res["fin_stats"].get("max_drawdown", 0.0) * 100
        to = res["avg_turnover"] * 100
        dsr = res["dsr"]
        print(f"{m_name:28s} | {ic:8.4f} | {sr:10.2f} | {mdd:7.1f}% | {to:7.1f}% | {dsr:6.2f}")
    print("=" * 80 + "\n")

    return results


if __name__ == "__main__":
    # Run experiment with synthetic fallback mode if offline
    try:
        run_experiment(lookback_days=20, holding_days=5, cost_bps=5.0, use_synthetic=False)
    except Exception as e:
        print(f"\n[INFO] Primary remote dataset fetch encountered network restriction: {e}")
        print("[INFO] Falling back to synthetic offline data generator for local verification...")
        run_experiment(lookback_days=20, holding_days=5, cost_bps=5.0, use_synthetic=True)
