# backend/app/ml/lob_wave_realtime.py
"""
Read-only availability of captured L1 quotes aligned with recent bars.
The legacy OHLCV-proxy wave model is retired; this module returns no trading
probability, synthetic order book, or live wave signal.
"""

import os
import sys
import datetime
import pytz
import pandas as pd
from typing import Dict, Any

# Ensure backend root is in sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.market_data.history import credentials
from app.market_data.alpaca_l1_capture import load_real_l1_quotes, real_l1_to_five_minute


def fetch_today_bars(ticker: str) -> pd.DataFrame:
    """
    Fetches real-time intraday bars from Alpaca.
    Retrieves the last 3 calendar days to guarantee sufficient history for
    VWAP cumulative calculation and EMA9/EMA21 smoothing on market open.
    """
    tk = str(ticker).upper().strip()
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed

        key, secret = credentials()
        client = StockHistoricalDataClient(key, secret)
        ny_tz = pytz.timezone("America/New_York")
        end_dt = datetime.datetime.now(ny_tz)
        # Fetch 3 calendar days of 1-minute bars
        start_dt = end_dt - datetime.timedelta(days=3)

        req = StockBarsRequest(
            symbol_or_symbols=[tk],
            timeframe=TimeFrame.Minute,
            start=start_dt,
            end=end_dt,
            feed=DataFeed.IEX
        )
        bars = client.get_stock_bars(req)
        raw_list = bars.data.get(tk, [])
        if raw_list:
            data = [{
                "timestamp": b.timestamp,
                "Open": float(b.open),
                "High": float(b.high),
                "Low": float(b.low),
                "Close": float(b.close),
                "Volume": float(b.volume),
                "vwap": float(b.vwap or b.close)
            } for b in raw_list]
            df = pd.DataFrame(data).set_index("timestamp")
            df.index = pd.to_datetime(df.index).tz_convert(ny_tz)
            df.attrs["bar_source"] = "alpaca_iex_1m"
            return df
    except Exception as e:
        print(f"⚠️ [Alpaca Live Fetch Warning for {tk}]: {e}")

    # Fallback to Yahoo Finance intraday
    try:
        import yfinance as yf
        stock = yf.Ticker(tk)
        df = stock.history(period="3d", interval="1m", prepost=False)
        if not df.empty:
            if df.index.tz is None:
                df = df.tz_localize("UTC").tz_convert("America/New_York")
            else:
                df = df.tz_convert("America/New_York")
            for c in ["Open", "High", "Low", "Close", "Volume"]:
                df[c] = df[c].astype(float)
            df["vwap"] = df["Close"]
            df.attrs["bar_source"] = "yahoo_1m_fallback"
            return df
    except Exception as e2:
        print(f"⚠️ [YFinance Live Fetch Warning for {tk}]: {e2}")

    return pd.DataFrame()


def compute_live_wave_day_data(ticker: str) -> Dict[str, Any]:
    """Report captured L1 availability without inferring a legacy wave signal.

    The old wave artifact used OHLCV-derived proxy-book fields.  A real quote
    stream deserves a separate causal, walk-forward training run, so this route
    does not attach its former probabilities or trade signals to L1 data.
    """
    tk = str(ticker).upper().strip()
    df_raw = fetch_today_bars(tk)
    if df_raw.empty or len(df_raw) < 2:
        return {
            "success": False, "status": "unavailable", "ticker": tk,
            "error": "No current intraday bars are available to align captured L1 data.",
        }

    df_5m = df_raw.resample("5min").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    }).dropna()
    df_5m = df_5m.between_time("09:30", "16:00")
    if df_5m.empty:
        return {
            "success": False, "status": "unavailable", "ticker": tk,
            "error": "No regular-session bars are available to align captured L1 data.",
        }

    l1_dir = os.getenv("QUANT_L1_CAPTURE_DIR", os.path.join(backend_dir, "data", "l1_capture"))
    session_day = df_5m.index[-1].date().isoformat()
    raw_quotes = load_real_l1_quotes(l1_dir, tk, session_day)
    l1_quotes = real_l1_to_five_minute(raw_quotes)
    real_l1_rows = 0
    if not l1_quotes.empty:
        joined = df_5m.join(l1_quotes, how="left")
        real_l1_rows = int(joined[["bid_price", "bid_size", "ask_price", "ask_size"]].notna().all(axis=1).sum())

    return {
        "success": False,
        "status": "unavailable",
        "ticker": tk,
        "data_provenance": {
            "bar_source": df_raw.attrs.get("bar_source", "unavailable"),
            "lob_source": "captured_alpaca_l1_quotes" if real_l1_rows else None,
            "market_depth": "L1" if real_l1_rows else None,
            "real_l1_five_minute_rows": real_l1_rows,
            "l1_session_date": session_day if real_l1_rows else None,
            "latest_quote_at": raw_quotes.index.max().isoformat() if not raw_quotes.empty else None,
        },
        "error": "The legacy wave model used OHLCV proxy-book features and is retired. Captured real L1 events are reserved for the new walk-forward research pipeline.",
    }
