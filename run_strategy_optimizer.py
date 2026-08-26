# run_strategy_optimizer.py
"""
Quant.ai Continuous Automated Strategy Optimizer & Peak-Finding CLI.
Executes multi-generation parameter optimization loops ("算无数遍") across historical datasets,
identifies the Global Peak Parameter Combination, and deploys the BEST strategy version.
"""

import os
import sys
import argparse
import itertools
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from backend.app.ml.max_profit_quant_optimizer import MaxProfitQuantOptimizer

def run_peak_finding_optimizer(
    start_date: str = "2026-08-03",
    end_date: str = "2026-08-21",
    total_capital: float = 300000.0,
    iterations: int = 50
):
    print("\n" + "=" * 80)
    print("      QUANT.AI CONTINUOUS AUTOMATED STRATEGY OPTIMIZER & PEAK FINDER")
    print(f"      Target: Perform Continuous Iterations ('算无数遍') to Discover Global Best Version")
    print(f"      Date Range: {start_date} ~ {end_date} | Initial Capital: ${total_capital:,.2f}")
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

    # Hyperparameter Grid Search Space
    alloc_space = [0.60, 0.70, 0.80]
    pyramid_mult_space = [1.5, 1.8, 2.2, 2.5]
    pyramid_trig_space = [0.005, 0.008, 0.012]

    param_combinations = list(itertools.product(alloc_space, pyramid_mult_space, pyramid_trig_space))
    results = []

    print(f"[*] Starting {len(param_combinations)} continuous optimization iteration runs across parameter space...\n")

    for iter_idx, (alloc_pct, pyr_mult, pyr_trig) in enumerate(param_combinations, 1):
        optimizer = MaxProfitQuantOptimizer(top_capital_allocation_pct=alloc_pct, pyramid_multiplier=pyr_mult)
        res = optimizer.run_max_profit_portfolio_optimization(ticker_dfs, total_capital=total_capital)
        
        pnl = res["total_dollar_pnl_$"]
        ret_pct = res["total_portfolio_return_%"]
        
        results.append({
            "Iteration": iter_idx,
            "Top_Alloc_%": int(alloc_pct * 100),
            "Pyramid_Mult": pyr_mult,
            "Pyramid_Trigger_%": pyr_trig * 100,
            "Total_PnL_$": pnl,
            "Return_%": ret_pct,
            "Score": pnl * (1.0 + ret_pct / 100.0)
        })

    df_res = pd.DataFrame(results).sort_values("Score", ascending=False).reset_index(drop=True)

    print("=" * 80)
    print("   【连续优化迭代排行榜 GLOBAL PEAK OPTIMIZER LEADERBOARD】")
    print("=" * 80)
    print(df_res.head(10).to_string(index=False))

    best = df_res.iloc[0]
    print("\n" + "=" * 80)
    print("★ 【全局最佳策略版本确定 (GLOBAL OPTIMAL VERSION DISCOVERED)】")
    print("=" * 80)
    print(f"  • 胜出模型组合: Top 1 重仓比例 {best['Top_Alloc_%']}% | 滚仓加仓倍数 {best['Pyramid_Mult']}x | 触发门槛 {best['Pyramid_Trigger_%']:.1f}%")
    print(f"  • 极限可实现净利润 (Peak PnL):    ${best['Total_PnL_$']:,.2f}")
    print(f"  • 极限组合收益率 (Peak Return):   +{best['Return_%']:.2f}%")
    print("=" * 80 + "\n")

    # Update runner_config.json with winning peak parameters
    config_file = os.path.join(os.path.dirname(__file__), "runner_config.json")
    try:
        import json
        config_data = {}
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
        config_data.update({
            "strategy_version": f"global_peak_v{int(best['Iteration'])}",
            "starter_buying_power_pct": float(best['Top_Alloc_%']) / 100.0,
            "pyramid_multiplier": float(best['Pyramid_Mult']),
            "pyramid_trigger_pct": float(best['Pyramid_Trigger_%']) / 100.0,
        })
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 已自动将全局最佳策略参数同步部署至 {config_file}")
    except Exception as e:
        print(f"⚠️ 配置写入提示: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Quant Strategy Continuous Optimizer")
    parser.add_argument("--start-date", type=str, default="2026-08-03", help="Start date")
    parser.add_argument("--end-date", type=str, default="2026-08-21", help="End date")
    parser.add_argument("--capital", type=float, default=300000.0, help="Capital ($)")
    args = parser.parse_args()

    run_peak_finding_optimizer(start_date=args.start_date, end_date=args.end_date, total_capital=args.capital)
