#!/usr/bin/env python3
"""Train QI, transition microprice and OFI Ridge from retained real L1 events."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.research.real_l1_research import DEFAULT_HORIZONS, run_real_l1_research


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", type=Path, default=[ROOT / "backend/data/l1_capture"],
                        help="One or more capture roots; separate historical quote/trade roots can be combined")
    parser.add_argument("--symbols", nargs="+", default=["SNDK", "TSLA", "PLTR", "NVDA"])
    parser.add_argument("--output", type=Path, required=True, help="New report directory (must not exist)")
    parser.add_argument("--before", help="Exclusive timezone-aware training cutoff; default uses all retained observations")
    parser.add_argument("--sessions", nargs="+", help="Explicit YYYY-MM-DD dates; load only these sessions without sampling")
    parser.add_argument("--regular-session", action=argparse.BooleanOptionalAction, default=True,
                        help="Use XNYS calendar open <= observed time < close, including early closes (default); --no-regular-session includes extended hours")
    parser.add_argument("--horizons", nargs="+", default=list(DEFAULT_HORIZONS))
    parser.add_argument("--tolerance", default="1s", help="Maximum additional wait for the future quote")
    parser.add_argument("--max-gap", default="30s", help="Quote gaps larger than this split label sequences")
    parser.add_argument("--ridge-alpha", type=float, default=10.0)
    parser.add_argument("--logistic-c", type=float, default=1.0)
    parser.add_argument("--tick-size", type=float, default=.01)
    parser.add_argument("--imbalance-bins", type=int, default=5)
    parser.add_argument("--spread-ticks", nargs="+", type=int,
                        help="Optional exact spread states; default learns quantile bins from training observations")
    parser.add_argument("--spread-bins", type=int, default=5, help="Training-only quantile bins when exact ticks are not specified")
    parser.add_argument("--price-changes", type=int, default=6)
    args = parser.parse_args()
    try:
        result = run_real_l1_research(args.input, args.symbols, args.output, before=args.before, session_dates=args.sessions,
                                      regular_session=args.regular_session,
                                      horizons=args.horizons, tolerance=args.tolerance, max_gap=args.max_gap,
                                      ridge_alpha=args.ridge_alpha, logistic_c=args.logistic_c,
                                      tick_size=args.tick_size, imbalance_bins=args.imbalance_bins,
                                      spread_ticks=args.spread_ticks, spread_bins=args.spread_bins, price_changes=args.price_changes)
    except (ValueError, OSError) as error:
        parser.exit(2, f"L1 research error: {error}\n")
    print(json.dumps({"status": result["status"], "trained_models": result["trained_models"],
                      "unavailable_models": result["unavailable_models"], "performance_verified": False,
                      "registry": str(args.output / "registry.json")}, indent=2))
    return 2 if result["status"] == "invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())
