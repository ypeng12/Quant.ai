# backend/data/export_by_symbol_breakdown.py
"""
Script to calculate exact breakdown by individual symbol (MSTR, TSLA, NVDA, SNDK) across the 3-week period.
"""

import os
import sys
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.alpha_engine import InstitutionalAlphaEngine
from app.ml.market_regime_hmm import MarketRegimeHMM

def breakdown_by_symbol():
    symbols = ["MSTR", "SNDK", "TSLA", "NVDA"]
    engine = InstitutionalAlphaEngine()
    hmm_classifier = MarketRegimeHMM()

    real_equity = 169171.12
    margin_multiplier = 4.0
    real_buying_power = real_equity * margin_multiplier  # $676k BP
    max_position_bp_share = 0.40  # ~$270k position per trade
    friction_bps = 3.0

    stock_dfs = {}
    for s in symbols:
        try:
            df = yf.download(s, period="1mo", interval="5m", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            stock_dfs[s] = df.dropna()
        except Exception:
            pass

    symbol_stats = {}

    for symbol in symbols:
        df = stock_dfs.get(symbol)
        if df is None:
            continue

        symbol_pnl = 0.0
        symbol_trades = 0
        symbol_wins = 0
        sample_trades = []

        all_dates = df.index.strftime("%Y-%m-%d").unique()

        for target_date in all_dates:
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

            regime_res = hmm_classifier.predict_regime_probabilities(df_session)
            p_chop = regime_res.get("p_chop_range", 0.50)

            w_t = 0.0
            entry_price = 0.0
            entry_shares = 0
            entry_time = None

            for i in range(5, len(df_session)):
                bar_time = df_session.index[i]
                row = df_session.iloc[i].to_dict()
                prev_row = df_session.iloc[i-1].to_dict()

                close = float(row["Close"])
                vwap = float(vwap_s.iloc[i])
                atr = float(atr_s.iloc[i])

                target_w = 0.0
                if p_chop >= 0.55:
                    if close >= (vwap + 1.2 * atr):
                        target_w = -1.0
                    elif close <= (vwap - 1.2 * atr):
                        target_w = 1.0
                else:
                    micro_vel_3 = ((close / float(close_s.iloc[max(0, i-3)])) - 1.0) * 100.0
                    if micro_vel_3 >= 0.18 and close > vwap:
                        target_w = 1.0
                    elif micro_vel_3 <= -0.18 and close < vwap:
                        target_w = -1.0

                if target_w != w_t:
                    if w_t != 0.0:
                        side = "LONG" if w_t > 0 else "SHORT"
                        raw_diff = (close - entry_price) if w_t > 0 else (entry_price - close)
                        trade_cost = (entry_shares * close * (friction_bps / 10000.0))
                        trade_pnl = (entry_shares * raw_diff) - trade_cost
                        pnl_pct = (raw_diff / entry_price) * 100.0

                        symbol_pnl += trade_pnl
                        symbol_trades += 1
                        if trade_pnl > 0:
                            symbol_wins += 1

                        time_str_in = entry_time.strftime("%H:%M") if hasattr(entry_time, "strftime") else str(entry_time)
                        time_str_out = bar_time.strftime("%H:%M") if hasattr(bar_time, "strftime") else str(bar_time)

                        if len(sample_trades) < 5:
                            sample_trades.append({
                                "date": target_date,
                                "time": f"{time_str_in}->{time_str_out}",
                                "side": side,
                                "shares": entry_shares,
                                "entry": entry_price,
                                "exit": close,
                                "pnl_pct": pnl_pct,
                                "pnl_usd": trade_pnl
                            })

                    if target_w != 0.0:
                        w_t = target_w
                        entry_price = close
                        entry_time = bar_time
                        target_notional = real_buying_power * max_position_bp_share
                        entry_shares = max(1, int(target_notional / close))
                else:
                    if w_t != 0.0:
                        pnl_pct_raw = ((close - entry_price) / entry_price) if w_t > 0 else ((entry_price - close) / entry_price)
                        if pnl_pct_raw <= -0.010:
                            side = "LONG" if w_t > 0 else "SHORT"
                            raw_diff = (close - entry_price) if w_t > 0 else (entry_price - close)
                            trade_cost = (entry_shares * close * (friction_bps / 10000.0))
                            trade_pnl = (entry_shares * raw_diff) - trade_cost

                            symbol_pnl += trade_pnl
                            symbol_trades += 1
                            if trade_pnl > 0:
                                symbol_wins += 1
                            w_t = 0.0

        win_rate = (symbol_wins / symbol_trades * 100.0) if symbol_trades > 0 else 0.0
        symbol_stats[symbol] = {
            "pnl_usd": symbol_pnl,
            "trades": symbol_trades,
            "win_rate": win_rate,
            "sample_trades": sample_trades
        }

    print("================================================================================")
    print("📊 4-STOCK WATCHLIST INDIVIDUAL PERFORMANCE BREAKDOWN (PAST 3 WEEKS)")
    print("================================================================================\n")

    total_pnl = sum(s["pnl_usd"] for s in symbol_stats.values())
    total_trades = sum(s["trades"] for s in symbol_stats.values())

    for symbol, st in symbol_stats.items():
        print(f"📌 {symbol}:")
        print(f"   • Realized Net PnL:   💵 ${st['pnl_usd']:+,.2f} USD")
        print(f"   • Executed Trades:    {st['trades']} trades (Win Rate: {st['win_rate']:.1f}%)")
        print(f"   • Sample Trades:")
        for t in st['sample_trades'][:3]:
            icon = "🟢" if t["pnl_usd"] > 0 else "🔴"
            print(f"     {icon} [{t['date']} {t['time']}] {t['side']} {t['shares']} shrs @ ${t['entry']:.2f} -> ${t['exit']:.2f} | PnL: {t['pnl_pct']:+.2f}% (💵 ${t['pnl_usd']:+,.2f} USD)")
        print("")

    print("--------------------------------------------------------------------------------")
    print(f"🏆 ALL 4 STOCKS COMBINED TOTAL: 💵 ${total_pnl:+,.2f} USD ({total_trades} trades)")
    print("================================================================================\n")

if __name__ == "__main__":
    breakdown_by_symbol()
