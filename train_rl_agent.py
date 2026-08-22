# train_rl_agent.py
"""
Quant.ai Reinforcement Learning Trading Agent Optimization & Evaluation Pipeline
Trains RL Agent on historical dataset (including choppy & high-volatility regimes)
and evaluates Out-of-Sample Performance against Baseline Momentum and LightGBM models.
"""

import os
import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.data.hf_loader import HuggingFaceETFLoader
from src.data.point_in_time import PointInTimeUniverseFilter
from src.features.momentum import FeaturePipeline
from backend.app.ml.market_regime_hmm import MarketRegimeHMM
from backend.app.ml.rl_trading_agent import TradingEnvironment, RLTradingAgent, ACTIONS
from src.models.rl_agent import RLAgentModel
from src.validation.metrics import calculate_financial_metrics

def train_and_evaluate_rl():
    print("\n" + "=" * 80)
    print("      QUANT.AI REINFORCEMENT LEARNING (RL) TRADING AGENT OPTIMIZATION")
    print("      Goal: Adaptive Regime Switching & Cash Allocation in Choppy Markets")
    print("=" * 80 + "\n")

    # 1. Ingestion & Filtering
    loader = HuggingFaceETFLoader(cache_dir="data/raw")
    try:
        df_raw = loader.load_prices()
    except Exception as e:
        print(f"Warning: Could not load HuggingFace prices ({e}), generating synthetic dataset.")
        df_raw = loader.generate_synthetic_prices(loader.DEFAULT_UNIVERSE, num_days=1000)

    print(f"[1/5] Loaded raw price dataset: {len(df_raw)} rows across {df_raw['symbol'].nunique()} tickers.")

    pit_filter = PointInTimeUniverseFilter(min_price=5.0, min_adv20_usd=10_000_000.0, min_age_days=100)
    aligned_df, _ = pit_filter.filter_universe(df_raw)

    # 2. Features & HMM Market Regime
    feat_pipeline = FeaturePipeline(lookback_windows=[5, 20, 60])
    df_feat_all = feat_pipeline.transform(aligned_df)

    # Filter target symbol (SPY)
    symbol = "SPY" if "SPY" in df_feat_all["symbol"].unique() else df_feat_all["symbol"].iloc[0]
    df_symbol = df_feat_all[df_feat_all["symbol"] == symbol].sort_values("date").reset_index(drop=True).copy()

    # Train Market Regime HMM
    hmm_engine = MarketRegimeHMM()
    hmm_engine.fit(df_symbol)
    
    # Compute forward 1d return (%)
    price_col = "adjusted_close" if "adjusted_close" in df_symbol.columns else "close"
    df_symbol["future_ret_1d_pct"] = df_symbol[price_col].pct_change().shift(-1) * 100.0
    df_dataset = df_symbol.dropna().reset_index(drop=True)

    feature_cols = [
        "cs_z_mom_5d", "cs_z_mom_20d", "cs_z_mom_60d",
        "cs_z_vol_adj_mom_5d", "cs_z_vol_adj_mom_20d"
    ]
    feature_cols = [c for c in feature_cols if c in df_dataset.columns]

    # Split Train / Out-of-Sample Test
    split_idx = int(len(df_dataset) * 0.70)
    train_df = df_dataset.iloc[:split_idx].reset_index(drop=True)
    test_df = df_dataset.iloc[split_idx:].reset_index(drop=True)

    print(f"[2/5] Train dataset: {len(train_df)} bars | Out-of-Sample Test: {len(test_df)} bars.")

    # 3. Train Reinforcement Learning Agent
    print("\n[3/5] Training Reinforcement Learning Agent over 25 market episodes...")
    train_env = TradingEnvironment(
        df=train_df,
        feature_cols=feature_cols,
        fwd_ret_col="future_ret_1d_pct",
        cost_bps=5.0,
        drawdown_penalty_factor=0.8
    )

    rl_agent = RLTradingAgent(
        state_dim=len(feature_cols) + 1,
        learning_rate=0.08,
        discount_factor=0.95,
        epsilon_start=0.9,
        epsilon_decay=0.95
    )

    rewards = rl_agent.train(train_env, episodes=25)
    print(f"  --> Final Episode Cumulative Reward: {rewards[-1]:.4f}")

    # Save trained RL model
    rl_agent.save()

    # 4. Out-of-Sample Strategy Simulation
    print("\n[4/5] Running Out-of-Sample Test Simulation...")
    test_env = TradingEnvironment(
        df=test_df,
        feature_cols=feature_cols,
        fwd_ret_col="future_ret_1d_pct",
        cost_bps=5.0
    )

    state = test_env.reset()
    actions_taken = []
    done = False

    while not done:
        action = rl_agent.select_action(state, evaluate=True)
        actions_taken.append(action)
        next_state, reward, done, info = test_env.step(action)
        state = next_state

    # 5. Evaluate Performance Metrics
    equity_series = pd.Series(test_env.equity_curve)
    net_returns = equity_series.pct_change().dropna()

    # Benchmark: Buy & Hold
    benchmark_returns = (test_df["future_ret_1d_pct"] / 100.0).iloc[:len(net_returns)]
    
    rl_metrics = calculate_financial_metrics(net_returns)
    bm_metrics = calculate_financial_metrics(benchmark_returns)

    action_counts = pd.Series(actions_taken).value_counts().to_dict()
    cash_pct = (action_counts.get(0, 0) / len(actions_taken)) * 100.0
    long_full_pct = (action_counts.get(1, 0) / len(actions_taken)) * 100.0
    long_half_pct = (action_counts.get(2, 0) / len(actions_taken)) * 100.0

    print("\n" + "=" * 80)
    print("      OUT-OF-SAMPLE EVALUATION RESULTS")
    print("=" * 80)
    print(f"  • RL Strategy Net Return:  {rl_metrics.get('total_return', 0.0)*100:.2f}% | Benchmark: {bm_metrics.get('total_return', 0.0)*100:.2f}%")
    print(f"  • RL Strategy Sharpe Ratio: {rl_metrics.get('sharpe_ratio', 0.0):.2f}  | Benchmark: {bm_metrics.get('sharpe_ratio', 0.0):.2f}")
    print(f"  • RL Strategy Max Drawdown: {rl_metrics.get('max_drawdown', 0.0)*100:.2f}% | Benchmark: {bm_metrics.get('max_drawdown', 0.0)*100:.2f}%")
    print(f"  • RL Strategy Win Rate:     {rl_metrics.get('win_rate', 0.0)*100:.2f}% | Benchmark: {bm_metrics.get('win_rate', 0.0)*100:.2f}%")
    print("-" * 80)
    print("  • Adaptive Action Allocation Breakdown:")
    print(f"    - CASH (Out of Market / Avoid Whipsaws): {cash_pct:.1f}% of days")
    print(f"    - LONG_FULL (Bull Trend Exposure):      {long_full_pct:.1f}% of days")
    print(f"    - LONG_HALF (Defensive Hold):            {long_half_pct:.1f}% of days")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    train_and_evaluate_rl()
