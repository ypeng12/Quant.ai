# backend/data/run_strict_portfolio_replay.py
"""
Strict Single-Ledger Multi-Asset Portfolio Replay Engine:
1. Strict Capital Constraint: Single unified buying power pool ($676,684.48 max).
   When a position is opened in Stock A, available buying power for Stock B/C/D shrinks in real-time.
2. Max Concurrent Position Limit = 2: Never holds more than 2 positions simultaneously.
3. Realistic Minimum Hold Time: 15 minutes (3x 5m bars) minimum hold to prevent unrealistic micro-churn.
4. Realistic Friction: 5 bps per trade (Exchange fee + spread).
"""

import os
import sys
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.alpha_engine import InstitutionalAlphaEngine
from app.ml.market_regime_hmm import MarketRegimeHMM

def run_strict_portfolio_replay():
    symbols = ["MSTR", "SNDK", "TSLA", "NVDA"]
    engine = InstitutionalAlphaEngine()
    hmm_classifier = MarketRegimeHMM()

    real_equity = 169171.12
    margin_mult = 4.0
    total_buying_power = real_equity * margin_mult  # $676,684.48 USD
    max_concurrent_positions = 2
    max_allocation_per_pos = 0.45  # Allocate up to 45% of total BP per stock (~$304k)
    friction_bps = 5.0  # 5 bps realistic friction per roundtrip/trade

    print("================================================================================")
    print("🏛️ STRICT UNIFIED CAPITAL LEDGER PORTFOLIO REPLAY (REAL-WORLD CONSTRAINTS)")
    print("================================================================================\n")
    print(f"💰 Initial Net Equity:          ${real_equity:,.2f} USD")
    print(f"🚀 Total 4x Buying Power Pool:  ${total_buying_power:,.2f} USD")
    print(f"🔒 Max Concurrent Positions:    {max_concurrent_positions} (Enforced in Real-Time)")
    print(f"⚡ Max Allocation Per Stock:     ${total_buying_power * max_allocation_per_pos:,.2f} (~45% BP)")
    print(f"🎯 Target Focus Watchlist:      {', '.join(symbols)}\n")

    stock_dfs = {}
    for s in symbols:
        try:
            df = yf.download(s, period="1mo", interval="5m", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            stock_dfs[s] = df.dropna()
        except Exception:
            pass

    if not stock_dfs:
        print("❌ Failed to load market data.")
        return

    sample_symbol = list(stock_dfs.keys())[0]
    all_dates = list(stock_dfs[sample_symbol].index.strftime("%Y-%m-%d").unique())
    last_12_dates = all_dates[-12:]  # Past 3 weeks (12 trading days)

    portfolio_equity = real_equity
    portfolio_trades = []
    daily_summaries = []

    # Active open positions: {symbol: {"side": "LONG"/"SHORT", "shares": int, "entry_price": float, "entry_time": timestamp, "invested_bp": float}}
    open_positions = {}

    for target_date in last_12_dates:
        day_start_equity = portfolio_equity
        day_realized_pnl = 0.0
        day_trades_count = 0
        day_wins_count = 0

        # Get common timestamps across all available symbols for this session
        session_slices = {}
        for s in symbols:
            df = stock_dfs.get(s)
            if df is not None:
                df_s = df[df.index.strftime("%Y-%m-%d") == target_date]
                if len(df_s) >= 10:
                    session_slices[s] = df_s

        if not session_slices:
            continue

        # Synchronous bar-by-bar time alignment
        sample_s = list(session_slices.keys())[0]
        timestamps = session_slices[sample_s].index

        for t_idx in range(5, len(timestamps)):
            current_time = timestamps[t_idx]

            # 1. First, check exits for currently open positions
            for s in list(open_positions.keys()):
                pos = open_positions[s]
                df_s = session_slices.get(s)
                if df_s is None or current_time not in df_s.index:
                    continue

                row = df_s.loc[current_time].to_dict()
                close = float(row["Close"])
                entry_price = pos["entry_price"]
                side = pos["side"]
                shares = pos["shares"]

                # PnL % calculation
                pnl_pct = ((close - entry_price) / entry_price) if side == "LONG" else ((entry_price - close) / entry_price)

                # Time in trade (bars)
                bars_in_trade = (current_time - pos["entry_time"]).total_seconds() / 300.0  # 5m bars

                # Calculate indicators
                high_s = df_s["High"].iloc[:t_idx+1]
                low_s = df_s["Low"].iloc[:t_idx+1]
                close_series = df_s["Close"].iloc[:t_idx+1]
                vol_s = df_s["Volume"].iloc[:t_idx+1]

                tp = (high_s + low_s + close_series) / 3.0
                vwap = float((tp * vol_s).cumsum().iloc[-1] / np.maximum(1.0, vol_s.cumsum().iloc[-1]))
                tr = np.maximum(high_s - low_s, np.abs(high_s - close_series.shift(1)))
                atr = float(tr.rolling(14, min_periods=1).mean().iloc[-1])

                # Exit logic: ATR Risk Stop (-1.2%) OR Momentum Exhaustion (d^2P/dt^2 < 0 & bars >= 3)
                should_exit = False
                exit_reason = ""

                if pnl_pct <= -0.012: # Strict 1.2% Risk Stop
                    should_exit = True
                    exit_reason = "STOP_LOSS"
                elif bars_in_trade >= 3:
                    # Trailing signal exit
                    micro_vel = ((close / float(close_series.iloc[-4])) - 1.0) * 100.0 if len(close_series) >= 4 else 0.0
                    if side == "LONG" and (close < vwap or micro_vel < -0.10):
                        should_exit = True
                        exit_reason = "MOM_EXHAUSTION"
                    elif side == "SHORT" and (close > vwap or micro_vel > 0.10):
                        should_exit = True
                        exit_reason = "MOM_EXHAUSTION"

                if should_exit:
                    raw_pnl = (shares * (close - entry_price)) if side == "LONG" else (shares * (entry_price - close))
                    cost = shares * close * (friction_bps / 10000.0)
                    net_pnl = raw_pnl - cost

                    day_realized_pnl += net_pnl
                    portfolio_equity += net_pnl
                    day_trades_count += 1
                    if net_pnl > 0:
                        day_wins_count += 1

                    portfolio_trades.append({
                        "date": target_date,
                        "time": current_time.strftime("%H:%M"),
                        "symbol": s,
                        "side": side,
                        "shares": shares,
                        "entry": entry_price,
                        "exit": close,
                        "pnl_pct": pnl_pct * 100.0,
                        "net_pnl": net_pnl,
                        "reason": exit_reason
                    })

                    # Free up buying power!
                    del open_positions[s]

            # 2. Next, check new entries if we have open slots (< max_concurrent_positions)
            current_occupied_bp = sum(p["invested_bp"] for p in open_positions.values())
            available_bp = total_buying_power - current_occupied_bp

            if len(open_positions) < max_concurrent_positions and available_bp >= (total_buying_power * 0.30):
                for s in symbols:
                    if s in open_positions or len(open_positions) >= max_concurrent_positions:
                        continue

                    df_s = session_slices.get(s)
                    if df_s is None or current_time not in df_s.index:
                        continue

                    row = df_s.loc[current_time].to_dict()
                    prev_row = df_s.iloc[t_idx-1].to_dict() if t_idx > 0 else row

                    close = float(row["Close"])
                    high_s = df_s["High"].iloc[:t_idx+1]
                    low_s = df_s["Low"].iloc[:t_idx+1]
                    close_series = df_s["Close"].iloc[:t_idx+1]
                    vol_s = df_s["Volume"].iloc[:t_idx+1]

                    tp = (high_s + low_s + close_series) / 3.0
                    vwap = float((tp * vol_s).cumsum().iloc[-1] / np.maximum(1.0, vol_s.cumsum().iloc[-1]))
                    micro_vel_3 = ((close / float(close_series.iloc[-4])) - 1.0) * 100.0 if len(close_series) >= 4 else 0.0

                    alpha_eval = engine.evaluate_composite_alpha(row=row, prev_row=prev_row)
                    is_trap = alpha_eval.get("is_trap", False)
                    trap_reason = alpha_eval.get("trap_reason", "")
                    composite_alpha = alpha_eval.get("composite_alpha_score", 0.0)

                    signal_side = None
                    if is_trap and "Bull Trap" in trap_reason:
                        signal_side = "SHORT"
                    elif is_trap and "Bear Trap" in trap_reason:
                        signal_side = "LONG"
                    elif composite_alpha >= 20.0 or (micro_vel_3 >= 0.18 and close > vwap):
                        signal_side = "LONG"
                    elif composite_alpha <= -20.0 or (micro_vel_3 <= -0.18 and close < vwap):
                        signal_side = "SHORT"

                    if signal_side:
                        # Allocate realistic capital from available buying power pool
                        allocated_bp = min(available_bp, total_buying_power * max_allocation_per_pos)
                        shares = max(1, int(allocated_bp / close))

                        open_positions[s] = {
                            "side": signal_side,
                            "shares": shares,
                            "entry_price": close,
                            "entry_time": current_time,
                            "invested_bp": shares * close
                        }
                        available_bp -= (shares * close)

        # EOD Closeout for any remaining open positions
        for s in list(open_positions.keys()):
            pos = open_positions[s]
            df_s = session_slices.get(s)
            if df_s is not None and not df_s.empty:
                close = float(df_s["Close"].iloc[-1])
                side = pos["side"]
                shares = pos["shares"]
                raw_pnl = (shares * (close - pos["entry_price"])) if side == "LONG" else (shares * (pos["entry_price"] - close))
                cost = shares * close * (friction_bps / 10000.0)
                net_pnl = raw_pnl - cost
                day_realized_pnl += net_pnl
                portfolio_equity += net_pnl
                day_trades_count += 1
                if net_pnl > 0:
                    day_wins_count += 1
            del open_positions[s]

        daily_win_rate = (day_wins_count / day_trades_count * 100.0) if day_trades_count > 0 else 0.0
        daily_return = (day_realized_pnl / day_start_equity) * 100.0

        daily_summaries.append({
            "date": target_date,
            "pnl": day_realized_pnl,
            "return_pct": daily_return,
            "trades": day_trades_count,
            "win_rate": daily_win_rate,
            "equity": portfolio_equity
        })

        print(f"📅 [{target_date}] Realized PnL: 💵 ${day_realized_pnl:+,.2f} USD ({daily_return:+.2f}%) | Trades: {day_trades_count} (WinRate: {daily_win_rate:.1f}%) | Equity: ${portfolio_equity:,.2f}")

    print("\n================================================================================")
    print("🏆 STRICT REALISTIC PORTFOLIO BENCHMARK SUMMARY (12 TRADING DAYS)")
    print("================================================================================")
    total_net_pnl = portfolio_equity - real_equity
    total_return_pct = (total_net_pnl / real_equity) * 100.0
    total_trades_all = len(portfolio_trades)
    total_wins_all = sum(1 for t in portfolio_trades if t["net_pnl"] > 0)
    overall_win_rate = (total_wins_all / total_trades_all * 100.0) if total_trades_all > 0 else 0.0

    print(f"💰 Starting Capital:        ${real_equity:,.2f} USD")
    print(f"🏁 Final Portfolio Equity:  ${portfolio_equity:,.2f} USD")
    print(f"📈 Total Net Realized PnL:  💵 ${total_net_pnl:+,.2f} USD")
    print(f"🚀 12-Day Net Return (%):   {total_return_pct:+.2f}%")
    print(f"🎯 Total Real Trades:       {total_trades_all} trades (Avg ~{total_trades_all // len(last_12_dates)} trades/day)")
    print(f"✅ Realized Win Rate:       {overall_win_rate:.1f}% ({total_wins_all}/{total_trades_all})")
    print(f"🔒 Max Concurrent Limit:    Strictly 2 Positions at all times")
    print("================================================================================\n")

if __name__ == "__main__":
    run_strict_portfolio_replay()
