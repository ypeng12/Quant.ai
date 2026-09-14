"""Quality measurements for retained Alpaca L1 quote and trade events.

Coverage means observed event minutes, not lossless capture or predictive power.
Files are verified incrementally and loaded one symbol/session at a time.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from .history import validate_symbol


_LEGACY_COLUMNS = [
    "session", "symbol", "source", "feed", "events", "quotes", "trades",
    "quote_trade_ratio", "quote_minutes", "quote_minute_coverage",
    "duplicate_events", "invalid_quotes", "crossed_quotes", "spread_bps_median",
    "spread_bps_p95", "quote_gap_seconds_median", "quote_gap_seconds_p99",
    "trade_gap_seconds_median", "trade_gap_seconds_p99", "latency_ms_median",
    "latency_ms_p95", "first_event", "last_event", "observed_delay_samples",
    "negative_observed_delay_events", "negative_observed_delay_fraction",
]


def _percentile(values: pd.Series, percentile: float):
    values = pd.to_numeric(values, errors="coerce").dropna()
    return None if values.empty else float(np.percentile(values, percentile))


def _gap_stats(index: pd.DatetimeIndex) -> tuple[float | None, float | None]:
    gaps = index.to_series().diff().dt.total_seconds().dropna()
    return _percentile(gaps, 50), _percentile(gaps, 99)


def _latency_ms(frame: pd.DataFrame) -> pd.Series:
    """Unadjusted host-observed minus exchange time, not network latency.

    Negative differences are evidence of clock misalignment or inconsistent
    timestamps. Excluding them would bias the reported distribution upward
    and hide the clock problem; retain them exactly as observed.
    """
    if "received_at" not in frame:
        return pd.Series(dtype=float)
    received = pd.to_datetime(frame["received_at"], utc=True, errors="coerce", format="mixed")
    exchange = pd.Series(frame.index.tz_convert("UTC"), index=frame.index)
    return (received - exchange).dt.total_seconds().mul(1000)


def _manifest(root: Path) -> dict:
    path = root / "manifest.json"
    if not path.exists():
        return {}
    manifest = json.loads(path.read_text())
    if manifest.get("status") != "complete":
        raise ValueError("Historical capture is incomplete")
    entries = manifest.get("normalized_files", [])
    if not entries and any(root.glob("*/*.jsonl")):
        raise ValueError("Historical capture has no verified normalized files")
    verified = set()
    for entry in entries:
        event_path = (root / entry["path"]).resolve()
        if not event_path.is_relative_to(root.resolve()) or not event_path.is_file():
            raise ValueError("Historical normalized data integrity check failed")
        digest = hashlib.sha256()
        with event_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != entry["sha256"]:
            raise ValueError("Historical normalized data integrity check failed")
        verified.add(event_path)
    manifest["_verified_paths"] = verified
    return manifest


def _load_session(path: Path, symbol: str, session: str) -> tuple[pd.DataFrame, int]:
    """Bound materialization to one symbol/date; never read ten days at once."""
    rows = []
    rejected = 0
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                if (event.get("schema_version") != 1
                        or event.get("event_type") not in {"quote", "trade"}
                        or event.get("source") not in {"alpaca_stock_websocket", "alpaca_stock_historical"}
                        or event.get("symbol") != symbol
                        or event.get("feed") not in {"iex", "sip"}
                        or event.get("market_depth") != ("L1" if event.get("event_type") == "quote" else "trade_print")):
                    rejected += 1
                    continue
                stamp = pd.Timestamp(event.get("timestamp"))
                if pd.isna(stamp) or stamp.tzinfo is None:
                    raise ValueError("Event file has missing or timezone-naive timestamp")
                stamp = stamp.tz_convert("America/New_York")
                if str(stamp.date()) != session:
                    raise ValueError("Event timestamp does not match the session directory")
                event["timestamp"] = stamp
                rows.append(event)
    if not rows:
        return pd.DataFrame(columns=["event_type", "source", "feed"],
                            index=pd.DatetimeIndex([], tz="America/New_York")), rejected
    frame = pd.DataFrame(rows).set_index("timestamp").sort_index(kind="stable")
    return frame, rejected


def _boundary(value, name: str) -> pd.Timestamp | None:
    if value is None:
        return None
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    return stamp.tz_convert("America/New_York")


def audit_l1_capture(
    capture_dir: str | Path,
    symbols: list[str] | tuple[str, ...],
    *,
    start=None,
    end=None,
    expected_event_types: tuple[str, ...] | list[str] | None = None,
) -> tuple[dict, pd.DataFrame]:
    """Measure actual coverage against XNYS sessions, including early closes.

    ``start``/``end`` define an inclusive/exclusive sampling interval and must
    include a timezone. Historical manifest bounds are used by default. Without
    either, the report covers the first through last retained directory dates;
    it cannot infer days before or after that range. A quotes-only historical
    manifest expects quotes only: absent trades are reported, not called a
    collector failure. Full-minute coverage is a descriptive count, not a
    declaration that every exchange event was retained or enough data exists
    to train a profitable model.
    """
    root = Path(capture_dir)
    clean = tuple(dict.fromkeys(validate_symbol(symbol) for symbol in symbols))
    if not clean:
        raise ValueError("At least one symbol is required")
    manifest = _manifest(root)
    if expected_event_types is None:
        expected_event_types = {"quotes": ("quote",), "trades": ("trade",)}.get(
            manifest.get("kind"), ("quote", "trade"))
    expected_types = tuple(dict.fromkeys(expected_event_types))
    if not expected_types or not set(expected_types).issubset({"quote", "trade"}):
        raise ValueError("expected_event_types must contain quote and/or trade")
    start = _boundary(start if start is not None else manifest.get("start"), "start")
    end = _boundary(end if end is not None else manifest.get("end"), "end")
    if start is not None and end is not None and start >= end:
        raise ValueError("start must precede end")

    paths = {(path.parent.name, symbol): path for symbol in clean for path in sorted(root.glob(f"*/{symbol}.jsonl"))}
    if manifest:
        if any(path.resolve() not in manifest["_verified_paths"] for path in paths.values()):
            raise ValueError("Historical event file is not listed in the verified manifest")
    dates = sorted({session for session, _ in paths})
    # Directory dates are part of the recorder's storage contract.
    for day in dates:
        if pd.Timestamp(day).strftime("%Y-%m-%d") != day:
            raise ValueError("Invalid session directory date")
    lower = start.date().isoformat() if start is not None else (dates[0] if dates else None)
    upper = (end - pd.Timedelta(nanoseconds=1)).date().isoformat() if end is not None else (dates[-1] if dates else None)
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("Sampling interval does not overlap the retained date range")
    schedule = {}
    if lower is not None and upper is not None:
        calendar = xcals.get_calendar("XNYS", start=pd.Timestamp(lower) - pd.Timedelta(days=7),
                                     end=pd.Timestamp(upper) + pd.Timedelta(days=7))
        for day in calendar.sessions_in_range(lower, upper):
            opened = calendar.session_open(day).tz_convert("America/New_York")
            closed = calendar.session_close(day).tz_convert("America/New_York")
            window_open = max(opened, start) if start is not None else opened
            window_close = min(closed, end) if end is not None else closed
            if window_open < window_close:
                schedule[str(day.date())] = (opened, closed, window_open, window_close)

    rows = []
    rejected_events = outside_session_events = 0
    # Include exchange sessions with no file so missing whole days stay visible.
    audit_dates = sorted(set(schedule) | {day for day in dates if (lower is None or day >= lower) and (upper is None or day <= upper)})
    for session in audit_dates:
        for symbol in clean:
            path = paths.get((session, symbol), root / session / f"{symbol}.jsonl")
            frame, rejected = _load_session(path, symbol, session)
            rejected_events += rejected
            if start is not None:
                frame = frame.loc[frame.index >= start]
            if end is not None:
                frame = frame.loc[frame.index < end]
            if session not in schedule:
                outside_session_events += len(frame)
                continue
            opened, closed, window_open, window_close = schedule[session]
            regular = frame.loc[(frame.index >= window_open) & (frame.index < window_close)]
            outside_session_events += len(frame) - len(regular)
            quotes = regular.loc[regular.event_type.eq("quote")].copy()
            trades = regular.loc[regular.event_type.eq("trade")].copy()
            duplicate_subset = ["event_type", "source", "feed"]
            for field in ("trade_id", "bid_price", "bid_size", "ask_price", "ask_size", "price", "size"):
                if field in regular:
                    duplicate_subset.append(field)
            duplicates = regular.reset_index(names="timestamp").duplicated(["timestamp", *duplicate_subset])
            invalid_quotes = crossed_quotes = invalid_trades = 0
            spread_bps = pd.Series(dtype=float)
            if not quotes.empty:
                numeric = quotes.reindex(columns=["bid_price", "bid_size", "ask_price", "ask_size"]).apply(pd.to_numeric, errors="coerce")
                invalid = (~np.isfinite(numeric)).any(axis=1) | (numeric[["bid_price", "ask_price"]] <= 0).any(axis=1) | (numeric[["bid_size", "ask_size"]] < 0).any(axis=1)
                crossed = numeric.bid_price > numeric.ask_price
                invalid_quotes, crossed_quotes = int(invalid.sum()), int(crossed.sum())
                midpoint = (numeric.bid_price + numeric.ask_price) / 2
                spread_bps = ((numeric.ask_price - numeric.bid_price) / midpoint * 10_000).where(~invalid & ~crossed)
            if not trades.empty:
                numeric = trades.reindex(columns=["price", "size"]).apply(pd.to_numeric, errors="coerce")
                invalid_trades = int(((~np.isfinite(numeric)).any(axis=1) | (numeric <= 0).any(axis=1)).sum())
            quote_gap_median, quote_gap_p99 = _gap_stats(quotes.index)
            trade_gap_median, trade_gap_p99 = _gap_stats(trades.index)
            latency = _latency_ms(regular)
            quote_minutes, trade_minutes = (int(events.index.floor("min").nunique()) for events in (quotes, trades))
            expected_minutes = int((closed - opened) / pd.Timedelta(minutes=1))
            # Count minute buckets intersecting the requested sampling interval.
            window_minutes = len(pd.date_range(window_open.floor("min"), window_close.ceil("min"), freq="min", inclusive="left"))
            full_window = window_open == opened and window_close == closed
            rows.append({
                "session": session, "symbol": symbol,
                "source": ",".join(sorted(regular.source.dropna().astype(str).unique())),
                "feed": ",".join(sorted(regular.feed.dropna().astype(str).unique())),
                "events": int(len(regular)), "quotes": int(len(quotes)), "trades": int(len(trades)),
                "quote_trade_ratio": None if trades.empty else float(len(quotes) / len(trades)),
                "quote_minutes": quote_minutes, "quote_minute_coverage": quote_minutes / expected_minutes,
                "duplicate_events": int(duplicates.sum()), "invalid_quotes": invalid_quotes,
                "crossed_quotes": crossed_quotes, "spread_bps_median": _percentile(spread_bps, 50),
                "spread_bps_p95": _percentile(spread_bps, 95),
                "quote_gap_seconds_median": quote_gap_median, "quote_gap_seconds_p99": quote_gap_p99,
                "trade_gap_seconds_median": trade_gap_median, "trade_gap_seconds_p99": trade_gap_p99,
                "latency_ms_median": _percentile(latency, 50), "latency_ms_p95": _percentile(latency, 95),
                "observed_delay_samples": int(latency.notna().sum()),
                "negative_observed_delay_events": int(latency.lt(0).sum()),
                "negative_observed_delay_fraction": None if not latency.notna().any() else float(latency.lt(0).sum()/latency.notna().sum()),
                "first_event": None if regular.empty else regular.index[0].isoformat(),
                "last_event": None if regular.empty else regular.index[-1].isoformat(),
                "session_open": opened.isoformat(), "session_close": closed.isoformat(),
                "expected_session_minutes": expected_minutes,
                "sampling_window_start": window_open.isoformat(), "sampling_window_end": window_close.isoformat(),
                "sampling_window_minutes": window_minutes, "sampling_window_is_full_session": full_window,
                "quote_window_minute_coverage": quote_minutes / window_minutes,
                "trade_minutes": trade_minutes, "trade_minute_coverage": trade_minutes / expected_minutes,
                "trade_window_minute_coverage": trade_minutes / window_minutes,
                "full_quote_minute_coverage": full_window and quote_minutes == expected_minutes,
                "full_trade_minute_coverage": full_window and trade_minutes == expected_minutes,
                "missing_quotes": quotes.empty, "missing_trades": trades.empty,
                "invalid_trades": invalid_trades,
            })

    detail = pd.DataFrame(rows) if rows else pd.DataFrame(columns=_LEGACY_COLUMNS)
    total = lambda name: 0 if detail.empty else int(detail[name].sum())
    missing = lambda field: [symbol for symbol in clean if detail.empty or int(detail.loc[detail.symbol.eq(symbol), field].sum()) == 0]
    full = {symbol: {event: ([] if detail.empty else detail.loc[detail.symbol.eq(symbol) & detail[f"full_{event}_minute_coverage"], "session"].tolist())
                     for event in ("quote", "trade")} for symbol in clean}
    common = sorted(set.intersection(*(set(full[symbol][event]) for symbol in clean for event in expected_types)))
    expected_sessions = sorted(schedule)
    summary = {
        "schema_version": 3,
        "status": "unavailable" if total("events") == 0 else ("complete" if len(common) == len(expected_sessions) else "partial"),
        "capture_dir": str(root), "requested_symbols": list(clean),
        "observed_symbols": [] if detail.empty else sorted(detail.loc[detail.events.gt(0), "symbol"].unique().tolist()),
        "missing_symbols": missing("events"), "missing_quote_symbols": missing("quotes"), "missing_trade_symbols": missing("trades"),
        "sessions": [] if detail.empty else sorted(detail.loc[detail.events.gt(0), "session"].unique().tolist()),
        "expected_sessions": expected_sessions, "expected_session_count": len(expected_sessions),
        "session_rows": int(len(detail)), "events": total("events"), "quotes": total("quotes"), "trades": total("trades"),
        "duplicate_events": total("duplicate_events"), "invalid_quotes": total("invalid_quotes"),
        "crossed_quotes": total("crossed_quotes"), "invalid_trades": total("invalid_trades"),
        "rejected_events": rejected_events, "outside_regular_session_events": outside_session_events,
        "calendar": "XNYS", "calendar_source": f"exchange_calendars {xcals.__version__}",
        "expected_event_types": list(expected_types),
        "sampling_start": None if start is None else start.isoformat(), "sampling_end_exclusive": None if end is None else end.isoformat(),
        "sampling_bounds_source": "explicit_or_historical_manifest" if start is not None or end is not None else "retained_directory_date_range",
        "full_minute_coverage_sessions_by_symbol": full,
        "common_full_minute_coverage_sessions": common, "common_full_minute_coverage_session_count": len(common),
        "performance_verified": False,
        "observed_delay_samples": total("observed_delay_samples"),
        "negative_observed_delay_events": total("negative_observed_delay_events"),
        "clock_alignment_verified": False,
        "timing_interpretation": "Legacy latency_ms fields retain unadjusted host-observed time minus exchange time, including negative values. SDK callback observation is not verified network/socket arrival. Neither positive nor negative differences independently measure network latency; clock offset and local processing delay are separate. No timestamps are shifted or clipped.",
        "coverage_interpretation": "Full coverage means at least one observed event in each exchange-session minute for each required event type. It does not establish lossless capture; sparse IEX activity can produce empty minutes without a capture failure. Quotes-only/trades-only downloads expect only their declared event type. Sessions outside the sampling bounds are not inferred.",
        "interpretation": "Data-quality measurements only; no number of captured sessions establishes predictive Alpha or profitability. Validate future returns and executable costs separately.",
        "memory_scope": "one_symbol_session; integrity hashes are streamed",
    }
    return summary, detail


def write_l1_quality_report(capture_dir: str | Path, symbols: list[str] | tuple[str, ...], output: str | Path, **audit_options) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    summary, detail = audit_l1_capture(capture_dir, symbols, **audit_options)
    detail.to_csv(output / "session_metrics.csv", index=False)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary
