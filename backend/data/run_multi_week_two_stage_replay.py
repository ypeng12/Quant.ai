# backend/data/run_multi_week_two_stage_replay.py
"""
Two-Stage Hierarchical ML Multi-Week Benchmark Replay:
Executes Stage-1 Regime Classification:
- Chop Range Mode (P_chop >= 55%): Mean-Reversion High-Sell at VWAP+1.5ATR / Low-Buy at VWAP-1.5ATR.
- Trend Breakout Mode (P_trend >= 55%): Trend Breakout Attack.
"""

import os
import sys
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.alpha_engine import InstitutionalAlphaEngine
from app.ml.market_regime_hmm import MarketRegimeHMM

def replay_two_stage_date_range(start_date: str, end_date: str, symbols=None):
    if symbols is None:
        symbols = ["SNDK", "TSLA", "NVDA", "MSTR"]

    engine = InstitutionalAlphaEngine()
    hmm_classifier = MarketRegimeHMM()

    real_equity = 169171.12
    margin_multiplier = 4.0
    real_buying_power = real_equity * margin_multiplier
    max_position_bp_share = 0.45

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
        return {"pnl_usd": 0.0, "return_pct": 0.0, "trades": 0, "win_rate": 0.0}

    sample_symbol = list(stock_dfs.keys())[0]
    all_dates = stock_dfs[sample_symbol].index.strftime("%Y-%m-%d").unique()
    valid_dates = [d for d in all_dates if start_date <= d <= end_date]

    if not valid_dates:
        return {"pnl_usd": 0.0, "return_pct": 0.0, "trades": 0, "win_rate": 0.0}

    range_pnl = 0.0
    total_trades = 0
    total_wins = 0

    for target_date in valid_dates:
        for symbol, df in stock_dfs.items():
            df_session = df[df.index.strftime("%Y-%m-%d") == target_date].copy()
            if len(df_session) < 10:
                continue

            close_s = df_session["Close"]
            high_s = df_session["High"]
            low_s = df_session["Low"]
            vol_s = df_session["Volume"]

            tp = (high_s + low_s + close_s) / 3.0
            vwap_s = (tp * vol_s).cumsum() / np.maximum(1.0, vol_s.cumsum())
            tr = np.maximum(high_s - low_s, np.abs(high_s - close_s.shift(1)))
            atr_s = tr.rolling(14, min_periods=1).mean()

            # Predict Stage-1 Market Regime for session
            regime_res = hmm_classifier.predict_regime_probabilities(df_session)
            p_chop = regime_res.get("p_chop_range", 0.50)

            w_t = 0.0
            entry_price = 0.0
            entry_shares = 0

            for i in range(5, len(df_session)):
                row = df_session.iloc[i].to_dict()
                prev_row = df_session.iloc[i-1].to_dict()

                close = float(row["Close"])
                vwap = float(vwap_s.iloc[i])
                atr = float(atr_s.iloc[i])

                target_w = 0.0
                if p_chop >= 0.55:
                    # STAGE-2: Mean-Reversion Arbitrage Mode (Chop Market)
                    # Sell Wall: VWAP + 1.2 ATR -> Short
                    # Buy Wall: VWAP - 1.2 ATR -> Long
                    if close >= (vwap + 1.2 * atr):
                        target_w = -1.0
                    elif close <= (vwap - 1.2 * atr):
                        target_w = 1.0
                else:
                    # STAGE-2: Trend Breakout Attack Mode
                    micro_vel_3 = ((close / float(close_s.iloc[max(0, i-3)])) - 1.0) * 100.0
                    if micro_vel_3 >= 0.18 and close > vwap:
                        target_w = 1.0
                    elif micro_vel_3 <= -0.18 and close < vwap:
                        target_w = -1.0

                if target_w != w_t:
                    if w_t != 0.0:
                        trade_pnl = entry_shares * (close - entry_price) if w_t > 0 else entry_shares * (entry_price - close)
                        range_pnl += trade_pnl
                        total_trades += 1
                        if trade_pnl > 0:
                            total_wins += 1

                    if target_w != 0.0:
                        w_t = target_w
                        entry_price = close
                        target_notional = real_buying_power * max_position_bp_share
                        entry_shares = max(1, int(target_notional / close))
                else:
                    if w_t != 0.0:
                        pnl_pct = ((close - entry_price) / entry_price) if w_t > 0 else ((entry_price - close) / entry_price)
                        if pnl_pct <= -0.010: # 1.0% Dynamic ATR Risk Stop
                            trade_pnl = entry_shares * (close - entry_price) if w_t > 0 else entry_shares * (entry_price - close)
                            range_pnl += trade_pnl
                            total_trades += 1
                            if trade_pnl > 0:
                                total_wins += 1
                            w_t = 0.0

        range_pnl += 0.0

    win_rate = (total_wins / total_trades * 100.0) if total_trades > 0 else 0.0
    return_pct = (range_pnl / real_equity) * 100.0

    return {
        "valid_dates": valid_dates,
        "pnl_usd": range_pnl,
        "return_pct": return_pct,
        "total_trades": total_trades,
        "win_rate": win_rate
    }

def main():
    print("================================================================================")
    print("🏛️ TWO-STAGE HIERARCHICAL ML MULTI-WEEK BENCHMARK REPLAY")
    print("================================================================================\n")

    # 1. This Week (2026-08-31 to 2026-09-01)
    res_this_week = replay_two_stage_date_range("2026-08-31", "2026-09-01")
    print(f"📅 1. 本周 (This Week: {', '.join(res_this_week['valid_dates'])}):")
    print(f"   • Realized Net PnL:  💵 ${res_this_week['pnl_usd']:+,.2f} USD ({res_this_week['return_pct']:+.2f}%)")
    print(f"   • Executed Trades:   {res_this_week['total_trades']} (Win Rate: {res_this_week['win_rate']:.1f}%)\n")

    # 2. Last Week (2026-08-24 to 2026-08-28)
    res_last_week = replay_two_stage_date_range("2026-08-24", "2026-08-28")
    print(f"📅 2. 上周 (Last Week: {', '.join(res_last_week['valid_dates'])}):")
    print(f"   • Realized Net PnL:  💵 ${res_last_week['pnl_usd']:+,.2f} USD ({res_last_week['return_pct']:+.2f}%)")
    print(f"   • Executed Trades:   {res_last_week['total_trades']} (Win Rate: {res_last_week['win_rate']:.1f}%)\n")

    # 3. Two Weeks Ago (2026-08-17 to 2026-08-21)
    res_two_weeks_ago = replay_two_stage_date_range("2026-08-17", "2026-08-21")
    print(f"📅 3. 上上周 (Two Weeks Ago: {', '.join(res_two_weeks_ago['valid_dates'])}):")
    print(f"   • Realized Net PnL:  💵 ${res_two_weeks_ago['pnl_usd']:+,.2f} USD ({res_two_weeks_ago['return_pct']:+.2f}%)")
    print(f"   • Executed Trades:   {res_two_weeks_ago['total_trades']} (Win Rate: {res_two_weeks_ago['win_rate']:.1f}%)\n")

    total_3w_pnl = res_this_week['pnl_usd'] + res_last_week['pnl_usd'] + res_two_weeks_ago['pnl_usd']
    start_capital = 169171.12
    total_3w_return = (total_3w_pnl / start_capital) * 100.0

    print("================================================================================")
    print("🏆 TWO-STAGE ML 3-WEEK CUMULATIVE BENCHMARK SUMMARY")
    print("================================================================================")
    print(f"💰 Starting Net Equity:     ${start_capital:,.2f} USD")
    print(f"📈 3-Week Total Net PnL:    💵 ${total_3w_pnl:+,.2f} USD ({total_3w_return:+.2f}% Total Return)")
    print(f"🏁 Final Cumulative Equity: ${start_capital + total_3w_pnl:,.2f} USD")
    print("================================================================================\n")

if __name__ == "__main__":
    main()
