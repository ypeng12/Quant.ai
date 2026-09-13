"""Quality measurements for retained Alpaca L1 quote and trade events."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .alpaca_l1_capture import load_real_l1_events
from .history import validate_symbol


def _percentile(values: pd.Series, percentile: float):
    values = pd.to_numeric(values, errors="coerce").dropna()
    return None if values.empty else float(np.percentile(values, percentile))


def _gap_stats(index: pd.DatetimeIndex) -> tuple[float | None, float | None]:
    gaps = index.to_series().diff().dt.total_seconds().dropna()
    return _percentile(gaps, 50), _percentile(gaps, 99)


def _latency_ms(frame: pd.DataFrame) -> pd.Series:
    if "received_at" not in frame:
        return pd.Series(dtype=float)
    received = pd.to_datetime(frame["received_at"], utc=True, errors="coerce")
    exchange = pd.Series(frame.index.tz_convert("UTC"), index=frame.index)
    return (received - exchange).dt.total_seconds().mul(1000).where(lambda value: value >= 0)


def audit_l1_capture(capture_dir: str | Path, symbols: list[str] | tuple[str, ...]) -> tuple[dict, pd.DataFrame]:
    """Return an aggregate summary and one measurement row per symbol/session.

    The function reports observed coverage and anomalies. It does not convert a
    short sample into a pass/fail claim about predictive Alpha.
    """
    root = Path(capture_dir)
    clean = tuple(dict.fromkeys(validate_symbol(symbol) for symbol in symbols))
    if not clean:
        raise ValueError("At least one symbol is required")

    rows: list[dict] = []
    missing: list[str] = []
    for symbol in clean:
        events = load_real_l1_events(root, symbol)
        if events.empty:
            missing.append(symbol)
            continue
        for session, frame in events.groupby(events.index.strftime("%Y-%m-%d"), sort=True):
            frame = frame.sort_index(kind="stable")
            regular = frame.between_time("09:30", "15:59:59.999999")
            quotes = regular.loc[regular.event_type.eq("quote")].copy()
            trades = regular.loc[regular.event_type.eq("trade")].copy()

            duplicate_subset = ["event_type"]
            for field in ("trade_id", "bid_price", "bid_size", "ask_price", "ask_size", "price", "size"):
                if field in regular:
                    duplicate_subset.append(field)
            duplicate_events = int(
                regular.reset_index(names="timestamp").duplicated(["timestamp", *duplicate_subset]).sum()
            )

            invalid_quotes = crossed_quotes = 0
            spread_bps = pd.Series(dtype=float)
            if not quotes.empty:
                numeric = quotes[["bid_price", "bid_size", "ask_price", "ask_size"]].apply(pd.to_numeric, errors="coerce")
                invalid = (~np.isfinite(numeric)).any(axis=1) | (numeric[["bid_price", "ask_price"]] <= 0).any(axis=1) | (numeric[["bid_size", "ask_size"]] < 0).any(axis=1)
                crossed = numeric.bid_price > numeric.ask_price
                invalid_quotes = int(invalid.sum())
                crossed_quotes = int(crossed.sum())
                midpoint = (numeric.bid_price + numeric.ask_price) / 2
                spread_bps = ((numeric.ask_price - numeric.bid_price) / midpoint * 10_000).where(~invalid & ~crossed)

            quote_gap_median, quote_gap_p99 = _gap_stats(quotes.index)
            trade_gap_median, trade_gap_p99 = _gap_stats(trades.index)
            latency = _latency_ms(regular)
            quote_minutes = int(quotes.index.floor("min").nunique()) if not quotes.empty else 0
            rows.append(
                {
                    "session": session,
                    "symbol": symbol,
                    "source": ",".join(sorted(regular.source.dropna().astype(str).unique())),
                    "feed": ",".join(sorted(regular.feed.dropna().astype(str).unique())),
                    "events": int(len(regular)),
                    "quotes": int(len(quotes)),
                    "trades": int(len(trades)),
                    "quote_trade_ratio": None if trades.empty else float(len(quotes) / len(trades)),
                    "quote_minutes": quote_minutes,
                    "quote_minute_coverage": float(quote_minutes / 390),
                    "duplicate_events": duplicate_events,
                    "invalid_quotes": invalid_quotes,
                    "crossed_quotes": crossed_quotes,
                    "spread_bps_median": _percentile(spread_bps, 50),
                    "spread_bps_p95": _percentile(spread_bps, 95),
                    "quote_gap_seconds_median": quote_gap_median,
                    "quote_gap_seconds_p99": quote_gap_p99,
                    "trade_gap_seconds_median": trade_gap_median,
                    "trade_gap_seconds_p99": trade_gap_p99,
                    "latency_ms_median": _percentile(latency, 50),
                    "latency_ms_p95": _percentile(latency, 95),
                    "first_event": None if regular.empty else regular.index[0].isoformat(),
                    "last_event": None if regular.empty else regular.index[-1].isoformat(),
                }
            )

    detail = pd.DataFrame(rows)
    summary = {
        "schema_version": 1,
        "status": "complete",
        "capture_dir": str(root),
        "requested_symbols": list(clean),
        "observed_symbols": [] if detail.empty else sorted(detail.symbol.unique().tolist()),
        "missing_symbols": missing,
        "sessions": [] if detail.empty else sorted(detail.session.unique().tolist()),
        "session_rows": int(len(detail)),
        "events": 0 if detail.empty else int(detail.events.sum()),
        "quotes": 0 if detail.empty else int(detail.quotes.sum()),
        "trades": 0 if detail.empty else int(detail.trades.sum()),
        "duplicate_events": 0 if detail.empty else int(detail.duplicate_events.sum()),
        "invalid_quotes": 0 if detail.empty else int(detail.invalid_quotes.sum()),
        "crossed_quotes": 0 if detail.empty else int(detail.crossed_quotes.sum()),
        "interpretation": "Data-quality measurements only; this report does not establish predictive Alpha or profitability.",
    }
    return summary, detail


def write_l1_quality_report(capture_dir: str | Path, symbols: list[str] | tuple[str, ...], output: str | Path) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    summary, detail = audit_l1_capture(capture_dir, symbols)
    detail.to_csv(output / "session_metrics.csv", index=False)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary
