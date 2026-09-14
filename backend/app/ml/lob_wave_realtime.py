# backend/app/ml/lob_wave_realtime.py
"""
Read-only classic wave display using observed bars and labelled OHLCV rules.
Real L1 research remains available through its separate capture/feature pipeline.
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


def compute_live_wave_day_data(ticker: str, *, now=None) -> Dict[str, Any]:
    """Classic OHLCV rule view for today's completed bars; never a measured book."""
    from .classic_dashboard import build_wave_data, symbol_name
    tk = symbol_name(ticker)
    cutoff = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="America/New_York")
    if cutoff.tzinfo is None:
        raise ValueError("Timezone-aware current time required")
    cutoff = cutoff.tz_convert("America/New_York")
    raw = fetch_today_bars(tk)
    if raw.empty:
        return {"success": False, "status": "unavailable", "ticker": tk, "error": "今日行情暂不可用，可切换历史日期。"}
    if raw.index.tz is None:
        raise ValueError("Observed bars require timezone-aware timestamps")
    raw = raw.tz_convert("America/New_York")
    raw = raw.loc[(raw.index + pd.Timedelta(minutes=1) <= cutoff) & (raw.index.date == cutoff.date())]
    if raw.empty:
        return {"success": False, "status": "unavailable", "ticker": tk, "error": "今日尚无已完成 K 线，可选择历史交易日。"}
    frame = raw.resample("5min").agg({"Open":"first", "High":"max", "Low":"min", "Close":"last", "Volume":"sum"})
    counts = raw.Close.resample("5min").count()
    frame = frame.loc[(counts == 5) & (frame.index + pd.Timedelta(minutes=5) <= cutoff)].dropna().between_time("09:30", "15:55")
    if frame.empty:
        return {"success": False, "status": "unavailable", "ticker": tk, "error": "等待完整的五分钟 K 线，可先查看历史展示。"}
    day = cutoff.date().isoformat()
    data = build_wave_data(frame, tk, day, raw.attrs.get("bar_source", "observed_1m_bars"))
    return {"success": True, "status": "current_ohlcv_view", "ticker": tk, "date": day,
            "is_today": True, "last_updated": cutoff.isoformat(), "data": data,
            "data_provenance": {**data["data_provenance"], "current_session": True,
                                "latest_bar_at": frame.index[-1].isoformat()}}
