#!/usr/bin/env python3
"""Explicitly capture real Alpaca stock L1 quotes/trades; never starts automatically."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.market_data.history import credentials
from app.market_data.alpaca_l1_capture import AlpacaL1Capture
from app.research.universe import RESEARCH_UNIVERSES, research_universe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--symbols", nargs="+", help="Explicit symbols, e.g. SNDK TSLA MSTR NVDA")
    selection.add_argument("--universe", choices=tuple(RESEARCH_UNIVERSES), help="A versioned research-only symbol panel")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "backend" / "data" / "l1_capture")
    parser.add_argument("--feed", choices=("iex", "sip"), default="iex")
    args = parser.parse_args()
    symbols = args.symbols if args.symbols else research_universe(args.universe)
    collector = AlpacaL1Capture(symbols, args.output_dir, feed=args.feed)
    print(f"Capturing real {collector.feed.upper()} L1 quotes and trades for {', '.join(collector.symbols)} into {collector.output_dir}. Ctrl-C stops capture.")
    collector.run(*credentials())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
