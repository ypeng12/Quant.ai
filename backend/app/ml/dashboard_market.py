"""Dated, observed market history for dashboards. No synthetic prices or model metrics."""
from functools import lru_cache
from pathlib import Path
import json
import re

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=2)
def _load(path, modified):
    return json.loads(Path(path).read_text())


def market_data(ticker, date="", interval="5m", root=ROOT):
    symbol = str(ticker).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", symbol):
        raise ValueError("Invalid symbol")
    minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30}.get(interval)
    if minutes is None:
        raise ValueError("Unsupported dashboard timeframe")
    path = Path(root) / "backend/data/market_history/dashboard_bars.json"
    source = _load(str(path), path.stat().st_mtime_ns)
    records = source["bars"].get(symbol, {})
    dates = sorted(records, reverse=True)
    day = date or (dates[0] if dates else "")
    if day not in records:
        raise ValueError("Requested historical session is unavailable")
    raw = pd.DataFrame(records[day])
    raw.index = pd.to_datetime(raw.pop("t"), utc=True).dt.tz_convert("America/New_York")
    if raw.index.has_duplicates:
        raise ValueError("Duplicate observed bar timestamps")
    frame = raw.resample(f"{minutes}min").agg(dict(o="first", h="max", l="min", c="last", v="sum"))
    counts = raw.c.resample(f"{minutes}min").count()
    frame = frame.loc[counts == minutes].dropna()
    if frame.empty:
        raise ValueError("No complete bars for this timeframe")
    return dict(success=True, ticker=symbol, date=day, interval=interval, available_dates=dates,
                time=frame.index.strftime("%H:%M").tolist(), full_time=[x.isoformat() for x in frame.index],
                open=frame.o.tolist(), high=frame.h.tolist(), low=frame.l.tolist(),
                close=frame.c.tolist(), volume=frame.v.tolist(),
                data_provenance=dict(source=source["manifest"]["source"], adjustment="raw",
                                     is_live=False, timestamp_convention="bar_start",
                                     bar_count=len(frame), observed_one_minute_bars=len(raw),
                                     last_bar_end=(frame.index[-1] + pd.Timedelta(minutes=minutes)).isoformat()))


def observed_snapshot(ticker, root=ROOT):
    data = market_data(ticker, root=root)
    closes = pd.Series(data["close"], dtype=float)
    volume = pd.Series(data["volume"], dtype=float)
    typical = (pd.Series(data["high"]) + pd.Series(data["low"]) + closes) / 3
    vwap = float((typical * volume).sum() / volume.sum()) if volume.sum() > 0 else None
    observed = dict(date=data["date"], bar_count=len(closes), close=float(closes.iloc[-1]),
                    open=data["open"][0], high=max(data["high"]), low=min(data["low"]),
                    volume=float(volume.sum()), vwap=vwap,
                    day_return_pct=float((closes.iloc[-1] / data["open"][0] - 1) * 100),
                    last_return_bps=float((closes.iloc[-1] / closes.iloc[-2] - 1) * 10000),
                    volatility_bps=float(closes.pct_change().dropna().std() * 10000),
                    up_bar_fraction=float((closes.diff().dropna() > 0).mean()),
                    vwap_distance_bps=float((closes.iloc[-1] / vwap - 1) * 10000) if vwap else None)
    return dict(success=True, status="market_data_only", ticker=data["ticker"], result=None,
                observed=observed, data_provenance={**data["data_provenance"],
                "label": f"{data['date']} · 历史 SIP 行情 · 模型指标待验证"},
                unavailable_metrics=["calibrated_win_rate", "brier_score", "rank_score", "hmm_probabilities",
                                     "expected_return", "kelly_fraction", "sor_fill_probability", "feature_importance"])


def archived_fills(ticker, date, root=ROOT):
    """Return broker-confirmed fill facts without inventing lot matches or PnL."""
    symbol = str(ticker).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", symbol):
        raise ValueError("Invalid symbol")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
        raise ValueError("Explicit historical date required")
    path = Path(root) / f"backend/data/datasets/daily_archives/trades_{date}.json"
    if not path.exists():
        return dict(success=True, ticker=symbol, date=date, fills=[],
                    data_provenance=dict(source="broker_archive_missing", is_live=False))
    payload = json.loads(path.read_text())
    rows = payload.get("trade_history", []) if isinstance(payload, dict) else payload
    fills = []
    for row in rows if isinstance(rows, list) else []:
        if str(row.get("ticker", "")).upper() != symbol or str(row.get("order_status", "")).lower() != "filled":
            continue
        try:
            quantity, price = float(row["shares"]), float(row["price"])
        except (KeyError, TypeError, ValueError):
            continue
        fills.append(dict(time=str(row.get("time", "")), action=str(row.get("action", "")).upper(),
                          shares=quantity, price=price, source=str(row.get("source", "broker_archive"))))
    return dict(success=True, ticker=symbol, date=date, fills=fills,
                data_provenance=dict(source="alpaca_filled_order_archive", is_live=False,
                                     pnl_verified=False, lot_matching=False))
