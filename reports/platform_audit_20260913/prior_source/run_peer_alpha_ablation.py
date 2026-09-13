#!/usr/bin/env python3
"""Compare the frozen OHLCV baseline with one causal peer-residual candidate.

This is a post-hoc exploratory ablation because its target dates were examined
before this script existed.  It writes a separate artifact and never changes the
selected live policy.  A future untouched period is required before promotion.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.quant_policy import PolicySpec
from backend.app.research.policy_replay import ExecutionConfig, complete_universe, fixed_order_cost_stress
from scripts.run_policy_research import ExperimentRunner

SYMBOLS = ("SNDK", "TSLA", "MSTR", "NVDA")
VALIDATION_DATES = ("2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28")
EVALUATION_DATES = ("2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
                    "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    bar_root = ROOT / "reports" / "quant_audit_20260912" / "bars"
    frames = {symbol: pd.read_parquet(bar_root / f"{symbol}.parquet") for symbol in SYMBOLS}
    requested = list(VALIDATION_DATES + EVALUATION_DATES)
    sessions, complete, coverage = complete_universe(frames, requested)
    missing = sorted(set(requested).difference(complete))
    if missing:
        raise ValueError(f"Requested sessions are incomplete: {missing}")

    config = ExecutionConfig(starting_equity=100_000.0, slippage_bps=2.0, commission_bps=0.0,
                             gross_limit=0.95, symbol_limit=0.70)
    candidates = (
        PolicySpec("frozen_price_volume_h1_g50", feature_set="price_volume", horizon_bars=1,
                   ridge_alpha=10.0, risk_aversion=50.0, cost_bps=2.0, gross_limit=.95, symbol_limit=.70),
        PolicySpec("exploratory_price_volume_peer_h1_g50", feature_set="price_volume_peer", horizon_bars=1,
                   ridge_alpha=10.0, risk_aversion=50.0, cost_bps=2.0, gross_limit=.95, symbol_limit=.70),
    )
    runner = ExperimentRunner(frames, sessions, config)
    records = []
    for spec in candidates:
        validation = runner.run(dict.fromkeys(VALIDATION_DATES, spec))
        evaluation = runner.run(dict.fromkeys(EVALUATION_DATES, spec))
        records.append({
            "spec": asdict(spec),
            "validation": validation["summary"],
            "evaluation_retrospective": evaluation["summary"],
            "evaluation_daily": evaluation["daily"],
            "fixed_orderflow_cost_stress_5bps": fixed_order_cost_stress(
                evaluation["fills"], evaluation["marks"],
                ExecutionConfig(starting_equity=100_000.0, slippage_bps=5.0, commission_bps=0.0,
                                gross_limit=0.95, symbol_limit=0.70),
            ),
        })

    # This is a separate cost sensitivity, not an additional candidate or a
    # parameter-selection opportunity.  The optimizer sees the higher cost, so
    # it can change its turnover; this answers a different question from
    # repricing the exact recorded 2 bps fills.
    cost_stress = []
    for spec in candidates:
        stressed = PolicySpec(**{**asdict(spec), "name": spec.name + "_cost5", "cost_bps": 5.0})
        result = runner.run(dict.fromkeys(EVALUATION_DATES, stressed))
        cost_stress.append({"spec": asdict(stressed), "evaluation_retrospective": result["summary"]})

    output = ROOT / "reports" / "quant_research_20260913" / "peer_alpha_ablation"
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "research_status": "exploratory_posthoc_not_promotable",
        "purpose": "Fixed-config ablation of leave-one-out peer residual features against the frozen selected OHLCV baseline.",
        "selection_rule": "none; neither candidate is selected or written to the live policy",
        "validation_dates": list(VALIDATION_DATES),
        "evaluation_dates": list(EVALUATION_DATES),
        "execution": asdict(config),
        "data_hashes": {symbol: digest(bar_root / f"{symbol}.parquet") for symbol in SYMBOLS},
        "coverage": coverage,
        "candidates": records,
        "cost_stress_reoptimized_5bps": cost_stress,
        "limitations": [
            "The evaluation period was already viewed in earlier research, so it is retrospective exploration rather than untouched evidence.",
            "The four-symbol peer basket is not a broad market or sector benchmark.",
            "Costs are assumed 2 bps per executed side; observed L1 spread, impact, borrow, and actual fills are unavailable.",
            "No result is an earning forecast or a justification to change the live artifact.",
        ],
    }
    (output / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pd.DataFrame([
        {"candidate": row["spec"]["name"], "window": window, **row[key]}
        for row in records
        for window, key in (("validation", "validation"), ("evaluation_retrospective", "evaluation_retrospective"))
    ]).to_csv(output / "summary.csv", index=False)
    print(json.dumps({"output": str(output), "candidates": [row["spec"]["name"] for row in records]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
