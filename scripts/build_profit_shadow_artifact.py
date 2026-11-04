#!/usr/bin/env python3
"""Build a dated, read-only comparison model from prior five-minute bars.

Example (no trading API is imported or called)::

    python scripts/build_profit_shadow_artifact.py --session 2026-11-04 \
        --fetch-alpaca --output .local_backups/shadow-20261104

An existing archive can instead supply NVDA/SNDK/TSLA/MSTR CSV files with an
aware ``timestamp`` column, or Parquet files with an aware DatetimeIndex.
The output directory must be new. Refreshing a running model is a separate,
explicit deployment operation; this command never changes the active policy.
Tomorrow's artifact can be prepared after today's complete regular session.
Market-data requests respect a 15-minute delay and exclude unfinished bars.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.quant_policy import NY, normalize_bars
from app.research.profit_signal_candidates import CANDIDATES, REFRESH_CANDIDATES, INPUT_SYMBOLS
from app.research.profit_signal_shadow import ProfitSignalShadowModel

ENDPOINT = "https://data.alpaca.markets/v2/stocks/bars"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def session_cutoff(session):
    parsed = date.fromisoformat(session)
    if parsed.isoformat() != session:
        raise ValueError("Session must be exactly YYYY-MM-DD")
    return pd.Timestamp(session, tz=NY)


def prior_bars(raw, cutoff):
    if not isinstance(raw.index, pd.DatetimeIndex) or raw.index.tz is None:
        raise ValueError("Source timestamps must explicitly include a timezone")
    # Exclude unavailable observations before checking prices or fitting.
    return normalize_bars(raw.loc[raw.index < cutoff])


def load_archive(directory, cutoff):
    directory = Path(directory)
    frames, sources = {}, {}
    for symbol in INPUT_SYMBOLS:
        choices = [directory / f"{symbol}.csv", directory / f"{symbol}.parquet"]
        found = [p for p in choices if p.is_file()]
        if len(found) != 1:
            raise ValueError(f"Exactly one CSV or Parquet input required for {symbol}")
        path = found[0]
        if path.suffix == ".csv":
            raw = pd.read_csv(path)
            if "timestamp" not in raw:
                raise ValueError("CSV inputs require a timestamp column")
            timestamps = raw.pop("timestamp")
            # utc=True must not silently invent a timezone for naive source rows.
            if any(pd.Timestamp(t).tzinfo is None for t in timestamps):
                raise ValueError("CSV source timestamps must explicitly include a timezone")
            raw.index = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True))
        else:
            raw = pd.read_parquet(path)
        frames[symbol] = prior_bars(raw, cutoff)
        sources[symbol] = {"filename": path.name, "sha256": digest(path)}
    source = {"kind": "existing_archive", "read_at": utc_now(), "files": sources,
              "historical_receipt_verified": False}
    manifest = directory / "source_manifest.json"
    if manifest.is_file():
        source["additional_source_manifest"] = {"filename": manifest.name, "sha256": digest(manifest),
                                                "contents_independently_verified": False}
    return frames, source


def fetch_alpaca(cutoff, destination, *, feed="sip", calendar_days=100,
                 env_file=ROOT / "backend/.env", client=None):
    """GET market data only, retaining real receipt times and full pagination."""
    from dotenv import dotenv_values
    import requests

    if calendar_days < 1:
        raise ValueError("A positive calendar-day lookback is required")
    values = {**dotenv_values(env_file), **os.environ}
    key, secret = values.get("ALPACA_API_KEY"), values.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise ValueError("Alpaca market-data credentials are not configured")
    session = client if client is not None else requests.Session()
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    # Historical SIP credentials may require a 15-minute delay. Also exclude
    # every unfinished five-minute bar, including next-session builds.
    available_before = min(cutoff, (pd.Timestamp(utc_now()) - pd.Timedelta(minutes=15)).floor("5min"))
    params = {"symbols": ",".join(INPUT_SYMBOLS), "timeframe": "5Min",
              "start": (cutoff - pd.DateOffset(days=calendar_days)).tz_convert("UTC").isoformat(),
              "end": (available_before - pd.Timedelta(minutes=5)).tz_convert("UTC").isoformat(),
              "feed": feed, "adjustment": "raw", "sort": "asc", "limit": 10000,
              "asof": "-"}
    # No credentials, headers, account identifiers, or local paths enter receipts.
    capture = {"kind": "fresh_alpaca_historical_bars", "endpoint": ENDPOINT,
               "request": dict(params), "started_at": utc_now(), "pages": [],
               "complete_bars_before": available_before.isoformat(), "completed": False,
               "historical_receipt_verified": False,
               "interpretation": "Captured now; not evidence of receipt at historical bar time."}
    rows, seen_tokens = {s: [] for s in INPUT_SYMBOLS}, set()
    try:
        while True:
            response = session.get(ENDPOINT, params=params, headers=headers, timeout=45)
            received = utc_now()
            if response.status_code != 200:
                raise RuntimeError(f"Market-data GET returned HTTP {response.status_code}")
            raw = response.content
            payload = response.json()
            page = f"alpaca_bars_{len(capture['pages']):03d}.json"
            (Path(destination) / page).write_bytes(raw)
            capture["pages"].append({"file": page, "received_at": received,
                                     "sha256": hashlib.sha256(raw).hexdigest()})
            bars = payload.get("bars")
            if not isinstance(bars, dict) or not set(bars) <= set(INPUT_SYMBOLS):
                raise ValueError("Unexpected market-data response symbol schema")
            for symbol, values in bars.items():
                rows[symbol].extend(values)
            token = payload.get("next_page_token")
            if not token:
                break
            if token in seen_tokens:
                raise ValueError("Repeated market-data pagination token")
            seen_tokens.add(token)
            params["page_token"] = token
        capture["completed"] = True
    finally:
        if client is None:
            session.close()
        capture["finished_at"] = utc_now()
        write_json(Path(destination) / "capture_receipt.json", capture)
    frames = {}
    for symbol, records in rows.items():
        if not records:
            raise ValueError(f"No bars returned for {symbol}")
        raw = pd.DataFrame(records).rename(columns={"o": "open", "h": "high", "l": "low",
                                                  "c": "close", "v": "volume"})
        raw.index = pd.DatetimeIndex(pd.to_datetime(raw.pop("t"), utc=True))
        frames[symbol] = prior_bars(raw, available_before)
    return frames, capture


def build(session, output, *, archive=None, fetch=False, candidate="ridge30_plan",
          feed="sip", calendar_days=100, env_file=ROOT / "backend/.env"):
    if bool(archive) == bool(fetch):
        raise ValueError("Choose exactly one input: archive or fetch")
    cutoff = session_cutoff(session)
    observed_at = pd.Timestamp(utc_now()).tz_convert(NY)
    next_day = cutoff.date() > observed_at.date()
    if cutoff.date() > observed_at.date() + timedelta(days=1):
        raise ValueError("Cannot build a future-session artifact beyond the next calendar day")
    if next_day and observed_at.hour < 16:
        raise ValueError("A next-session artifact requires today's completed regular session")
    if candidate not in {**CANDIDATES, **REFRESH_CANDIDATES}:
        raise ValueError("Choose an explicitly registered candidate")
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    os.chmod(out, 0o700)
    started = utc_now()
    if fetch:
        frames, source = fetch_alpaca(cutoff, out, feed=feed, calendar_days=calendar_days,
                                      env_file=env_file)
    else:
        frames, source = load_archive(archive, cutoff)
    for frame in frames.values():
        if not (frame.index + pd.Timedelta(minutes=5) <= observed_at).all():
            raise ValueError("Input contains a bar that was not complete at actual build time")
    files, coverage = {}, {}
    for symbol, frame in frames.items():
        path = out / f"{symbol}.csv"
        frame.to_csv(path, index_label="timestamp")
        files[path.name] = digest(path)
        coverage[symbol] = {"rows": len(frame), "first_bar": frame.index.min().isoformat(),
                            "last_bar": frame.index.max().isoformat(),
                            "observed_dates": sorted(set(frame.index.strftime("%Y-%m-%d")))}
    model = ProfitSignalShadowModel.fit(frames, session, candidate)
    if next_day and model.model.audit["training_sessions"][-1] != observed_at.date().isoformat():
        raise ValueError("A next-session artifact requires a complete common session today")
    artifact = out / "shadow_model.json"
    model.save(artifact)
    restored = ProfitSignalShadowModel.load(artifact)
    if restored.model.audit != model.model.audit:
        raise ValueError("Saved model failed audit round-trip")
    receipt = {"kind": "profit_shadow_daily_build_v1", "session": session,
               "started_at": started, "finished_at": utc_now(), "candidate": candidate,
               "execution_enabled": False, "performance_verified": False,
               "selection": "explicit_fixed_candidate_not_selected_by_outcomes",
               "training_cutoff": cutoff.isoformat(), "observed_at": observed_at.isoformat(), "source": source,
               "normalized_files_sha256": files, "input_coverage": coverage,
               "artifact": {"filename": artifact.name, "sha256": digest(artifact)},
               "training_sessions": model.model.audit["training_sessions"],
               "training_fits": model.model.audit["training_fits"],
               "limitations": ["A new dated artifact is required on the next session.",
                   "Historical bars were retrieved now, not at their original timestamps.",
                   "Model generation does not activate comparison or trading.",
                   "Input audits are not evidence of profitable future returns.",
                   "Raw Alpaca bars differ from the older Yahoo research data source."]}
    write_json(out / "build_receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--output", required=True, type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path)
    source.add_argument("--fetch-alpaca", action="store_true")
    parser.add_argument("--candidate", choices=sorted({**CANDIDATES, **REFRESH_CANDIDATES}),
                        default="ridge30_plan")
    parser.add_argument("--feed", choices=["sip", "iex"], default="sip")
    parser.add_argument("--calendar-days", type=int, default=100)
    parser.add_argument("--env-file", type=Path, default=ROOT / "backend/.env")
    args = parser.parse_args()
    receipt = build(args.session, args.output, archive=args.archive, fetch=args.fetch_alpaca,
                    candidate=args.candidate, feed=args.feed, calendar_days=args.calendar_days,
                    env_file=args.env_file)
    days = receipt["training_sessions"]
    print(json.dumps({"session": args.session, "candidate": args.candidate,
                      "training_sessions": len(days), "first_training_session": days[0],
                      "last_training_session": days[-1], "artifact_sha256": receipt["artifact"]["sha256"],
                      "execution_enabled": False, "performance_verified": False}))


if __name__ == "__main__":
    main()
