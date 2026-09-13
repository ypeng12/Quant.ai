#!/usr/bin/env python3
"""Measure coverage, gaps, spreads, duplicates and latency in retained L1 data."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.market_data.l1_quality import write_l1_quality_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "backend" / "data" / "l1_capture")
    parser.add_argument("--symbols", nargs="+", default=["SNDK", "TSLA", "PLTR", "NVDA"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = write_l1_quality_report(args.input, args.symbols, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
