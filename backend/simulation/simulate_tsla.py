# backend/simulation/simulate_tsla.py
"""
Dedicated Ticker Simulation: TSLA (High Volatility, Bear Expansion & Rejection Fader)
Zero-overlap independent simulation for TSLA.
Focus:
- Strict Long Prohibition when TSLA is in BEAR_EXPANSION or below VWAP.
- Avoids fighting the daily trend.
- Explores Shorting / Pullback Fading into EMA21/VWAP resistance.
- Closes intraday before 15:55 EDT to prevent overnight gap risk.
"""

import sys
import os
import yfinance as yf
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from backend.app.ml.ticker_regime_engine import TickerRegimeEngine, MarketRegime

def run_tsla_simulation(period="5d", interval="5m", initial_capital=100000.0, allow_short=True):
    print("=" * 80)
    print("      【TSLA 独立专用量化回测与模拟系统 (DEDICATED SIMULATION: TSLA)】")
    print("      核心特征: 高贝塔、流动性清扫、破位严禁抄底、顺势做空/空仓避险")
    print(f"      初始本金: ${initial_capital:,.2f} | 允许做空: {allow_short} | 周期: {period} ({interval})")
    print("=" * 80 + "\n")

    df = yf.download("TSLA", period=period, interval=interval, progress=False)
    if df.empty:
        print("Error: Could not retrieve TSLA data.")
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
    trough_price = 999999.0

    for i in range(20, len(df)):
        sub_df = df.iloc[:i+1]
        regime_info = TickerRegimeEngine.analyze_ticker_regime(sub_df, "TSLA")

        current_time = df.index[i]
        bar_close = float(close_s.iloc[i])
        bar_low = float(low_s.iloc[i])
        bar_vwap = float(df["VWAP"].iloc[i])
        bar_ema9 = float(df["EMA_9"].iloc[i])
        bar_ema21 = float(df["EMA_21"].iloc[i])

        time_str = str(current_time)
        is_eod = "15:50" in time_str or "15:55" in time_str

        # 1. Exit Logic
        if position_shares > 0 and position_side == "SHORT":
            trough_price = min(trough_price, bar_low)
            profit_pct = (entry_price - bar_close) / entry_price * 100.0

            # Exit short if price reclaims VWAP + EMA21 or hits trailing profit target
            is_stopped = bar_close > bar_vwap * 1.004 or bar_close > bar_ema21 * 1.005
            is_trail_hit = (profit_pct >= 1.8 and (bar_close - trough_price) / entry_price * 100.0 >= 0.8)

            if is_stopped or is_trail_hit or is_eod:
                cover_price = bar_close
                pnl = position_shares * (entry_price - cover_price)
                capital += pnl
                return_pct = (entry_price - cover_price) / entry_price * 100.0
                reason = "EOD Flatten" if is_eod else ("Trailing Profit Cover" if is_trail_hit else "VWAP Reclaim Stop")

                trades.append({
                    "entry_time": entry_time,
                    "exit_time": current_time,
                    "side": "SHORT",
                    "shares": position_shares,
                    "entry_price": entry_price,
                    "exit_price": cover_price,
                    "pnl_$": pnl,
                    "return_%": return_pct,
                    "reason": reason
                })
                position_shares = 0
                position_side = None

        # 2. Entry Logic
        elif position_shares == 0 and not is_eod:
            # If TSLA is in BEAR_EXPANSION:
            # - LONG is 100% FORBIDDEN.
            # - If shorting allowed: Short on weak pullback retesting EMA21/VWAP from below
            if regime_info.regime == MarketRegime.BEAR_EXPANSION and allow_short:
                if bar_close < bar_vwap and bar_close <= bar_ema9 * 1.002:
                    alloc_capital = capital * 0.80
                    shares = int(alloc_capital / bar_close)
                    if shares > 0:
                        position_shares = shares
                        position_side = "SHORT"
                        entry_price = bar_close
                        entry_time = current_time
                        trough_price = bar_close

    df_trades = pd.DataFrame(trades)
    print("=" * 80)
    print("   【TSLA 独立交易明细 (INDIVIDUAL TRADE LOG)】")
    print("=" * 80)
    if not df_trades.empty:
        for idx, row in df_trades.iterrows():
            win_icon = "🟢 盈利" if row["pnl_$"] > 0 else "🔴 亏损"
            print(f"  Trade #{idx+1} | {row['entry_time']} -> {row['exit_time']} | "
                  f"{row['side']} @ ${row['entry_price']:.2f} -> ${row['exit_price']:.2f} | "
                  f"PnL: ${row['pnl_$']:+,.2f} ({row['return_%']:+.2f}%) | {win_icon} ({row['reason']})")
    else:
        print("  TSLA 今日为单边下行日，策略严格触发【绝对禁止做多】，保全本金避免逆势爆亏！")

    total_pnl = capital - initial_capital
    total_ret_pct = total_pnl / initial_capital * 100.0
    win_rate = (df_trades["pnl_$"] > 0).mean() * 100.0 if not df_trades.empty else 0.0

    print("\n" + "=" * 80)
    print("   【TSLA 独立回测指标总结】")
    print("=" * 80)
    print(f"  • 期末总资产 (Ending Equity):      ${capital:,.2f}")
    print(f"  • 累计总净利润 (Net Total PnL):    ${total_pnl:+,.2f}")
    print(f"  • 总收益率 (Total Net Return):     {total_ret_pct:+.2f}%")
    print(f"  • 胜率 (Win Rate):                 {win_rate:.1f}% ({len(df_trades)} 笔交易)")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    run_tsla_simulation()
