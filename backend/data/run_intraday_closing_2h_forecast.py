# backend/data/run_intraday_closing_2h_forecast.py
"""
Intraday 2-Hour Closing Window Simulation & Loss Recovery Projection.
Simulates trading during the final 2 hours of intraday trading (14:00 EST ~ 16:00 EST)
to evaluate expected net profit, loss recovery (recovering -$2,000 loss + profit buffer),
and optimal position sizing on a $100,000 capital account.
"""

import os
import sys
import pandas as pd
import numpy as np

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from backend.app.ml.max_profit_quant_optimizer import MaxProfitQuantOptimizer

def run_closing_2h_simulation(capital: float = 54004.12, target_loss_recovery: float = 2000.0):
    fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets", "intraday_5m_watchlist_dataset.parquet")
    if not os.path.exists(fpath):
        print(f"Dataset {fpath} not found.")
        return

    df_5m = pd.read_parquet(fpath)
    date_col = "Date" if "Date" in df_5m.columns else "date"
    ticker_col = "ticker" if "ticker" in df_5m.columns else "symbol"

    df_5m["date_str"] = pd.to_datetime(df_5m[date_col]).dt.strftime("%Y-%m-%d")
    latest_date = df_5m["date_str"].max()

    optimizer = MaxProfitQuantOptimizer(top_capital_allocation_pct=0.70, pyramid_multiplier=2.2)

    target_tickers = ["SNDK", "TSLA", "MSTR", "NVDA"]
    ticker_dfs = {}
    for t in target_tickers:
        if t not in df_5m[ticker_col].unique():
            continue
        df_t = df_5m[(df_5m[ticker_col] == t) & (df_5m["date_str"] == latest_date)].sort_values(date_col).reset_index(drop=True)
        if len(df_t) >= 10:
            # Extract last 24 5-minute bars (representing the last 2 hours of trading, 120 mins)
            last_2h_df = df_t.tail(24).reset_index(drop=True)
            if "Close" not in last_2h_df.columns:
                last_2h_df["Close"] = last_2h_df["close"]
            ticker_dfs[t] = last_2h_df

    if not ticker_dfs:
        print("⚠️ 未找到今日盘尾 2 小时有效 K 线。")
        return

    res = optimizer.run_max_profit_portfolio_optimization(ticker_dfs, total_capital=capital)
    pnl = res["total_dollar_pnl_$"]
    ret_pct = res["total_portfolio_return_%"]

    net_after_recovery = pnl - target_loss_recovery

    print("\n" + "=" * 80)
    print(f"      QUANT.AI 今日盘尾最后 2 小时 (Closing 2-Hour Window) 收益与回本预测")
    print(f"      交易日期: {latest_date} | 初始账户本金: ${capital:,.2f}")
    print("=" * 80 + "\n")

    print(res["ticker_breakdown"].to_string(index=False))

    print("\n" + "=" * 80)
    print("   【盘尾 2 小时预测与亏损回本结果】")
    print("=" * 80)
    print(f"  • 投入账户本金 (Account Capital):        ${capital:,.2f}")
    print(f"  • 盘尾2小时预计产出净利润 (Closing PnL):  +${pnl:,.2f}  (+{ret_pct:.2f}%)")
    print(f"  • 填补前期亏损目标 (Loss Recovery Target): -${target_loss_recovery:,.2f}")
    print(f"  • 剔除亏损后净回血利润 (Net Surplus):     +${net_after_recovery:,.2f}")
    print("=" * 80 + "\n")

    if net_after_recovery > 0:
        print(f"✅ 预测成功：盘尾 2 小时通过重仓+滚仓，不仅能 100% 抹平 ${target_loss_recovery:,.2f} 亏损，还能额外净赚 +${net_after_recovery:,.2f}！\n")
    else:
        print(f"⚠️ 回本覆盖率: {(pnl / target_loss_recovery)*100:.1f}%\n")

if __name__ == "__main__":
    run_closing_2h_simulation(capital=54004.12, target_loss_recovery=2000.0)
