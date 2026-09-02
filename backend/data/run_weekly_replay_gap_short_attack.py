# backend/data/run_weekly_replay_gap_short_attack.py
"""
Gap-Down Short Attack Optimization Script:
Tests instant SHORT execution at Market Open (09:35 EST) when Stage-1 Regime flags a Gap-Down Breakdown (2026-08-31).
"""

import os
import sys
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.alpha_engine import InstitutionalAlphaEngine

def replay_entire_week_with_gap_short():
    symbols = ["SNDK", "TSLA", "NVDA", "MSTR"]
    engine = InstitutionalAlphaEngine()

    real_equity = 169171.12
    margin_multiplier = 4.0
    real_buying_power = real_equity * margin_multiplier  # $676,684.48 USD

    stock_dfs = {}
    for s in symbols:
        try:
            df = yf.download(s, period="1mo", interval="5m", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            stock_dfs[s] = df.dropna()
        except Exception:
            pass

    sample_symbol = list(stock_dfs.keys())[0]
    all_dates = stock_dfs[sample_symbol].index.strftime("%Y-%m-%d").unique()
    last_5_dates = list(all_dates[-5:])

    print("================================================================================")
    print("🚀 GAP-DOWN DIRECT SHORT ATTACK: PAST 5 TRADING DAYS REPLAY")
    print("================================================================================")
    print(f"📅 Dates Evaluated: {', '.join(last_5_dates)}\n")

    cumulative_pnl = 0.0
    daily_results = []

    for target_date in last_5_dates:
        day_pnl = 0.0
        day_trades = 0
        day_wins = 0

        for symbol, df in stock_dfs.items():
            df_session = df[df.index.strftime("%Y-%m-%d") == target_date].copy()
            if len(df_session) < 10:
                continue

            close_s = df_session["Close"]
            high_s = df_session["High"]
            low_s = df_session["Low"]
            open_s = df_session["Open"]
            vol_s = df_session["Volume"]

            tp = (high_s + low_s + close_s) / 3.0
            vwap_s = (tp * vol_s).cumsum() / np.maximum(1.0, vol_s.cumsum())

            # Detect Open Gap Down
            session_open = float(open_s.iloc[0])
            first_bar_close = float(close_s.iloc[0])
            gap_pct = ((first_bar_close / session_open) - 1.0) * 100.0

            w_t = 0.0
            entry_price = 0.0
            entry_shares = 0

            # If Market Opens with a Gap-Down or Breakdown -> Direct SHORT Attack at 09:35 AM!
            if gap_pct <= -0.20 or (first_bar_close < session_open):
                w_t = -1.0
                entry_price = first_bar_close
                target_notional = real_buying_power * 0.45
                entry_shares = max(1, int(target_notional / entry_price))

            for i in range(1, len(df_session)):
                row = df_session.iloc[i].to_dict()
                prev_row = df_session.iloc[i-1].to_dict()

                close = float(row["Close"])
                vwap = float(vwap_s.iloc[i])

                micro_vel_3 = ((close / float(close_s.iloc[max(0, i-3)])) - 1.0) * 100.0

                alpha_eval = engine.evaluate_composite_alpha(row=row, prev_row=prev_row)
                is_trap = alpha_eval.get("is_trap", False)
                trap_reason = alpha_eval.get("trap_reason", "")
                composite_alpha = alpha_eval.get("composite_alpha_score", 0.0)

                target_w = 0.0
                if is_trap and "Bull Trap" in trap_reason:
                    target_w = -1.0
                elif is_trap and "Bear Trap" in trap_reason:
                    target_w = 1.0
                elif composite_alpha >= 20.0 or (micro_vel_3 >= 0.15 and close > vwap):
                    target_w = 1.0
                elif composite_alpha <= -20.0 or (micro_vel_3 <= -0.15 and close < vwap):
                    target_w = -1.0

                if target_w != w_t:
                    if w_t != 0.0:
                        trade_pnl = entry_shares * (close - entry_price) if w_t > 0 else entry_shares * (entry_price - close)
                        day_pnl += trade_pnl
                        day_trades += 1
                        if trade_pnl > 0:
                            day_wins += 1

                    if target_w != 0.0:
                        w_t = target_w
                        entry_price = close
                        target_notional = real_buying_power * 0.45
                        entry_shares = max(1, int(target_notional / close))
                else:
                    if w_t != 0.0:
                        pnl_pct = ((close - entry_price) / entry_price) if w_t > 0 else ((entry_price - close) / entry_price)
                        if pnl_pct <= -0.015: # Strict Risk Stop Loss
                            trade_pnl = entry_shares * (close - entry_price) if w_t > 0 else entry_shares * (entry_price - close)
                            day_pnl += trade_pnl
                            day_trades += 1
                            if trade_pnl > 0:
                                day_wins += 1
                            w_t = 0.0

        cumulative_pnl += day_pnl
        win_rate = (day_wins / day_trades * 100.0) if day_trades > 0 else 0.0
        daily_return = (day_pnl / real_equity) * 100.0

        daily_results.append({
            "date": target_date,
            "pnl_usd": day_pnl,
            "return_pct": daily_return,
            "trades": day_trades,
            "win_rate": win_rate,
            "cum_pnl": cumulative_pnl,
            "cum_return": (cumulative_pnl / real_equity) * 100.0
        })

        print(f"📅 [{target_date}] Net PnL: 💵 ${day_pnl:+,.2f} USD ({daily_return:+.2f}%) | Trades: {day_trades} (WinRate: {win_rate:.1f}%) | Cum PnL: 💵 ${cumulative_pnl:+,.2f} USD")

    print("\n================================================================================")
    print("🏆 GAP-DOWN DIRECT SHORT ATTACK: 5-DAY CUMULATIVE REPLAY SUMMARY")
    print("================================================================================")
    total_cum_pnl = cumulative_pnl
    total_cum_return = (total_cum_pnl / real_equity) * 100.0
    total_trades_week = sum(d["trades"] for d in daily_results)

    print(f"💰 Account Starting Capital:  ${real_equity:,.2f} USD")
    print(f"📈 5-Day Cumulative Net PnL:  💵 ${total_cum_pnl:+,.2f} USD")
    print(f"🚀 5-Day Total Return (%):    {total_cum_return:+.2f}%")
    print(f"📊 Total Trades Executed:    {total_trades_week} trades")
    print(f"🏁 Final Equity Value:        ${real_equity + total_cum_pnl:,.2f} USD")
    print("================================================================================\n")

if __name__ == "__main__":
    replay_entire_week_with_gap_short()
