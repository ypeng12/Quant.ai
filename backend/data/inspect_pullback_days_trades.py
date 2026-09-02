# backend/data/inspect_pullback_days_trades.py
"""
Inspect trades on the 4 drawdown days (08-20, 08-21, 08-27, 08-28) to analyze why shorting wasn't flexible.
"""

import os
import sys
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.alpha_engine import InstitutionalAlphaEngine

def inspect_pullback_days():
    symbols = ["MSTR", "SNDK", "TSLA", "NVDA"]
    engine = InstitutionalAlphaEngine()

    pullback_dates = ["2026-08-20", "2026-08-21", "2026-08-27", "2026-08-28"]

    for target_date in pullback_dates:
        print(f"================================================================================")
        print(f"🔍 INSPECTING TRADES FOR PULLBACK DAY: {target_date}")
        print(f"================================================================================")

        for s in symbols:
            try:
                df = yf.download(s, period="1mo", interval="5m", progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df_s = df[df.index.strftime("%Y-%m-%d") == target_date]
                if len(df_s) < 10:
                    continue

                close_s = df_s["Close"]
                high_s = df_s["High"]
                low_s = df_s["Low"]
                open_s = df_s["Open"]
                vol_s = df_s["Volume"]

                day_open = open_s.iloc[0]
                day_close = close_s.iloc[-1]
                day_change_pct = ((day_close / day_open) - 1.0) * 100.0

                print(f"📌 {s} on {target_date}: Open=${day_open:.2f} -> Close=${day_close:.2f} (Change: {day_change_pct:+.2f}%)")

            except Exception as e:
                pass
        print("")

if __name__ == "__main__":
    inspect_pullback_days()
