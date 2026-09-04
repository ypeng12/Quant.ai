# backend/simulation/simulate_mstr.py
"""
Dedicated Ticker Simulation: MSTR (High-Beta Momentum & Trend Runner)
Zero-overlap independent simulation for MSTR.
Focus:
- Crypto/BTC proxy high-volatility momentum.
- Riding BULL_EXPANSION waves with trailing stops.
- Prevents overnight gap decay by closing out by 15:55 EDT.
"""

import sys
import os
import yfinance as yf
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from backend.app.ml.ticker_regime_engine import TickerRegimeEngine, MarketRegime

def run_mstr_simulation(period="5d", interval="5m", initial_capital=100000.0):
    print("=" * 80)
    print("      【MSTR 独立专用量化回测与模拟系统 (DEDICATED SIMULATION: MSTR)】")
    print("      核心特征: 高贝塔强动量、加密叙事共振、波段顺势跟踪、严格日内平仓")
    print(f"      初始本金: ${initial_capital:,.2f} | 周期: {period} (Interval: {interval})")
    print("=" * 80 + "\n")

    df = yf.download("MSTR", period=period, interval=interval, progress=False)
    if df.empty:
        print("Error: Could not retrieve MSTR data.")
        return

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    close_s = df["Close"].squeeze()
    open_s = df["Open"].squeeze()
    high_s = df["High"].squeeze()
    low_s = df["Low"].squeeze()
    vol_s = df["Volume"].squeeze()

    df["VWAP"] = TickerRegimeEngine.calculate_vwap(df)
    df["EMA_9"] = close_s.ewm(span=9, adjust=False).mean()
    df["EMA_21"] = close_s.ewm(span=21, adjust=False).mean()

    capital = initial_capital
    position_shares = 0
    entry_price = 0.0
    entry_time = None
    trades = []
    peak_price = 0.0

    for i in range(20, len(df)):
        sub_df = df.iloc[:i+1]
        regime_info = TickerRegimeEngine.analyze_ticker_regime(sub_df, "MSTR")

        current_time = df.index[i]
        time_str = str(current_time)
        bar_close = float(close_s.iloc[i])
        bar_high = float(high_s.iloc[i])
        bar_vwap = float(df["VWAP"].iloc[i])
        bar_ema9 = float(df["EMA_9"].iloc[i])
        bar_ema21 = float(df["EMA_21"].iloc[i])

        is_eod = "15:50" in time_str or "15:55" in time_str

        # 1. Manage Active Position
        if position_shares > 0:
            peak_price = max(peak_price, bar_high)
            pnl_pct = (bar_close - entry_price) / entry_price * 100.0

            # Dynamic trailing lock
            is_trail_hit = (pnl_pct >= 2.0 and (peak_price - bar_close) / peak_price * 100.0 >= 1.2)
            is_trend_lost = bar_close < bar_ema21 * 0.995 and bar_close < bar_vwap

            if is_trail_hit or is_trend_lost or is_eod:
                exit_price = bar_close
                pnl = position_shares * (exit_price - entry_price)
                capital += position_shares * exit_price
                trades.append({
                    "entry_time": entry_time,
                    "exit_time": current_time,
                    "side": "LONG",
                    "shares": position_shares,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_$": pnl,
                    "return_%": (exit_price - entry_price) / entry_price * 100.0,
                    "reason": "EOD Flatten" if is_eod else ("Trailing Lock" if is_trail_hit else "Trend Life-Line Break")
                })
                position_shares = 0
                entry_price = 0.0

        # 2. Entry Logic
        elif position_shares == 0 and not is_eod:
            if regime_info.regime == MarketRegime.BULL_EXPANSION:
                if bar_close >= bar_vwap and bar_close >= bar_ema9 * 0.998:
                    alloc = capital * 0.85
                    shares = int(alloc / bar_close)
                    if shares > 0:
                        position_shares = shares
                        entry_price = bar_close
                        entry_time = current_time
                        peak_price = bar_close
                        capital -= position_shares * bar_close

    df_trades = pd.DataFrame(trades)
    print("=" * 80)
    print("   【MSTR 独立交易明细 (INDIVIDUAL TRADE LOG)】")
    print("=" * 80)
    if not df_trades.empty:
        for idx, row in df_trades.iterrows():
            win_icon = "🟢 盈利" if row["pnl_$"] > 0 else "🔴 亏损"
            print(f"  Trade #{idx+1} | {row['entry_time']} -> {row['exit_time']} | "
                  f"Entry: ${row['entry_price']:.2f} -> Exit: ${row['exit_price']:.2f} | "
                  f"PnL: ${row['pnl_$']:+,.2f} ({row['return_%']:+.2f}%) | {win_icon} ({row['reason']})")
    else:
        print("  No trades triggered under strict regime criteria.")

    total_pnl = capital - initial_capital
    total_ret_pct = total_pnl / initial_capital * 100.0
    win_rate = (df_trades["pnl_$"] > 0).mean() * 100.0 if not df_trades.empty else 0.0

    print("\n" + "=" * 80)
    print("   【MSTR 独立回测指标总结】")
    print("=" * 80)
    print(f"  • 期末总资产 (Ending Equity):      ${capital:,.2f}")
    print(f"  • 累计总净利润 (Net Total PnL):    ${total_pnl:+,.2f}")
    print(f"  • 总收益率 (Total Net Return):     {total_ret_pct:+.2f}%")
    print(f"  • 胜率 (Win Rate):                 {win_rate:.1f}% ({len(df_trades)} 笔交易)")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    run_mstr_simulation()
