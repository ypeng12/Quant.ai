# backend/data/run_today_market_replay.py
"""
Institutional Replay Engine:
1. Reads Real Account Buying Power (e.g. $400,000 - $676,000 USD with 4x margin leverage).
2. Uses Continuous Target Position Flipping w_t* in [-1.0, +1.0] driven by Microprice Velocity & OFI acceleration.
   Captures instant top/bottom reversals without waiting for lagging EMA crosses.
"""

import os
import sys
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.alpha_engine import InstitutionalAlphaEngine
from app.broker.probability_engine import evaluate_mathematical_expectation

def run_real_account_market_replay():
    print("================================================================================")
    print("🏛️ QUANT.AI INSTITUTIONAL CONTINUOUS TARGET POSITION ENGINE (HRT/JANE STREET MODE)")
    print("================================================================================\n")

    symbols = ["SNDK", "TSLA", "NVDA", "MSTR"]
    engine = InstitutionalAlphaEngine()

    # Read Real Account Parameters (4x Intraday Buying Power Leverage)
    real_equity = 169171.12
    margin_multiplier = 4.0
    real_buying_power = real_equity * margin_multiplier  # $676,684.48 USD
    max_position_bp_share = 0.45  # Allocate up to 45% buying power per focus stock (~$304k position)

    print(f"💰 Real Account Net Equity:    ${real_equity:,.2f}")
    print(f"🚀 Intraday 4x Buying Power:   ${real_buying_power:,.2f}")
    print(f"⚡ Allocation Per Ticker:      ${real_buying_power * max_position_bp_share:,.2f} (~45% BP)")
    print(f"🎯 Target Focus Watchlist:     {', '.join(symbols)}\n")

    portfolio_pnl = 0.0
    trades_logged = []

    for symbol in symbols:
        print(f"--------------------------------------------------------------------------------")
        print(f"🔍 Executing Continuous Target Position (w_t*) Replay for: {symbol}")
        print(f"--------------------------------------------------------------------------------")
        
        try:
            df = yf.download(symbol, period="5d", interval="5m", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
        except Exception as e:
            print(f"⚠️ Error fetching yfinance data for {symbol}: {e}")
            continue

        if df.empty or len(df) < 15:
            continue

        df = df.dropna()
        latest_date = df.index.strftime("%Y-%m-%d").max()
        df_session = df[df.index.strftime("%Y-%m-%d") == latest_date].copy()
        if len(df_session) < 10:
            df_session = df.tail(40).copy()

        print(f"📅 Session Replay Date: {latest_date} ({len(df_session)} 5m bars)")

        close_s = df_session["Close"]
        high_s = df_session["High"]
        low_s = df_session["Low"]
        open_s = df_session["Open"]
        vol_s = df_session["Volume"]

        # Fast Indicators & Microprice Velocity
        tp = (high_s + low_s + close_s) / 3.0
        vwap_s = (tp * vol_s).cumsum() / np.maximum(1.0, vol_s.cumsum())
        tr = np.maximum(high_s - low_s, np.abs(high_s - close_s.shift(1)))
        atr_s = tr.rolling(14, min_periods=1).mean()
        rvol_s = vol_s / np.maximum(1.0, vol_s.rolling(20, min_periods=1).mean())

        session_open = open_s.iloc[0]
        session_high = high_s.max()
        session_low = low_s.min()

        # Continuous State: Target Weight w_t in {-1.0, 0.0, +1.0}
        w_t = 0.0
        entry_price = 0.0
        entry_shares = 0
        entry_time = None
        entry_p_win = 0.0

        ticker_pnl = 0.0
        ticker_trades = 0
        ticker_wins = 0

        for i in range(5, len(df_session)):
            bar_time = df_session.index[i]
            row = df_session.iloc[i].to_dict()
            prev_row = df_session.iloc[i-1].to_dict()

            close = float(row["Close"])
            vwap = float(vwap_s.iloc[i])
            atr = float(atr_s.iloc[i])
            rvol = float(rvol_s.iloc[i])

            # Microprice Velocity (1-bar and 3-bar price velocity)
            micro_vel_1 = ((close / float(close_s.iloc[i-1])) - 1.0) * 100.0
            micro_vel_3 = ((close / float(close_s.iloc[max(0, i-3)])) - 1.0) * 100.0
            high_to_now_pct = float(((close / session_high) - 1.0) * 100.0)
            low_to_now_pct = float(((close / session_low) - 1.0) * 100.0)

            # Evaluate Microstructure Trap & OFI Acceleration
            alpha_eval = engine.evaluate_composite_alpha(row=row, prev_row=prev_row)
            is_trap = alpha_eval.get("is_trap", False)
            trap_reason = alpha_eval.get("trap_reason", "")
            composite_alpha = alpha_eval.get("composite_alpha_score", 0.0)

            # Institutional Continuous Target Position Model (Instant Flip Signal)
            # Replaces lagging moving averages with instantaneous Microprice Velocity & OFI Trap Reversal
            target_w = 0.0
            if is_trap and "Bull Trap" in trap_reason:
                target_w = -1.0  # Instant Top Reversal Flip -> Short
            elif is_trap and "Bear Trap" in trap_reason:
                target_w = 1.0   # Instant Bottom Reversal Flip -> Long
            elif composite_alpha >= 25.0 or (micro_vel_3 >= 0.15 and close > vwap):
                target_w = 1.0   # Bullish Momentum
            elif composite_alpha <= -25.0 or (micro_vel_3 <= -0.15 and close < vwap):
                target_w = -1.0  # Bearish Momentum

            # State Transition & Order Execution
            if target_w != w_t:
                # Close existing position if any
                if w_t != 0.0:
                    side = "LONG" if w_t > 0 else "SHORT"
                    pnl_pct = ((close - entry_price) / entry_price) if w_t > 0 else ((entry_price - close) / entry_price)
                    trade_pnl = entry_shares * (close - entry_price) if w_t > 0 else entry_shares * (entry_price - close)
                    ticker_pnl += trade_pnl
                    if trade_pnl > 0:
                        ticker_wins += 1

                    trades_logged.append({
                        "ticker": symbol,
                        "direction": side,
                        "shares": entry_shares,
                        "entry_price": entry_price,
                        "exit_price": close,
                        "pnl_pct": pnl_pct,
                        "pnl_dollar": trade_pnl,
                    })
                    time_str = bar_time.strftime("%H:%M") if hasattr(bar_time, "strftime") else str(bar_time)
                    print(f"  🔴 [{time_str}] EXIT {side} ({entry_shares} shrs) @ ${close:.2f} | PnL={pnl_pct*100:+.2f}% (💵 ${trade_pnl:+,.2f} USD)")

                # Open new position if target_w != 0.0
                if target_w != 0.0:
                    w_t = target_w
                    entry_price = close
                    entry_time = bar_time
                    target_notional = real_buying_power * max_position_bp_share
                    entry_shares = max(1, int(target_notional / close))
                    direction_str = "LONG" if w_t > 0 else "SHORT"
                    ticker_trades += 1
                    time_str = bar_time.strftime("%H:%M") if hasattr(bar_time, "strftime") else str(bar_time)
                    print(f"  🟢 [{time_str}] INSTANT FLIP {direction_str} ({entry_shares} shrs / ${entry_shares*close:,.2f}) @ ${close:.2f} | Alpha={composite_alpha:+.1f} | MicroVel={micro_vel_3:+.2f}%")
            else:
                # Check Risk Stop Loss
                if w_t != 0.0:
                    pnl_pct = ((close - entry_price) / entry_price) if w_t > 0 else ((entry_price - close) / entry_price)
                    if pnl_pct <= -0.015: # 1.5% Strict ATR Stop Loss
                        side = "LONG" if w_t > 0 else "SHORT"
                        trade_pnl = entry_shares * (close - entry_price) if w_t > 0 else entry_shares * (entry_price - close)
                        ticker_pnl += trade_pnl
                        trades_logged.append({"ticker": symbol, "direction": side, "shares": entry_shares, "entry_price": entry_price, "exit_price": close, "pnl_pct": pnl_pct, "pnl_dollar": trade_pnl})
                        time_str = bar_time.strftime("%H:%M") if hasattr(bar_time, "strftime") else str(bar_time)
                        print(f"  🛑 [{time_str}] STOP EXIT {side} ({entry_shares} shrs) @ ${close:.2f} | PnL={pnl_pct*100:+.2f}% (💵 ${trade_pnl:+,.2f} USD)")
                        w_t = 0.0

        portfolio_pnl += ticker_pnl
        win_rate_ticker = (ticker_wins / ticker_trades * 100.0) if ticker_trades > 0 else 0.0
        print(f"\n📌 {symbol} Institutional Replay Summary: Trades={ticker_trades} | Win Rate={win_rate_ticker:.1f}% | Net Realized PnL=💵 ${ticker_pnl:+,.2f} USD\n")

    print("================================================================================")
    print("🏆 REAL ACCOUNT BUYING POWER ($676K BP) - HRT/JANE STREET MODE DIAGNOSTIC RESULT")
    print("================================================================================")
    total_trades = len(trades_logged)
    total_wins = sum(1 for t in trades_logged if t["pnl_dollar"] > 0)
    win_rate = (total_wins / total_trades * 100.0) if total_trades > 0 else 0.0
    return_pct = (portfolio_pnl / real_equity) * 100.0

    print(f"💰 Account Real Equity:     ${real_equity:,.2f} USD")
    print(f"⚡ Intraday Buying Power:    ${real_buying_power:,.2f} USD (4x Leverage)")
    print(f"📈 Total Net Realized PnL:   💵 ${portfolio_pnl:+,.2f} USD ({return_pct:+.2f}% Net Return)")
    print(f"🎯 Total Trades Executed:    {total_trades}")
    print(f"✅ Winning Trades / WinRate: {total_wins}/{total_trades} ({win_rate:.1f}%)")
    print(f"⚡ Engine Architecture:      Continuous Target Position Model (w_t*) + Microprice Acceleration")
    print("================================================================================\n")

if __name__ == "__main__":
    run_real_account_market_replay()
