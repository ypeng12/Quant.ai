#!/usr/bin/env python3
"""Refit a frozen JSON policy from local completed sessions, without reselection.

The cutoff and destination are mandatory. Existing files are never overwritten,
and no broker, live configuration, network source, or trial registry is touched.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.quant_policy import NY, PolicyModel
from backend.app.research.causal_week_replay import prepare_sessions


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new_atomic(path: Path, content: bytes) -> None:
    """Publish complete bytes atomically, refusing even a concurrent overwrite."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        # Linking on the same filesystem publishes a fully written inode and
        # fails if the requested destination already exists (unlike replace).
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def refresh_policy(source_policy: Path, bars_dir: Path, train_before: str,
                   output_path: Path) -> dict:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", train_before):
        raise ValueError("train-before must be an explicit YYYY-MM-DD date")
    cutoff = date.fromisoformat(train_before)
    source_policy, bars_dir, output_path = (Path(p).resolve() for p in (source_policy, bars_dir, output_path))
    metadata_path = output_path.with_suffix(output_path.suffix + ".metadata.json")
    if output_path == source_policy or output_path.exists() or metadata_path.exists():
        raise FileExistsError("Choose a new output path; source/current artifacts and prior metadata cannot be overwritten")
    source = PolicyModel.load(source_policy)
    inputs, frames = {}, {}
    for symbol in source.symbols:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", symbol):
            raise ValueError(f"Unsupported local bar filename symbol: {symbol!r}")
        path = (bars_dir / f"{symbol}.parquet").resolve()
        if path.parent != bars_dir:
            raise ValueError("Local bar path escapes the supplied directory")
        raw = pd.read_parquet(path)
        if not isinstance(raw.index, pd.DatetimeIndex) or raw.index.tz is None:
            raise ValueError(f"{symbol}: timestamps must be timezone-aware bar opens")
        # Filter dates before OHLCV validation/feature calculation: future rows
        # cannot affect inclusion, model means, covariance or fitted parameters.
        ny_index = raw.index.tz_convert(NY)
        before = ny_index.date < cutoff
        eligible, coverage = prepare_sessions(raw.loc[before], [])
        if not eligible:
            raise ValueError(f"{symbol}: no complete regular sessions strictly before {train_before}")
        dates = sorted(eligible)
        frames[symbol] = pd.concat([eligible[day] for day in dates])
        inputs[symbol] = {
            "path": str(path), "sha256": sha256(path), "input_rows": len(raw),
            "rows_ignored_on_or_after_cutoff": int((~before).sum()),
            "eligible_complete_sessions": dates, "eligible_rows": len(frames[symbol]),
            "latest_complete_session": dates[-1],
            "new_complete_sessions_after_source_latest": [d for d in dates if d > source.trained_last_session],
            "rejected_prior_sessions": [r for r in coverage if r["status"] != "complete"],
        }
    updated = PolicyModel.fit(frames, train_before=train_before, spec=source.spec)
    if asdict(updated.spec) != asdict(source.spec) or updated.symbols != source.symbols:
        raise AssertionError("Refit must preserve the frozen specification and symbol universe")
    latest = {s: row["latest_complete_session"] for s, row in inputs.items()}
    advanced = {s: latest[s] > source.trained_last_session for s in source.symbols}
    if all(advanced.values()):
        status = "refit_with_new_complete_sessions_for_all_symbols"
    elif any(advanced.values()):
        status = "refit_with_partial_universe_data_advance"
    else:
        status = "refit_without_new_complete_sessions"
    # Reuse the validated safe-JSON serializer, but publish to a new destination
    # with exclusive atomic linking so a current live file can never be replaced.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".policy-refit-", dir=output_path.parent) as temporary_dir:
        temporary_policy = Path(temporary_dir) / "model.json"
        updated.save(temporary_policy)
        serialized_policy = temporary_policy.read_bytes()
    metadata = {
        "schema_version": 1, "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kind": "local_frozen_spec_refit_no_parameter_selection",
        "source_policy_path": str(source_policy), "source_policy_sha256": sha256(source_policy),
        "source_trained_before": source.trained_before,
        "source_trained_last_session": source.trained_last_session,
        "requested_train_before": train_before, "output_policy_path": str(output_path),
        "output_policy_sha256": hashlib.sha256(serialized_policy).hexdigest(),
        "spec": asdict(updated.spec), "symbols": list(updated.symbols),
        "trained_before": updated.trained_before, "trained_last_session": updated.trained_last_session,
        "latest_complete_session_by_symbol": latest,
        "latest_complete_sessions_synchronized": len(set(latest.values())) == 1,
        "training_rows": updated.training_rows, "training_sessions": updated.training_sessions,
        "data_advanced_by_symbol": advanced, "inputs": inputs,
        "core_source_sha256": sha256(ROOT / "backend/app/quant_policy.py"),
        "updater_source_sha256": sha256(Path(__file__).resolve()),
        "parameter_selection_performed": False, "broker_or_live_configuration_changed": False,
        "limitations": [
            "Data is read from existing local parquet files; this command does not download new observations.",
            "Only exact complete 78-bar regular sessions strictly before the cutoff are fitted; shortened/incomplete days are excluded.",
            "Freshness is reported from observed session dates, not an exchange calendar or a promise that data reaches yesterday.",
            "A refit without later complete sessions is explicitly reported as no data advance, even if the requested cutoff is later.",
            "The frozen feature/horizon/risk/cost/capital specification is retained; refitting does not establish new trading edge.",
            "The new artifact is only an output file; configuring a runner to use it is a separate operation.",
        ],
    }
    serialized_metadata = (json.dumps(metadata, indent=2, allow_nan=False) + "\n").encode()
    write_new_atomic(output_path, serialized_policy)
    write_new_atomic(metadata_path, serialized_metadata)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-policy", required=True, type=Path, help="Existing validated JSON; only its frozen spec/universe are retained")
    parser.add_argument("--bars-dir", required=True, type=Path, help="Existing SYMBOL.parquet files, with timezone-aware 5-minute bar-open timestamps")
    parser.add_argument("--train-before", required=True, help="Exclusive YYYY-MM-DD training cutoff")
    parser.add_argument("--output", required=True, type=Path, help="New JSON file path; an existing path is rejected")
    args = parser.parse_args()
    metadata = refresh_policy(args.source_policy, args.bars_dir, args.train_before, args.output)
    print(json.dumps({key: metadata[key] for key in (
        "status", "output_policy_path", "trained_before", "trained_last_session",
        "latest_complete_session_by_symbol", "data_advanced_by_symbol",
        "parameter_selection_performed", "broker_or_live_configuration_changed",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
