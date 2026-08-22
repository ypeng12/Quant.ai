# run_strategy_optimizer.py
"""
Quant.ai Multi-Strategy Grid-Search & Optimization Benchmark CLI
Runs multi-strategy backtests across arbitrary date ranges (e.g. 1 week, 2 weeks, custom start/end dates)
and outputs the ranked Strategy Leaderboard to discover the BEST trading logic.
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.data.hf_loader import HuggingFaceETFLoader
from backend.app.ml.simulation_engine import MultiStrategySimulationEngine

def run_optimization(start_date: str = "2026-08-04", end_date: str = "2026-08-21", symbol: str = "SPY"):
    print("\n" + "=" * 80)
    print("      QUANT.AI MULTI-STRATEGY ALPHA OPTIMIZER & LEADERBOARD")
    print(f"      Date Range: {start_date} ~ {end_date} | Target Symbol: {symbol}")
    print("=" * 80 + "\n")

    # Load dataset
    loader = HuggingFaceETFLoader(cache_dir="data/raw")
    try:
        df_raw = loader.load_prices()
    except Exception as e:
        print(f"Warning: Could not load HuggingFace prices ({e}), generating synthetic dataset.")
        df_raw = loader.generate_synthetic_prices(loader.DEFAULT_UNIVERSE, num_days=1000)

    # Filter target symbol
    sym_use = symbol if symbol in df_raw["symbol"].unique() else df_raw["symbol"].iloc[0]
    df_sym = df_raw[df_raw["symbol"] == sym_use].sort_values("date").reset_index(drop=True).copy()
    
    if "Close" not in df_sym.columns:
        df_sym["Close"] = df_sym["adjusted_close"] if "adjusted_close" in df_sym.columns else df_sym["close"]

    engine = MultiStrategySimulationEngine(cost_bps=5.0)
    leaderboard = engine.run_multi_strategy_benchmark(df_sym, start_date=start_date, end_date=end_date)

    print("\n" + "=" * 80)
    print(f"   【策略优化排行榜 LEADERBOARD ({start_date} ~ {end_date})】")
    print("=" * 80)
    print(leaderboard.to_string(index=False))
    print("=" * 80 + "\n")

    best_strategy = leaderboard.iloc[0]["Strategy"]
    best_sharpe = leaderboard.iloc[0]["Sharpe_Ratio"]
    best_ret = leaderboard.iloc[0]["Net_Return_%"]
    best_dd = leaderboard.iloc[0]["Max_Drawdown_%"]

    print(f"★ 【综合评估最佳炒股逻辑推荐】: [{best_strategy}]")
    print(f"  • 胜出理由：在选定区间内实现 Net Return: {best_ret:+.2f}% | Sharpe: {best_sharpe:.2f} | Max Drawdown: {best_dd:.2f}%")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quant.ai Multi-Strategy Optimization CLI")
    parser.add_argument("--start-date", type=str, default="2026-08-04", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default="2026-08-21", help="End date (YYYY-MM-DD)")
    parser.add_argument("--symbol", type=str, default="SPY", help="Target symbol")
    args = parser.parse_args()

    run_optimization(start_date=args.start_date, end_date=args.end_date, symbol=args.symbol)
