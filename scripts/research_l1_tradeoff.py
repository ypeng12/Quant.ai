#!/usr/bin/env python3
"""Evaluate held-out L1 horizon diagnostics without trading or executable PnL."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"backend"))
from app.research.l1_tradeoff import HORIZONS, run_l1_tradeoff


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", nargs="+", type=Path, required=True)
    p.add_argument("--symbols", nargs="+", default=["SNDK", "TSLA", "PLTR", "NVDA"])
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--sessions", nargs="+")
    p.add_argument("--horizons", nargs="+", default=list(HORIZONS))
    p.add_argument("--decision-interval", default="5s")
    p.add_argument("--max-quote-age", default="1s")
    p.add_argument("--label-tolerance", default="1s")
    p.add_argument("--ofi-window", default="5s")
    p.add_argument("--max-gap", default="30s")
    p.add_argument("--ridge-alpha", type=float, default=10.)
    p.add_argument("--intraday-cut", default="12:00", help="Only if one date: local New York train/test cutoff")
    p.add_argument("--costs", type=float, nargs="+", default=[2., 5.], help="Hypothetical one-way bps; no realized PnL")
    args = p.parse_args()
    try:
        result = run_l1_tradeoff(args.input, args.symbols, args.output, session_dates=args.sessions,
                                 horizons=args.horizons, decision_interval=args.decision_interval,
                                 max_quote_age=args.max_quote_age, label_tolerance=args.label_tolerance,
                                 ofi_window=args.ofi_window, max_gap=args.max_gap, ridge_alpha=args.ridge_alpha,
                                 intraday_cut=args.intraday_cut, costs=args.costs, progress=lambda s: print(s, flush=True))
    except (ValueError, OSError) as error:
        p.exit(2, f"L1 diagnostic error: {error}\n")
    print(json.dumps({"status": result["status"], "evaluated_candidates": result["evaluated_candidates"],
                      "evaluation_kinds": result["evaluation_kinds"], "selected_for_live": None,
                      "report": str(args.output/"REPORT.md")}, indent=2))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
