#!/usr/bin/env python3
"""Strict-date, sequential offline research. Never connects to a broker."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.research.causal_week_replay import CANDIDATES, ReplayConfig, run_ticker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars-dir", type=Path, required=True)
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--dates", nargs="+", required=True, help="Exact YYYY-MM-DD dates; no fallback")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--commission-bps", type=float, default=0.0)
    parser.add_argument("--min-train-sessions", type=int, default=5)
    parser.add_argument("--validation-sessions", type=int, default=3)
    parser.add_argument("--fixed-selection-from", type=Path,
                        help="Prior daily.csv: preserve that run's choices for a cost-only stress test")
    args = parser.parse_args()
    config = ReplayConfig(args.slippage_bps, args.commission_bps,
                          args.min_train_sessions, args.validation_sessions)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    tables = {key: [] for key in ("daily", "candidate_daily", "validation", "trades", "coverage")}
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "kind": "offline_ohlcv_research_baseline_not_live_runner_replay",
        "requested_dates": sorted(set(args.dates)),
        "candidate_order": list(CANDIDATES), "config": config.__dict__,
        "assumptions": [
            "Inputs are real, timezone-aware OHLCV with 5-minute bar OPEN timestamps; provenance is caller-supplied.",
            "Only exact complete 09:30-16:00 New York sessions are eligible. No fallback, interpolation, or synthetic data.",
            "Features reset per session and use completed bars only. Signals fill next bar open; no latency is modeled.",
            "Daily candidate choice maximizes compounded net return on the prior validation sessions.",
            "Validation ML refits only on sessions before each validation day; test ML refits on all earlier complete sessions.",
            "Features/scalers/labels never cross a session or train/test boundary. Ridge alpha is fixed at 10.",
            "Exposure is an idealized +/-1 bar-return model with full session-end liquidation, not shares or real executions.",
            "One-way commission and slippage bps apply to target-exposure turnover, including reversals and final close.",
            "No live alpha/LAB/ML behavior, order book, spread history, queue, latency, liquidity, borrow, or financing is reproduced.",
            "Intraday drawdown is marked at 5-minute interval boundaries and costs; within-bar adverse excursions are omitted.",
            "Buy-and-hold enters at 09:30 by prior commitment; signal strategies first enter at 09:35 or later.",
            "Candidate test returns are descriptive only and must not be used to choose that same day's candidate.",
            "Incomplete dates are excluded and disclosed; evaluated-date totals are not full-period returns when dates are missing.",
            "Short validation windows cannot establish reliable performance or guarantee profits.",
        ],
        "inputs": {}, "summary": {}, "errors": {},
    }
    fixed_table = None
    if args.fixed_selection_from:
        fixed_table = pd.read_csv(args.fixed_selection_from)
        if fixed_table.duplicated(["ticker", "date"]).any():
            raise ValueError("Fixed selection input has duplicate ticker/date rows")
        prior_metadata = json.loads((args.fixed_selection_from.parent / "metadata.json").read_text())
        for key in ("min_train_sessions", "validation_sessions", "ridge_alpha"):
            if prior_metadata["config"][key] != getattr(config, key):
                raise ValueError(f"Cost-only stress must preserve original {key}")
        metadata["fixed_selection_source"] = {
            "path": str(args.fixed_selection_from.resolve()),
            "sha256": hashlib.sha256(args.fixed_selection_from.read_bytes()).hexdigest(),
        }
        metadata["assumptions"].append(
            "Daily choices are copied from the fixed selection source; increased costs do not reselect strategies."
        )
    # Deliberately sequential so each ticker has a separate, inspectable result.
    for ticker in args.tickers:
        source = args.bars_dir / f"{ticker}.parquet"
        try:
            raw = pd.read_parquet(source)
            metadata["inputs"][ticker] = {
                "path": str(source.resolve()),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "rows": len(raw),
            }
            fixed_selections = None
            if fixed_table is not None:
                fixed_rows = fixed_table.loc[fixed_table["ticker"] == ticker]
                fixed_selections = {row.date: None if pd.isna(row.selected_candidate) else row.selected_candidate
                                    for row in fixed_rows.itertuples()}
                if metadata["inputs"][ticker]["sha256"] != prior_metadata["inputs"][ticker]["sha256"]:
                    raise ValueError("Cost-only stress must use the identical input OHLCV file")
            result = run_ticker(ticker, raw, args.dates, config, fixed_selections=fixed_selections)
        except (OSError, ValueError, TypeError, ImportError) as error:
            metadata["errors"][ticker] = f"{type(error).__name__}: {error}"
            tables["daily"].extend({"ticker": ticker, "date": day, "status": "input_error",
                                    "selected_candidate": None, "net_return": None}
                                   for day in sorted(set(args.dates)))
            print(f"{ticker}: INPUT ERROR: {error}")
            continue
        for key in tables:
            tables[key].extend(result[key])
        metadata["summary"][ticker] = result["summary"]
        print(f"{ticker}: {json.dumps(result['summary'], ensure_ascii=False)}")
    for key, rows in tables.items():
        pd.DataFrame(rows).to_csv(output / f"{key}.csv", index=False)
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Research outputs: {output}")
    return 1 if metadata["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
