#!/usr/bin/env python3
"""Supplement a completed frozen-policy study with a fresh $100k recent week.

This is an explicitly requested capital-account reset, not another candidate
search. Existing trial registries and results are preserved byte-for-byte.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.quant_policy import PolicySpec
from backend.app.research.policy_replay import ExecutionConfig, complete_universe, fixed_order_cost_stress
from scripts.run_policy_research import ExperimentRunner, export_run, now, sha256, write_new_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports/quant_research_20260913")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    summary_path = output / "research_summary.json"
    summary = json.loads(summary_path.read_text())
    if summary.get("status") != "complete":
        raise ValueError("The base research must complete before the capital-reset diagnostic")
    if "recent_week_reset" in summary["portfolio"]:
        raise ValueError("This capital-reset diagnostic has already completed; preserve its result")
    for relative, expected in summary["source_hashes"].items():
        if sha256(ROOT / relative) != expected:
            raise ValueError(f"Base-study source changed: {relative}; do not mix policy versions")
    frozen_path = output / "frozen_selection.json"
    frozen = json.loads(frozen_path.read_text())
    if frozen["spec"] != summary["selected_spec"]:
        raise ValueError("Selected specification differs from the preperiod frozen selection")
    spec = PolicySpec(**frozen["spec"])
    frames = {}
    for symbol, path in summary["data_paths"].items():
        path = Path(path)
        if sha256(path) != summary["data_hashes"][symbol]:
            raise ValueError(f"Input data changed for {symbol}")
        frames[symbol] = pd.read_parquet(path)
    dates = [day for day in summary["evaluation_dates"] if day >= "2026-09-08"]
    config = replace(ExecutionConfig(**summary["execution"]), starting_equity=100_000.0)
    sessions, _, _ = complete_universe(frames, dates)
    supplemental_registration = {
        "registered_at": now(), "kind": "user_requested_capital_reset_of_already_frozen_policy",
        "starting_equity": config.starting_equity, "dates": dates, "spec": frozen["spec"],
        "base_summary_sha256": sha256(summary_path), "frozen_selection_sha256": sha256(frozen_path),
        "base_registry_sha256": sha256(output / "trial_registry.json"),
        "supplemental_source_path": str(Path(__file__).resolve()),
        "supplemental_source_sha256": sha256(Path(__file__).resolve()),
        "parameter_selection_performed": False,
    }
    write_new_json(output / "recent_week_reset_registration.json", supplemental_registration)
    result = ExperimentRunner(frames, sessions, config).run(dict.fromkeys(dates, spec))
    export_run(output, "recent_week_reset100k", result)
    stress = fixed_order_cost_stress(result["fills"], result["marks"], replace(config, slippage_bps=5.0))
    write_new_json(output / "recent_week_reset100k_fixed_orderflow_5bps_stress.json", stress)
    # Preserve the completed primary summary, then atomically add this distinct
    # requested comparison. No prior score, selected spec, trial or fill changes.
    with (output / "research_summary_base.json").open("xb") as backup:
        backup.write(summary_path.read_bytes())
    summary["portfolio"]["recent_week_reset"] = result["summary"]
    summary["recent_week_reset_fixed_orderflow_5bps_stress"] = stress
    summary["recent_week_reset_registration"] = supplemental_registration
    summary["recent_week_reset_daily"] = result["daily"]
    for symbol in frames:
        summary["per_ticker"][symbol]["recent_week_reset"] = {
            "net_pnl": sum(day[f"{symbol}_net_pnl"] for day in result["daily"]),
            "costs": sum(day[f"{symbol}_costs"] for day in result["daily"]),
            "fill_count": sum(day[f"{symbol}_fill_count"] for day in result["daily"]),
        }
    summary["generated_at"] = now()
    temporary = output / "research_summary.with_recent_week_reset.tmp"
    write_new_json(temporary, summary)
    temporary.replace(summary_path)
    print(json.dumps({"recent_week_reset100k": result["summary"], "per_ticker": {
        s: summary["per_ticker"][s]["recent_week_reset"] for s in frames
    }}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
