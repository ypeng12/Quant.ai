# run_max_profit_simulation.py
"""
Quant.ai Max-Profit Optimizer Evaluation Script.
Evaluates the Max-Profit Engine (Cross-Sectional Capital Concentration + Dynamic Pyramid Scaling)
on last week's 5-minute K-line dataset (2026-08-16 to 2026-08-21).
Outputs total dollar PnL, portfolio return %, and ticker allocation breakdown.
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from backend.app.ml.max_profit_quant_optimizer import MaxProfitQuantOptimizer

def run_max_profit_benchmark(start_date: str = "2026-08-16", end_date: str = "2026-08-21", total_capital: float = 300000.0):
    print("\n" + "=" * 80)
    print("      QUANT.AI MAX-PROFIT OPTIMIZER & CAPITAL CONCENTRATION EVALUATION")
    print("      Goal: Maximize Total Dollar Profit (Cross-Sectional Heavy Loading + Pyramid Scaling)")
    print(f"      Date Range: {start_date} ~ {end_date} | Total Portfolio Capital: ${total_capital:,.2f}")
    print("=" * 80 + "\n")

    fpath = "backend/data/datasets/intraday_5m_watchlist_dataset.parquet"
    if not os.path.exists(fpath):
        print(f"Dataset {fpath} not found.")
        return

    df_5m = pd.read_parquet(fpath)
    date_col = "Date" if "Date" in df_5m.columns else "date"
    ticker_col = "ticker" if "ticker" in df_5m.columns else "symbol"

    ticker_dfs = {}
    for t in df_5m[ticker_col].unique():
        df_t = df_5m[df_5m[ticker_col] == t].sort_values(date_col).reset_index(drop=True)
        if "Close" not in df_t.columns:
            df_t["Close"] = df_t["close"]
        df_t["date"] = df_t[date_col]
        
        df_t["date_str"] = pd.to_datetime(df_t[date_col]).dt.strftime("%Y-%m-%d")
        week_df = df_t[(df_t["date_str"] >= start_date) & (df_t["date_str"] <= end_date)].reset_index(drop=True)
        if len(week_df) < 5:
            week_df = df_t.tail(150).reset_index(drop=True)
        
        ticker_dfs[t] = week_df

    optimizer = MaxProfitQuantOptimizer(top_capital_allocation_pct=0.60, pyramid_multiplier=1.5)
    res = optimizer.run_max_profit_portfolio_optimization(ticker_dfs, total_capital=total_capital)

    print("=" * 80)
    print("   【跨截面资金重仓与浮盈金字塔加仓明细】")
    print("=" * 80)
    print(res["ticker_breakdown"].to_string(index=False))

    print("\n" + "=" * 80)
    print("   【极限收益最大化结果评估结果】")
    print("=" * 80)
    print(f"  • 投入总本金 (Total Capital):     ${res['total_capital_$']:,.2f}")
    print(f"  • 极限实现总利润 (Total PnL):    ${res['total_dollar_pnl_$']:,.2f}")
    print(f"  • 组合总净收益率 (Portfolio Return): +{res['total_portfolio_return_%']:.2f}%")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Max Profit Quant Optimizer Benchmark")
    parser.add_argument("--start-date", type=str, default="2026-08-16", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default="2026-08-21", help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=300000.0, help="Total portfolio capital ($)")
    args = parser.parse_args()

    run_max_profit_benchmark(start_date=args.start_date, end_date=args.end_date, total_capital=args.capital)
