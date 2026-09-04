# backend/simulation/simulate_nvda.py
"""
Dedicated Ticker Simulation: NVDA (Pop & Fade / Mean-Reversion Specialist)
Zero-overlap independent simulation for NVDA.
Focus:
- Specifically addresses the "先涨后跌" (Morning Pop then Afternoon Bleed) phenomenon.
- Morning Momentum Scalp (09:30 - 10:15): Quick profit taking near morning resistance.
- Distribution Transition: When peak gains are rejected and price drops below VWAP, long entries are banned.
- Fade / Shorting the post-pop decay back to daily mean.
"""

import sys
import os
import yfinance as yf
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from backend.app.ml.ticker_regime_engine import TickerRegimeEngine, MarketRegime

def run_nvda_simulation(period="5d", interval="5m", initial_capital=100000.0):
    print("=" * 80)
    print("      【NVDA 独立专用量化回测与模拟系统 (DEDICATED SIMULATION: NVDA)】")
    print("      核心特征: 机构高流动性洗盘、'先涨后跌' 冲高回落、严禁高位死拿、破位止盈反手")
    print(f"      初始本金: ${initial_capital:,.2f} | 周期: {period} (Interval: {interval})")
    print("=" * 80 + "\n")

    df = yf.download("NVDA", period=period, interval=interval, progress=False)
    if df.empty:
        print("Error: Could not retrieve NVDA data.")
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
    position_side = None # "LONG" or "SHORT"
    entry_price = 0.0
    entry_time = None
    trades = []
    extreme_price = 0.0

    for i in range(20, len(df)):
        sub_df = df.iloc[:i+1]
        regime_info = TickerRegimeEngine.analyze_ticker_regime(sub_df, "NVDA")

        current_time = df.index[i]
        time_str = str(current_time)
        bar_close = float(close_s.iloc[i])
        bar_high = float(high_s.iloc[i])
        bar_low = float(low_s.iloc[i])
        bar_vwap = float(df["VWAP"].iloc[i])
        bar_ema9 = float(df["EMA_9"].iloc[i])
        bar_ema21 = float(df["EMA_21"].iloc[i])

        is_morning = any(t in time_str for t in ["09:35", "09:40", "09:45", "09:50", "09:55", "10:00", "10:05", "10:10"])
        is_eod = "15:50" in time_str or "15:55" in time_str

        # 1. Manage Active Position
        if position_shares > 0:
            if position_side == "LONG":
                extreme_price = max(extreme_price, bar_high)
                profit_pct = (bar_close - entry_price) / entry_price * 100.0

                # NVDA Long Rule: Never hold into afternoon decay.
                # If profit > 1.0% or price crosses below VWAP or 10:30 arrives -> EXIT
                is_take_profit = profit_pct >= 1.2
                is_vwap_lost = bar_close < bar_vwap
                is_morning_ended = "10:30" in time_str or "10:45" in time_str

                if is_take_profit or is_vwap_lost or is_morning_ended or is_eod:
                    exit_price = bar_close
                    pnl = position_shares * (exit_price - entry_price)
                    capital += pnl
                    trades.append({
                        "entry_time": entry_time,
                        "exit_time": current_time,
                        "side": "LONG",
                        "shares": position_shares,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "pnl_$": pnl,
                        "return_%": (exit_price - entry_price) / entry_price * 100.0,
                        "reason": "Quick Pop TP" if is_take_profit else ("VWAP Exit Before Fade" if is_vwap_lost else "Morning Window Close")
                    })
                    position_shares = 0
                    position_side = None

            elif position_side == "SHORT":
                extreme_price = min(extreme_price, bar_low)
                profit_pct = (entry_price - bar_close) / entry_price * 100.0

                # Short Fade logic: Cover when VWAP is reclaimed or EOD
                if bar_close > bar_vwap * 1.003 or is_eod or profit_pct >= 1.5:
                    exit_price = bar_close
                    pnl = position_shares * (entry_price - exit_price)
                    capital += pnl
                    trades.append({
                        "entry_time": entry_time,
                        "exit_time": current_time,
                        "side": "SHORT",
                        "shares": position_shares,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "pnl_$": pnl,
                        "return_%": (entry_price - exit_price) / entry_price * 100.0,
                        "reason": "EOD Flatten" if is_eod else "Short Fade Target"
                    })
                    position_shares = 0
                    position_side = None

        # 2. Entry Logic
        elif position_shares == 0 and not is_eod:
            # Case A: Morning Open Spike (09:35 - 10:00) with price above VWAP -> Quick Long Scalp
            if is_morning and bar_close > bar_vwap and bar_close > bar_ema9:
                alloc = capital * 0.70
                shares = int(alloc / bar_close)
                if shares > 0:
                    position_shares = shares
                    position_side = "LONG"
                    entry_price = bar_close
                    entry_time = current_time
                    extreme_price = bar_close

            # Case B: POP_AND_FADE detected (Failed peak, under VWAP) -> Fade Short
            elif regime_info.regime == MarketRegime.POP_AND_FADE and bar_close < bar_vwap:
                alloc = capital * 0.70
                shares = int(alloc / bar_close)
                if shares > 0:
                    position_shares = shares
                    position_side = "SHORT"
                    entry_price = bar_close
                    entry_time = current_time
                    extreme_price = bar_close

    df_trades = pd.DataFrame(trades)
    print("=" * 80)
    print("   【NVDA 独立交易明细 (INDIVIDUAL TRADE LOG)】")
    print("=" * 80)
    if not df_trades.empty:
        for idx, row in df_trades.iterrows():
            win_icon = "🟢 盈利" if row["pnl_$"] > 0 else "🔴 亏损"
            print(f"  Trade #{idx+1} | {row['entry_time']} -> {row['exit_time']} | "
                  f"{row['side']:5s} @ ${row['entry_price']:.2f} -> ${row['exit_price']:.2f} | "
                  f"PnL: ${row['pnl_$']:+,.2f} ({row['return_%']:+.2f}%) | {win_icon} ({row['reason']})")
    else:
        print("  No trades executed.")

    total_pnl = capital - initial_capital
    total_ret_pct = total_pnl / initial_capital * 100.0
    win_rate = (df_trades["pnl_$"] > 0).mean() * 100.0 if not df_trades.empty else 0.0

    print("\n" + "=" * 80)
    print("   【NVDA 独立回测指标总结】")
    print("=" * 80)
    print(f"  • 期末总资产 (Ending Equity):      ${capital:,.2f}")
    print(f"  • 累计总净利润 (Net Total PnL):    ${total_pnl:+,.2f}")
    print(f"  • 总收益率 (Total Net Return):     {total_ret_pct:+.2f}%")
    print(f"  • 胜率 (Win Rate):                 {win_rate:.1f}% ({len(df_trades)} 笔交易)")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    run_nvda_simulation()
