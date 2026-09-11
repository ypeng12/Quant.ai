# backend/app/ml/lob_wave_realtime.py
"""
Real-Time Limit Order Book (LOB) & Saggese Microstructure Wave Alpha Service.
Provides on-demand, sub-second calculation of today's live intraday microstructure:
1. Fetches real-time 1m bars up to the current minute from Alpaca IEX/SIP.
2. Resamples into 5m microstructure wave bars.
3. Computes 7 causal LOB microstructure features (OFI, Microprice Drift, Queue Imbalance, Sweep Velocity).
4. Runs calibrated MicrostructureWaveAlphaEngine inference (Long/Short wave probability & Expected Return).
5. Evaluates Institutional Multi-Factor Alpha to generate actionable, debounced wave reversal signals.
"""

import os
import sys
import datetime
import pytz
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

# Ensure backend root is in sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY
from app.ml.lob_microstructure_ml import MicrostructureWaveAlphaEngine
from app.alpha_engine import InstitutionalAlphaEngine

# Global singleton engine instances for sub-millisecond reuse
_wave_engine_instance: Optional[MicrostructureWaveAlphaEngine] = None
_alpha_engine_instance: Optional[InstitutionalAlphaEngine] = None

def get_wave_engine() -> MicrostructureWaveAlphaEngine:
    global _wave_engine_instance
    if _wave_engine_instance is None:
        _wave_engine_instance = MicrostructureWaveAlphaEngine.load()
    return _wave_engine_instance

def get_alpha_engine() -> InstitutionalAlphaEngine:
    global _alpha_engine_instance
    if _alpha_engine_instance is None:
        _alpha_engine_instance = InstitutionalAlphaEngine()
    return _alpha_engine_instance


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

        client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
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
            return df
    except Exception as e2:
        print(f"⚠️ [YFinance Live Fetch Warning for {tk}]: {e2}")

    return pd.DataFrame()


def compute_live_wave_day_data(ticker: str) -> Dict[str, Any]:
    """
    Computes today's real-time LOB microstructure wave alpha data for the given ticker.
    Returns format identical to the Saggese visual dashboard schema.
    """
    tk = str(ticker).upper().strip()
    df_raw = fetch_today_bars(tk)
    if df_raw.empty or len(df_raw) < 2:
        return {
            "success": False,
            "error": f"暂未获取到 {tk} 当天的实时 K 线数据，请确认当前美股是否处于开盘时段或检查网络连接。"
        }

    # Resample 1m to 5m
    df_5m = df_raw.resample("5min").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()

    if df_5m.empty:
        return {"success": False, "error": f"{tk} 重采样 5 分钟线数据为空"}

    # Filter regular market hours 09:30 - 16:00
    df_5m["hour"] = df_5m.index.hour
    df_5m["min"] = df_5m.index.minute
    df_5m = df_5m[(df_5m["hour"] > 9) | ((df_5m["hour"] == 9) & (df_5m["min"] >= 30))]
    df_5m = df_5m[(df_5m["hour"] < 16) | ((df_5m["hour"] == 16) & (df_5m["min"] == 0))]

    if df_5m.empty:
        return {"success": False, "error": f"{tk} 常规交易时段 (09:30~16:00) 暂无分钟线"}

    df_5m["day"] = df_5m.index.strftime("%Y-%m-%d")
    available_days = sorted(df_5m["day"].unique().tolist())
    target_day = available_days[-1]  # Latest day (today)

    wave_engine = get_wave_engine()
    alpha_engine = get_alpha_engine()

    # Extract 7 microstructure features
    df_feat = wave_engine.build_microstructure_features(df_5m)
    X = df_feat[wave_engine.FEATURE_COLS].fillna(0.0)
    p_long_all = wave_engine.model.predict_proba(X)[:, 1]

    # Calculate EMA9, EMA21
    df_5m["ema_9"] = df_5m["Close"].ewm(span=9, adjust=False).mean()
    df_5m["ema_21"] = df_5m["Close"].ewm(span=21, adjust=False).mean()

    # Isolate target day
    idx_mask = (df_5m["day"] == target_day)
    day_df = df_5m[idx_mask].copy()
    if len(day_df) == 0:
        return {"success": False, "error": f"{tk} 当日无有效数据"}

    day_p_long = p_long_all[idx_mask]
    day_feat = df_feat[idx_mask]

    # Day cumulative VWAP
    pv = (day_df["Close"] * day_df["Volume"]).cumsum()
    v_cum = day_df["Volume"].cumsum().replace(0, 1.0)
    day_vwap = (pv / v_cum).round(2).tolist()

    times = day_df.index.strftime("%H:%M").tolist()
    day_records = day_df.to_dict(orient="records")
    kline = [
        [round(float(r["Open"]), 2), round(float(r["Close"]), 2), round(float(r["Low"]), 2), round(float(r["High"]), 2)]
        for r in day_records
    ]
    vols = [int(v) for v in day_df["Volume"].values]
    ema9_vals = [round(float(v), 2) for v in day_df["ema_9"].values]
    ema21_vals = [round(float(v), 2) for v in day_df["ema_21"].values]

    ofi = [round(float(v), 3) for v in day_feat["feature_ofi"].values]
    micro = [round(float(v), 2) for v in (
        day_feat["feature_micro_drift_bps"].values
        if "feature_micro_drift_bps" in day_feat.columns
        else day_feat["feature_micro_drift"].values * 100.0
    )]
    queue = [round(float(v), 3) for v in day_feat["feature_queue_imbalance"].values]
    sweep = [round(float(v), 3) for v in day_feat["feature_sweep_vel"].values]
    wave_p = [round(float(p) * 100, 1) for p in day_p_long]

    comp_scores = []
    signals = []
    last_sig_idx = -999
    last_sig_dir = None

    for i in range(len(day_records)):
        row = day_records[i]
        prev_row = day_records[i - 1] if i > 0 else None
        p_l = float(day_p_long[i])
        a_eval = alpha_engine.evaluate_composite_alpha(row, prev_row, ml_p_win_long=p_l)
        score = float(a_eval.get("composite_alpha_score", 0.0))
        comp_scores.append(round(score, 1))

        p_s = 1.0 - p_l
        cur_dir = None
        if score > 15 and p_l >= 0.54:
            cur_dir = "LONG"
        elif score < -15 and p_s >= 0.54:
            cur_dir = "SHORT"

        if cur_dir is not None:
            # Debounce: only record if direction flipped, or at least 5 bars (25 mins) passed
            if cur_dir != last_sig_dir or (i - last_sig_idx >= 5):
                price = float(row["Close"])
                low_val = float(row["Low"])
                high_val = float(row["High"])
                coord_y = low_val * 0.9985 if cur_dir == "LONG" else high_val * 1.0015
                signals.append({
                    "index": i,
                    "time": times[i],
                    "direction": cur_dir,
                    "coord_x": times[i],
                    "coord_y": round(coord_y, 2),
                    "price": round(price, 2),
                    "high": round(high_val, 2),
                    "low": round(low_val, 2),
                    "p_win": round(p_l * 100 if cur_dir == "LONG" else p_s * 100, 1),
                    "expected_ret": round((p_l - 0.5) * 1.8 if cur_dir == "LONG" else (p_s - 0.5) * 1.8, 2),
                    "ofi": ofi[i],
                    "micro_drift": micro[i],
                    "alpha": round(score, 1)
                })
                last_sig_idx = i
                last_sig_dir = cur_dir

    day_open = float(day_df["Open"].iloc[0])
    day_close = float(day_df["Close"].iloc[-1])
    day_pnl_pct = round(((day_close - day_open) / day_open) * 100, 2)

    now_ny = datetime.datetime.now(pytz.timezone("America/New_York"))

    return {
        "success": True,
        "ticker": tk,
        "date": target_day,
        "is_today": (target_day == now_ny.strftime("%Y-%m-%d")),
        "last_updated": now_ny.strftime("%H:%M:%S EDT"),
        "data": {
            "times": times,
            "kline": kline,
            "volume": vols,
            "ema9": ema9_vals,
            "ema21": ema21_vals,
            "vwap": day_vwap,
            "ofi": ofi,
            "micro_drift": micro,
            "queue_imb": queue,
            "sweep_vel": sweep,
            "wave_p_win_long": wave_p,
            "composite_alpha": comp_scores,
            "signals": signals,
            "stats": {
                "open": round(day_open, 2),
                "close": round(day_close, 2),
                "high": round(float(day_df["High"].max()), 2),
                "low": round(float(day_df["Low"].min()), 2),
                "pnl_pct": day_pnl_pct,
                "signal_count": len(signals)
            }
        }
    }
