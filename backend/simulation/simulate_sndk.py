# backend/simulation/simulate_sndk.py
"""
Dedicated Ticker Simulation: SNDK (High-Momentum Breakout & Trend-Holding Leader)
Zero-overlap independent simulation for SNDK.
Focus:
- Avoids 30s micro-panic exits.
- Adheres to GP Saggese's 5-30m+ wave holding principle.
- Leverages BULL_EXPANSION regime: buys momentum pullbacks near VWAP/EMA9, rides trend with trailing stop.
"""

import sys
import os
import yfinance as yf
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from backend.app.ml.ticker_regime_engine import TickerRegimeEngine, MarketRegime

def run_sndk_simulation(period="5d", interval="5m", initial_capital=100000.0):
    print("=" * 80)
    print("      【SNDK 独立专用量化回测与模拟系统 (DEDICATED SIMULATION: SNDK)】")
    print("      核心特征: 高动量、强单边趋势、5~45分钟波段锁仓、拒绝秒级微观假摔洗盘")
    print(f"      初始本金: ${initial_capital:,.2f} | 数据周期: {period} (Interval: {interval})")
    print("=" * 80 + "\n")

    df = yf.download("SNDK", period=period, interval=interval, progress=False)
    if df.empty:
        print("Error: Could not retrieve SNDK data.")
        return

    # Clean multi-index columns if present
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

    # Simulation State
    capital = initial_capital
    position_shares = 0
    entry_price = 0.0
    entry_time = None
    trades = []
    peak_price = 0.0

    # Iterate through bars
    for i in range(20, len(df)):
        sub_df = df.iloc[:i+1]
        regime_info = TickerRegimeEngine.analyze_ticker_regime(sub_df, "SNDK")

        current_time = df.index[i]
        bar_open = float(open_s.iloc[i])
        bar_high = float(high_s.iloc[i])
        bar_low = float(low_s.iloc[i])
        bar_close = float(close_s.iloc[i])
        bar_vwap = float(df["VWAP"].iloc[i])
        bar_ema9 = float(df["EMA_9"].iloc[i])
        bar_ema21 = float(df["EMA_21"].iloc[i])

        time_str = str(current_time)
        is_eod = "15:50" in time_str or "15:55" in time_str

        # 1. Check Exit if holding
        if position_shares > 0:
            peak_price = max(peak_price, bar_high)
            pnl_pct = (bar_close - entry_price) / entry_price * 100.0

            # Dynamic Trailing Exit for SNDK (GP Saggese wave rule: don't exit on micro dips)
            # Exit condition 1: Hard trend break (Close falls below EMA21 by > 0.6% AND below VWAP)
            # Exit condition 2: Large runner trailing stop (if up > 3.0%, trail 1.5% from peak)
            is_trend_broken = (bar_close < bar_ema21 * 0.994 and bar_close < bar_vwap)
            is_profit_trail_hit = (pnl_pct >= 2.5 and (peak_price - bar_close) / peak_price * 100.0 >= 1.5)

            if is_trend_broken or is_profit_trail_hit or is_eod:
                exit_price = bar_close
                trade_pnl = position_shares * (exit_price - entry_price)
                capital += position_shares * exit_price
                return_pct = (exit_price - entry_price) / entry_price * 100.0
                reason = "EOD Flatten" if is_eod else ("Trailing Stop Peak Lock" if is_profit_trail_hit else "Trend Life-Line Break")

                trades.append({
                    "entry_time": entry_time,
                    "exit_time": current_time,
                    "side": "LONG",
                    "shares": position_shares,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_$": trade_pnl,
                    "return_%": return_pct,
                    "reason": reason
                })
                position_shares = 0
                entry_price = 0.0

        # 2. Check Entry if flat
        elif position_shares == 0 and not is_eod:
            # SNDK Entry Rule: In BULL_EXPANSION or strong upward momentum pullback to EMA9/VWAP
            if regime_info.regime == MarketRegime.BULL_EXPANSION:
                # Enter when price is comfortably above VWAP and testing EMA9
                if bar_close >= bar_vwap and bar_close >= bar_ema9 * 0.998:
                    # Allocate 90% buying power into leader
                    alloc_capital = capital * 0.90
                    position_shares = int(alloc_capital / bar_close)
                    if position_shares > 0:
                        entry_price = bar_close
                        entry_time = current_time
                        peak_price = bar_close
                        capital -= position_shares * bar_close

    # Close open position at end
    if position_shares > 0:
        final_close = float(close_s.iloc[-1])
        trade_pnl = position_shares * (final_close - entry_price)
        capital += position_shares * final_close
        return_pct = (final_close - entry_price) / entry_price * 100.0
        trades.append({
            "entry_time": entry_time,
            "exit_time": df.index[-1],
            "side": "LONG",
            "shares": position_shares,
            "entry_price": entry_price,
            "exit_price": final_close,
            "pnl_$": trade_pnl,
            "return_%": return_pct,
            "reason": "Market Close Final Mark"
        })

    # Summary Statistics
    df_trades = pd.DataFrame(trades)
    print("=" * 80)
    print("   【SNDK 独立交易明细 (INDIVIDUAL TRADE LOG)】")
    print("=" * 80)
    if not df_trades.empty:
        for idx, row in df_trades.iterrows():
            win_icon = "🟢 盈利" if row["pnl_$"] > 0 else "🔴 亏损"
            print(f"  Trade #{idx+1} | {row['entry_time']} -> {row['exit_time']} | "
                  f"Entry: ${row['entry_price']:.2f} | Exit: ${row['exit_price']:.2f} | "
                  f"PnL: ${row['pnl_$']:+,.2f} ({row['return_%']:+.2f}%) | {win_icon} ({row['reason']})")
    else:
        print("  No trades triggered under strict regime criteria.")

    total_pnl = capital - initial_capital
    total_ret_pct = total_pnl / initial_capital * 100.0
    win_rate = (df_trades["pnl_$"] > 0).mean() * 100.0 if not df_trades.empty else 0.0

    print("\n" + "=" * 80)
    print("   【SNDK 独立回测指标总结】")
    print("=" * 80)
    print(f"  • 期末总资产 (Ending Equity):      ${capital:,.2f}")
    print(f"  • 累计总净利润 (Net Total PnL):    ${total_pnl:+,.2f}")
    print(f"  • 总收益率 (Total Net Return):     {total_ret_pct:+.2f}%")
    print(f"  • 胜率 (Win Rate):                 {win_rate:.1f}% ({len(df_trades)} 笔交易)")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    run_sndk_simulation()
