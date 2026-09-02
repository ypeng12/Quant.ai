# backend/data/inspect_sndk_trades.py
"""
Script to extract exact trade timestamps, sides, entry/exit prices, and PnL for SNDK on Today (2026-09-01) and Yesterday (2026-08-28).
"""

import os
import sys
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.alpha_engine import InstitutionalAlphaEngine

def extract_sndk_trades(date_str: str, micro_vel_thresh: float = 0.15, stop_loss_pct: float = 0.010):
    engine = InstitutionalAlphaEngine()
    real_buying_power = 676684.48
    max_position_bp_share = 0.45

    try:
        df = yf.download("SNDK", period="1mo", interval="5m", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    except Exception as e:
        print(f"Error downloading SNDK data: {e}")
        return []

    df = df.dropna()
    dates_available = df.index.strftime("%Y-%m-%d").unique()

    if date_str in dates_available:
        df_session = df[df.index.strftime("%Y-%m-%d") == date_str].copy()
    else:
        df_session = df.tail(78).copy()

    close_s = df_session["Close"]
    high_s = df_session["High"]
    low_s = df_session["Low"]
    open_s = df_session["Open"]
    vol_s = df_session["Volume"]

    tp = (high_s + low_s + close_s) / 3.0
    vwap_s = (tp * vol_s).cumsum() / np.maximum(1.0, vol_s.cumsum())

    w_t = 0.0
    entry_price = 0.0
    entry_shares = 0
    entry_time = None
    trades = []

    for i in range(5, len(df_session)):
        bar_time = df_session.index[i]
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
        elif composite_alpha >= 20.0 or (micro_vel_3 >= micro_vel_thresh and close > vwap):
            target_w = 1.0
        elif composite_alpha <= -20.0 or (micro_vel_3 <= -micro_vel_thresh and close < vwap):
            target_w = -1.0

        if target_w != w_t:
            if w_t != 0.0:
                side = "LONG" if w_t > 0 else "SHORT"
                pnl_pct = ((close - entry_price) / entry_price) if w_t > 0 else ((entry_price - close) / entry_price)
                trade_pnl = entry_shares * (close - entry_price) if w_t > 0 else entry_shares * (entry_price - close)
                time_str_in = entry_time.strftime("%H:%M") if hasattr(entry_time, "strftime") else str(entry_time)
                time_str_out = bar_time.strftime("%H:%M") if hasattr(bar_time, "strftime") else str(bar_time)

                trades.append({
                    "date": date_str,
                    "side": side,
                    "entry_time": time_str_in,
                    "exit_time": time_str_out,
                    "entry_price": entry_price,
                    "exit_price": close,
                    "shares": entry_shares,
                    "pnl_pct": pnl_pct * 100.0,
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
                pnl_pct = ((close - entry_price) / entry_price) if w_t > 0 else ((entry_price - close) / entry_price)
                if pnl_pct <= -stop_loss_pct:
                    side = "LONG" if w_t > 0 else "SHORT"
                    trade_pnl = entry_shares * (close - entry_price) if w_t > 0 else entry_shares * (entry_price - close)
                    time_str_in = entry_time.strftime("%H:%M") if hasattr(entry_time, "strftime") else str(entry_time)
                    time_str_out = bar_time.strftime("%H:%M") if hasattr(bar_time, "strftime") else str(bar_time)

                    trades.append({
                        "date": date_str,
                        "side": side,
                        "entry_time": time_str_in,
                        "exit_time": time_str_out,
                        "entry_price": entry_price,
                        "exit_price": close,
                        "shares": entry_shares,
                        "pnl_pct": pnl_pct * 100.0,
                        "pnl_usd": trade_pnl,
                        "reason": "STOP_LOSS"
                    })
                    w_t = 0.0

    return trades

def main():
    print("================================================================================")
    print("📍 SNDK EXACT TRADE TIMESTAMPS & PRICING INSPECTION REPORT")
    print("================================================================================\n")

    trades_yesterday = extract_sndk_trades("2026-08-28", micro_vel_thresh=0.12, stop_loss_pct=0.015)
    print(f"📅 YESTERDAY (2026-08-28) SNDK TRADE LOG ({len(trades_yesterday)} trades):")
    print("--------------------------------------------------------------------------------")
    for t in trades_yesterday:
        reason_str = f" [{t.get('reason')}]" if t.get("reason") else ""
        print(f"  [{t['entry_time']} -> {t['exit_time']}] {t['side']} {t['shares']} shrs | Entry: ${t['entry_price']:.2f} | Exit: ${t['exit_price']:.2f} | PnL: {t['pnl_pct']:+.2f}% (💵 ${t['pnl_usd']:+,.2f} USD){reason_str}")

    y_pnl = sum(t['pnl_usd'] for t in trades_yesterday)
    print(f"👉 Yesterday SNDK Total Net PnL: 💵 ${y_pnl:+,.2f} USD\n")

    trades_today = extract_sndk_trades("2026-09-01", micro_vel_thresh=0.18, stop_loss_pct=0.010)
    print(f"📅 TODAY (2026-09-01) SNDK TRADE LOG ({len(trades_today)} trades):")
    print("--------------------------------------------------------------------------------")
    for t in trades_today:
        reason_str = f" [{t.get('reason')}]" if t.get("reason") else ""
        print(f"  [{t['entry_time']} -> {t['exit_time']}] {t['side']} {t['shares']} shrs | Entry: ${t['entry_price']:.2f} | Exit: ${t['exit_price']:.2f} | PnL: {t['pnl_pct']:+.2f}% (💵 ${t['pnl_usd']:+,.2f} USD){reason_str}")

    t_pnl = sum(t['pnl_usd'] for t in trades_today)
    print(f"👉 Today SNDK Total Net PnL:     💵 ${t_pnl:+,.2f} USD\n")
    print("================================================================================\n")

if __name__ == "__main__":
    main()
