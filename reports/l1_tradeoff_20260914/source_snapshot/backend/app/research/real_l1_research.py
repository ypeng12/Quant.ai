"""Build research-only L1 artifacts from retained Alpaca files, without orders."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import exchange_calendars as xcals

from ..alpha.l1_ridge import L1Ridge
from ..alpha.l1_state_models import QueueImbalanceModel, TransitionMicroprice, _cutoff
from ..alpha.paper_l1_alpha import VERSION, observed_events
from ..market_data.alpaca_l1_capture import load_real_l1_events
from ..market_data.history import validate_symbol

DEFAULT_HORIZONS = ("1s", "5s", "30s", "1min", "5min")


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def run_real_l1_research(inputs, symbols, output, *, before=None, session_dates=None, regular_session=True, horizons=DEFAULT_HORIZONS,
                         tolerance="1s", max_gap="30s", ridge_alpha=10.0,
                         logistic_c=1.0, tick_size=.01, imbalance_bins=5,
                         spread_ticks=None, spread_bins=5, price_changes=6):
    """Train only: future evaluation and trading PnL are deliberately absent.

    Separate quote/trade roots can be supplied. Sources and feeds are always
    fitted independently: a historical SIP model cannot silently become an
    arrival-clock IEX model. No files are overwritten.
    """
    roots = list(dict.fromkeys(Path(root).resolve() for root in inputs))
    symbols = list(dict.fromkeys(validate_symbol(symbol) for symbol in symbols))
    if not roots or not symbols:
        raise ValueError("At least one input root and symbol are required")
    cutoff = None if before is None else _cutoff(before)
    if session_dates is not None:
        session_dates = sorted(set(str(date) for date in session_dates))
        if not session_dates or any(pd.Timestamp(date).strftime("%Y-%m-%d") != date for date in session_dates):
            raise ValueError("sessions must contain explicit YYYY-MM-DD dates")
    horizons = list(dict.fromkeys(horizons))
    if not horizons or any(pd.Timedelta(horizon) <= pd.Timedelta(0) for horizon in horizons):
        raise ValueError("Positive prediction horizons are required")
    if pd.Timedelta(tolerance) < pd.Timedelta(0) or pd.Timedelta(max_gap) <= pd.Timedelta(0):
        raise ValueError("Nonnegative tolerance and positive max_gap required")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    registry = dict(
        schema_version=1, task="real_l1_train_only", feature_version=VERSION,
        created_at=pd.Timestamp.now(tz="UTC").isoformat(), inputs=[str(root) for root in roots],
        requested_symbols=symbols, requested_before=None if cutoff is None else cutoff.isoformat(),
        requested_sessions=session_dates, sampling="none; all retained events within requested sessions",
        session_filter="XNYS official session open <= observation_time < official close" if regular_session else "all retained hours",
        status="unavailable", deployment="research_only", performance_verified=False,
        selected_for_live=None, models=[], datasets=[], source_files=[], input_errors=[],
        unverified_assumptions=[
            "Model parameters have not been evaluated on held-out or future sessions.",
            "Future-mid returns are not executable returns or cost-adjusted PnL.",
            "Historical exchange timestamps do not verify actual arrival latency.",
            "IEX top-of-book is one venue's L1; it is not consolidated SIP or L2/L3.",
            "Transition-model spread bins are learned only before the training cutoff; optional exact-tick states remain configurable.",
            "An IEX microprice is a venue-mid estimate, not an executable NBBO opportunity.",
        ],
        parameters=dict(horizons=horizons, tolerance=tolerance, max_gap=max_gap,
                        ridge_alpha=ridge_alpha, logistic_c=logistic_c, tick_size=tick_size,
                        imbalance_bins=imbalance_bins, spread_ticks=None if spread_ticks is None else list(spread_ticks),
                        spread_bins=spread_bins, price_changes=price_changes),
    )
    sessions = []
    names = ["qi_logistic", "transition_microprice"] + [f"ofi_ridge_{horizon}" for horizon in horizons]

    def unavailable(symbol, reason, *, source=None, feed=None):
        registry["models"].extend(dict(symbol=symbol, source=source, feed=feed, model=name,
                                       status="unavailable", reason=reason,
                                       performance_verified=False) for name in names)

    for symbol in symbols:
        frames = []
        input_failed = False
        seen_paths = set()
        seen_content = set()
        for root in roots:
            files = (sorted(root.glob(f"*/{symbol}.jsonl")) if session_dates is None else
                     [root / date / f"{symbol}.jsonl" for date in session_dates if (root / date / f"{symbol}.jsonl").is_file()])
            if any(path.resolve() in seen_paths for path in files):
                raise ValueError("Overlapping input roots would count the same event file twice")
            seen_paths.update(path.resolve() for path in files)
            try:
                fingerprints = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in files}
                if session_dates is None:
                    frame = load_real_l1_events(root, symbol)
                else:
                    session_frames = [load_real_l1_events(root, symbol, date) for date in session_dates]
                    nonempty = [frame for frame in session_frames if not frame.empty]
                    frame = pd.concat(nonempty).sort_index(kind="stable") if nonempty else pd.DataFrame()
                for path in files:
                    sha256 = digest(path)
                    if (path.stat().st_size, path.stat().st_mtime_ns) != fingerprints[path]:
                        raise ValueError("Input changed during training-data read; use a completed capture snapshot")
                    if path.stat().st_size and sha256 in seen_content:
                        raise ValueError("Duplicate event file contents across inputs would double-count observations")
                    if path.stat().st_size:
                        seen_content.add(sha256)
                    registry["source_files"].append(dict(path=str(path), bytes=path.stat().st_size, sha256=sha256))
                if not frame.empty:
                    frames.append(frame)
            except (ValueError, OSError, KeyError) as error:
                input_failed = True
                registry["input_errors"].append(dict(symbol=symbol, input=str(root), reason=str(error)))
        if input_failed:
            unavailable(symbol, "Input integrity/format failure; see input_errors")
            continue
        if not frames:
            unavailable(symbol, "No retained real L1 events; no proxy events or synthetic training data generated")
            continue
        raw = pd.concat(frames).sort_index(kind="stable")
        if not {"source", "feed"}.issubset(raw) or raw[["source", "feed"]].isna().any().any():
            unavailable(symbol, "Every event needs an explicit source and feed")
            continue
        for (source, feed), events in raw.groupby(["source", "feed"], sort=True):
            try:
                excluded_out_of_session = 0
                if regular_session:
                    if source == "alpaca_stock_websocket":
                        if "received_at" not in events:
                            raise ValueError("WebSocket events require recorded received_at")
                        clock_index = pd.DatetimeIndex(pd.to_datetime(events.received_at, utc=True, errors="coerce", format="mixed"))
                        if clock_index.hasnans:
                            raise ValueError("Invalid received_at")
                        clock_index = clock_index.tz_convert("America/New_York")
                    else:
                        clock_index = events.index.tz_convert("America/New_York")
                    calendar = xcals.get_calendar("XNYS")
                    included = np.zeros(len(clock_index), dtype=bool)
                    for session_date in sorted(set(clock_index.strftime("%Y-%m-%d"))):
                        if calendar.is_session(session_date):
                            included |= ((clock_index >= calendar.session_open(session_date)) &
                                         (clock_index < calendar.session_close(session_date)))
                    positions = np.flatnonzero(included)
                    excluded_out_of_session = len(events) - len(positions)
                    events = events.iloc[positions]
                observed = observed_events(events, as_of=cutoff)
                if observed.empty:
                    raise ValueError("No observed events before the requested cutoff")
                train_before = cutoff if cutoff is not None else observed.index.max() + pd.Timedelta("1ns")
                observed_sessions = sorted(set(observed.index.strftime("%Y-%m-%d")))
                book = observed.loc[observed.event_type.eq("quote"), ["bid_price", "ask_price"]].astype(float)
                spread = book.ask_price-book.bid_price
                spread_bps = spread/((book.ask_price+book.bid_price)/2)*10000
                spread_statistics = dict(
                    dollars_median=float(spread.median()), dollars_p95=float(spread.quantile(.95)),
                    bps_median=float(spread_bps.median()), bps_p95=float(spread_bps.quantile(.95)),
                    interpretation="Observed feed quote spread, not calibrated execution cost or consolidated NBBO",
                )
                registry["datasets"].append(dict(
                    symbol=symbol, source=source, feed=feed, events=len(observed),
                    quotes=int(observed.event_type.eq("quote").sum()), trades=int(observed.event_type.eq("trade").sum()),
                    sessions=observed_sessions, first_event=observed.index.min().isoformat(),
                    last_event=observed.index.max().isoformat(), trained_before=train_before.isoformat(),
                    clock=observed.attrs["clock"], late_events_excluded=observed.attrs["late_events_excluded"],
                    out_of_session_events_excluded=excluded_out_of_session,
                    observed_quote_spread=spread_statistics,
                ))
                for date, frame in observed.groupby(observed.index.strftime("%Y-%m-%d")):
                    sessions.append(dict(symbol=symbol, source=source, feed=feed, session=date,
                                         events=len(frame), quotes=int(frame.event_type.eq("quote").sum()),
                                         trades=int(frame.event_type.eq("trade").sum()),
                                         first_event=frame.index.min().isoformat(), last_event=frame.index.max().isoformat()))
            except (ValueError, KeyError) as error:
                unavailable(symbol, str(error), source=source, feed=feed)
                continue
            models_dir = output / "models" / f"{symbol}_{feed}_{source}"
            models_dir.mkdir(parents=True)
            builders = [
                ("qi_logistic", lambda: QueueImbalanceModel().fit(events, before=train_before, C=logistic_c, max_gap=max_gap)),
                ("transition_microprice", lambda: TransitionMicroprice().fit(
                    events, before=train_before, tick_size=tick_size, imbalance_bins=imbalance_bins,
                    spread_ticks=None if spread_ticks is None else tuple(spread_ticks), spread_bins=spread_bins,
                    price_changes=price_changes, max_gap=max_gap)),
            ]
            builders.extend((f"ofi_ridge_{horizon}", lambda h=horizon: L1Ridge().fit(
                events, before=train_before, horizon=h, tolerance=tolerance, alpha=ridge_alpha, max_gap=max_gap))
                for horizon in horizons)
            for name, build in builders:
                entry = dict(symbol=symbol, source=source, feed=feed, model=name, performance_verified=False)
                try:
                    model = build()
                    model.artifact.update(session_filter=registry["session_filter"], target_feed=feed)
                    path = models_dir / f"{name}.json"
                    model.save(path)
                    entry.update(status="trained_unvalidated", path=str(path.relative_to(output)),
                                 sha256=digest(path), trained_before=model.artifact["trained_before"],
                                 last_label_end=model.artifact["last_label_end"], rows=model.artifact["rows"],
                                 target_feed=feed, session_filter=registry["session_filter"])
                except (ValueError, np.linalg.LinAlgError) as error:
                    entry.update(status="unavailable", reason=str(error))
                registry["models"].append(entry)
    trained = sum(item["status"] == "trained_unvalidated" for item in registry["models"])
    registry["trained_models"] = trained
    registry["unavailable_models"] = len(registry["models"]) - trained
    registry["status"] = "complete" if trained == len(registry["models"]) else "partial" if trained else "unavailable"
    if registry["input_errors"]:
        registry["status"] = "invalid"
    detail = pd.DataFrame(sessions, columns=["symbol", "source", "feed", "session", "events", "quotes", "trades", "first_event", "last_event"])
    detail.to_csv(output / "sessions.csv", index=False)
    (output / "registry.json").write_text(json.dumps(registry, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    (output / "registry.sha256").write_text(digest(output / "registry.json") + "\n")
    lines = ["# Real L1 research training", "", f"Status: {registry['status']}",
             f"Trained, unvalidated models: {trained}; unavailable: {registry['unavailable_models']}", "",
             "No trading orders, validation accuracy, or profit are produced by this training run.", "",
             "See registry.json for source hashes, clocks, model contracts and individual reasons.", "",
             "## Unverified assumptions", ""]
    lines.extend(f"- {item}" for item in registry["unverified_assumptions"])
    (output / "REPORT.md").write_text("\n".join(lines) + "\n")
    return registry
