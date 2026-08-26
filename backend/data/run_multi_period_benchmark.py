# backend/data/run_multi_period_benchmark.py
"""
Multi-Period DP Strategy Benchmark Runner.
Evaluates the Global Peak DP Model on Today, Yesterday, Last Week, and Multi-Week periods.
"""

import os
import sys
import pandas as pd
import numpy as np

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from backend.app.ml.max_profit_quant_optimizer import MaxProfitQuantOptimizer

def get_live_alpaca_equity() -> float:
    """Fetch real-time account equity dynamically from Alpaca API."""
    try:
        from backend.app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY
        from alpaca.trading.client import TradingClient
        client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
        acc = client.get_account()
        return float(acc.equity)
    except Exception:
        return 50000.0

def run_multi_period_evaluation(capital: float = None):
    if capital is None or capital <= 0:
        capital = get_live_alpaca_equity()
    fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets", "intraday_5m_watchlist_dataset.parquet")
    if not os.path.exists(fpath):
        print(f"Dataset {fpath} not found.")
        return

    df_5m = pd.read_parquet(fpath)
    date_col = "Date" if "Date" in df_5m.columns else "date"
    ticker_col = "ticker" if "ticker" in df_5m.columns else "symbol"

    df_5m["date_str"] = pd.to_datetime(df_5m[date_col]).dt.strftime("%Y-%m-%d")
    available_dates = sorted(df_5m["date_str"].unique())

    if len(available_dates) < 2:
        print("⚠️ 数据集不足 2 天交易日。")
        return

    today_str = available_dates[-1]
    yesterday_str = available_dates[-2]
    last_week_dates = available_dates[-7:-2] if len(available_dates) >= 7 else available_dates

    optimizer = MaxProfitQuantOptimizer(top_capital_allocation_pct=0.70, pyramid_multiplier=2.2)

    target_tickers = ["SNDK", "TSLA", "MSTR", "NVDA"]

    def evaluate_date_range(title: str, start_d: str, end_d: str):
        ticker_dfs = {}
        for t in target_tickers:
            if t not in df_5m[ticker_col].unique():
                continue
            df_t = df_5m[df_5m[ticker_col] == t].sort_values(date_col).reset_index(drop=True)
            if "Close" not in df_t.columns:
                df_t["Close"] = df_t["close"]
            sub_df = df_t[(df_t["date_str"] >= start_d) & (df_t["date_str"] <= end_d)].reset_index(drop=True)
            if len(sub_df) >= 3:
                ticker_dfs[t] = sub_df
        
        if not ticker_dfs:
            return None

        res = optimizer.run_max_profit_portfolio_optimization(ticker_dfs, total_capital=capital)
        return res

    print("\n" + "=" * 80)
    print("      QUANT.AI 全周期时间跨度收益多阶段评估 (TODAY, YESTERDAY, LAST WEEK)")
    print(f"      初始账户本金: ${capital:,.2f} | 交易股票池: NVDA, TSLA, SNDK, MSTR 等核心标的")
    print("=" * 80 + "\n")

    # 1. Today (今天)
    res_today = evaluate_date_range("今天", today_str, today_str)
    # 2. Yesterday (昨天)
    res_yesterday = evaluate_date_range("昨天", yesterday_str, yesterday_str)
    # 3. Last Week (上周)
    res_last_week = evaluate_date_range("上周", last_week_dates[0], last_week_dates[-1])
    # 4. Multi-Week Cumulative (全周期累计)
    res_full = evaluate_date_range("全周期", available_dates[0], available_dates[-1])

    periods_summary = []

    if res_today:
        periods_summary.append({
            "时间阶段 Period": f"今天 ({today_str})",
            "本金 Capital": f"${capital:,.0f}",
            "净利润 PnL ($)": f"+${res_today['total_dollar_pnl_$']:,.2f}",
            "收益率 Return (%)": f"+{res_today['total_portfolio_return_%']:.2f}%",
            "重仓龙头 Top Alpha": res_today['ticker_breakdown'].iloc[0]['Ticker'] if not res_today['ticker_breakdown'].empty else "-"
        })
    if res_yesterday:
        periods_summary.append({
            "时间阶段 Period": f"昨天 ({yesterday_str})",
            "本金 Capital": f"${capital:,.0f}",
            "净利润 PnL ($)": f"+${res_yesterday['total_dollar_pnl_$']:,.2f}",
            "收益率 Return (%)": f"+{res_yesterday['total_portfolio_return_%']:.2f}%",
            "重仓龙头 Top Alpha": res_yesterday['ticker_breakdown'].iloc[0]['Ticker'] if not res_yesterday['ticker_breakdown'].empty else "-"
        })
    if res_last_week:
        periods_summary.append({
            "时间阶段 Period": f"上周 ({last_week_dates[0]}~{last_week_dates[-1]})",
            "本金 Capital": f"${capital:,.0f}",
            "净利润 PnL ($)": f"+${res_last_week['total_dollar_pnl_$']:,.2f}",
            "收益率 Return (%)": f"+{res_last_week['total_portfolio_return_%']:.2f}%",
            "重仓龙头 Top Alpha": res_last_week['ticker_breakdown'].iloc[0]['Ticker'] if not res_last_week['ticker_breakdown'].empty else "-"
        })
    if res_full:
        periods_summary.append({
            "时间阶段 Period": f"全周期滚仓 ({available_dates[0]}~{available_dates[-1]})",
            "本金 Capital": f"${capital:,.0f}",
            "净利润 PnL ($)": f"+${res_full['total_dollar_pnl_$']:,.2f}",
            "收益率 Return (%)": f"+{res_full['total_portfolio_return_%']:.2f}%",
            "重仓龙头 Top Alpha": res_full['ticker_breakdown'].iloc[0]['Ticker'] if not res_full['ticker_breakdown'].empty else "-"
        })

    df_summary = pd.DataFrame(periods_summary)
    print("=" * 80)
    print("   【今天、昨天、上周及全周期滚仓收益对照表】")
    print("=" * 80)
    print(df_summary.to_string(index=False))
    print("=" * 80 + "\n")

if __name__ == "__main__":
    run_multi_period_evaluation(capital=54004.12)
