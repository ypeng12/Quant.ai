#!/usr/bin/env python3
"""Explicitly capture real Alpaca stock L1 quotes/trades; never starts automatically."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.market_data.history import credentials
from app.market_data.alpaca_l1_capture import AlpacaL1Capture
from app.research.universe import RESEARCH_UNIVERSES, research_universe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--symbols", nargs="+", help="Explicit symbols, e.g. SNDK TSLA PLTR NVDA")
    selection.add_argument("--universe", choices=tuple(RESEARCH_UNIVERSES), help="A versioned research-only symbol panel")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "backend" / "data" / "l1_capture")
    parser.add_argument("--feed", choices=("iex", "sip"), default="iex")
    parser.add_argument("--env-file", type=Path, help="Existing private credential file; no secret values in arguments")
    parser.add_argument("--duration-seconds", type=float, help="Optional bounded connection check; omitted for continuous collection")
    args = parser.parse_args()
    if args.duration_seconds is not None and args.duration_seconds <= 0:
        parser.error("--duration-seconds must be positive")
    key, secret = credentials(args.env_file)
    symbols = args.symbols if args.symbols else research_universe(args.universe)
    collector = AlpacaL1Capture(symbols, args.output_dir, feed=args.feed)
    def request_stop(*_):
        threading.Thread(target=collector.stop, daemon=True).start()
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    timer = None
    if args.duration_seconds:
        timer = threading.Timer(args.duration_seconds, request_stop)
        timer.daemon = True
        timer.start()
    print(f"Capturing real {collector.feed.upper()} L1 quotes and trades for {', '.join(collector.symbols)} into {collector.output_dir}. Ctrl-C stops capture.", flush=True)
    try:
        collector.run(key, secret)
    finally:
        if timer:
            timer.cancel()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
