#!/usr/bin/env python3
"""Record real L1 alongside a supplied forecast; no orders or forecast blending.

This is an offline replay/diagnostic command. Use completed capture snapshots.
The forecast JSON supplies decision_time, target, horizon_seconds, symbols,
mu, covariance, model_trained_before and last_training_label_end. Return units
are decimal gross returns; symbol order also defines covariance matrix order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.market_data.alpaca_l1_capture import load_real_l1_events
from app.research.l1_policy_overlay import build_l1_policy_record


def _aware(value, field):
    value = pd.Timestamp(value)
    if pd.isna(value) or value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def record_context(forecast_path, inputs, output, *, feed, source, max_quote_age,
                   frequency="5min", max_gap="30s"):
    """Preserve supplied forecast even when an L1 input is unavailable/invalid."""
    if feed not in ("iex", "sip") or source not in ("alpaca_stock_historical", "alpaca_stock_websocket"):
        raise ValueError("Explicit Alpaca feed and source required")
    forecast_path, output = Path(forecast_path), Path(output)
    payload = forecast_path.read_bytes()
    baseline = json.loads(payload)
    decision = _aware(baseline["decision_time"], "decision_time")
    trained = _aware(baseline["model_trained_before"], "model_trained_before")
    label_end = _aware(baseline["last_training_label_end"], "last_training_label_end")
    if trained > decision or label_end >= trained:
        raise ValueError("Base forecast training/label cutoff is not mature at decision_time")
    if baseline.get("return_units") != "decimal_gross_return":
        raise ValueError("Forecast must declare return_units=decimal_gross_return")
    date = decision.tz_convert("America/New_York").strftime("%Y-%m-%d")
    roots = list(dict.fromkeys(Path(root).resolve() for root in inputs))
    if not roots:
        raise ValueError("At least one capture input is required")
    if output.exists():
        raise ValueError("Output already exists; choose a new context record path")
    observed, files, errors = {}, [], {}
    for symbol in baseline["symbols"]:
        frames, seen_paths, seen_content = [], set(), set()
        try:
            for root in roots:
                path = root / date / f"{symbol}.jsonl"
                if not path.is_file():
                    continue
                resolved = path.resolve()
                if resolved in seen_paths:
                    raise ValueError("Overlapping capture inputs")
                seen_paths.add(resolved)
                before = (path.stat().st_size, path.stat().st_mtime_ns)
                frame = load_real_l1_events(root, symbol, date)
                sha = hashlib.sha256()
                with path.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        sha.update(block)
                if before != (path.stat().st_size, path.stat().st_mtime_ns):
                    raise ValueError("Capture changed during read; use a completed snapshot")
                if before[0] and sha.hexdigest() in seen_content:
                    raise ValueError("Duplicate capture file contents")
                seen_content.add(sha.hexdigest())
                files.append(dict(symbol=symbol, path=str(path), sha256=sha.hexdigest(), bytes=before[0]))
                if not frame.empty:
                    frames.append(frame)
            if frames:
                observed[symbol] = pd.concat(frames).sort_index(kind="stable")
        except (ValueError, OSError, KeyError, TypeError) as error:
            errors[symbol] = str(error)
            observed.pop(symbol, None)
    clock = "historical_exchange_latency_unverified" if source == "alpaca_stock_historical" else "recorded_arrival"
    expected = {symbol: dict(feed=feed, source=source, clock=clock) for symbol in baseline["symbols"]}
    forecast = SimpleNamespace(mu=baseline["mu"], covariance=baseline["covariance"], symbols=tuple(baseline["symbols"]))
    result = build_l1_policy_record(
        forecast, observed, decision_time=decision, base_target=baseline["target"],
        horizon_seconds=baseline["horizon_seconds"], expected_contracts=expected,
        max_quote_age=max_quote_age, frequency=frequency, max_gap=max_gap,
    ).to_dict()
    result.update(
        forecast_source=dict(path=str(forecast_path.resolve()), sha256=hashlib.sha256(payload).hexdigest(),
                             model_trained_before=trained.isoformat(), last_training_label_end=label_end.isoformat(),
                             lineage_verified=False),
        input_files=files, input_errors=errors, orders_submitted=0,
        unverified_assumptions=[
            "Forecast metadata is supplied by the caller, not independently reconstructed from its training pipeline.",
            "L1 diagnostics do not modify the supplied forecast or submit orders.",
            "Historical exchange-time data does not establish actual real-time arrival latency.",
            "IEX quotes are single-venue prices, not NBBO or executable portfolio returns.",
        ],
    )
    for symbol, reason in errors.items():
        result["l1"][symbol]["reason"] = f"Capture input unavailable: {reason}"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as handle:
        handle.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast", type=Path, required=True)
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--feed", choices=["iex", "sip"], required=True)
    parser.add_argument("--source", choices=["alpaca_stock_historical", "alpaca_stock_websocket"], required=True)
    parser.add_argument("--max-quote-age", required=True, help="Explicit diagnostic freshness assumption, e.g. 1s")
    parser.add_argument("--frequency", default="5min")
    parser.add_argument("--max-gap", default="30s")
    args = parser.parse_args()
    try:
        result = record_context(args.forecast, args.input, args.output, feed=args.feed, source=args.source,
                                max_quote_age=args.max_quote_age, frequency=args.frequency, max_gap=args.max_gap)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"L1 context error: {error}\n")
    print(json.dumps(dict(record=str(args.output), active_forecast=result["active_forecast"],
                          l1={symbol: row["status"] for symbol, row in result["l1"].items()}, orders_submitted=0), indent=2))


if __name__ == "__main__":
    main()
