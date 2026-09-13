#!/usr/bin/env python3
"""Predeclared offline experiments on the actual shared live quant policy.

No broker connection, live configuration write, synthetic fallback, date
substitution, or target-period parameter selection is performed.
"""

from __future__ import annotations

import argparse
from copy import copy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.quant_policy import PolicyModel, PolicySpec, integer_targets, target_weights
from backend.app.research.policy_replay import (
    ExecutionConfig, ShareLedger, complete_universe, fixed_order_cost_stress,
    replay_day, summarize,
)

SYMBOLS = ("SNDK", "TSLA", "MSTR", "NVDA")
DATES = ("2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
         "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new_json(path: Path, payload: Any) -> None:
    """Exclusive creation preserves prior attempted trials and their outputs."""
    # Serialize first: a serialization failure must not leave an apparently
    # completed but truncated trial file behind.
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    with path.open("x", encoding="utf-8") as file:
        file.write(serialized + "\n")


def candidate_grid(cost_bps: float) -> list[PolicySpec]:
    # The complete grid is declared and registered before any validation or
    # target-period optimization; it cannot expand in response to target PnL.
    return [
        PolicySpec(name=f"{feature}_h{horizon}_g{gamma}", feature_set=feature,
                   horizon_bars=horizon, ridge_alpha=10.0, risk_aversion=float(gamma),
                   cost_bps=cost_bps, gross_limit=0.95, symbol_limit=0.70)
        for feature in ("price", "price_volume")
        for horizon in (1, 3, 6)
        for gamma in (10, 50)
    ]


class ExperimentRunner:
    def __init__(self, frames, sessions, config):
        self.frames, self.sessions, self.config = frames, sessions, config
        self.models = {}
        self.predictions = {}

    def model(self, spec: PolicySpec, day: str) -> PolicyModel:
        # Risk aversion and trading cost affect optimization only. A shallow
        # copy with immutable replacement spec reuses precisely the same fit.
        key = (spec.feature_set, spec.horizon_bars, spec.ridge_alpha, day)
        if key not in self.models:
            self.models[key] = PolicyModel.fit(self.frames, train_before=day, spec=spec)
        fitted = copy(self.models[key])
        fitted.spec = spec
        if fitted.trained_last_session >= day:
            raise AssertionError("Training session leaks into evaluation session")
        return fitted

    def prediction(self, model: PolicyModel, day: str):
        key = (model.spec.feature_set, model.spec.horizon_bars, model.spec.ridge_alpha, day)
        if key not in self.predictions:
            day_panel = {symbol: self.sessions[symbol][day] for symbol in model.symbols}
            self.predictions[key] = {
                symbol: forecast.to_numpy()
                for symbol, forecast in model.forecast_frames(day_panel).items()
            }
        return self.predictions[key]

    def run(self, specs_by_day: dict[str, PolicySpec], kind: str = "policy"):
        ledger = ShareLedger(list(SYMBOLS), self.config)
        daily = []
        for day, spec in sorted(specs_by_day.items()):
            bars = {s: self.sessions[s][day] for s in SYMBOLS}
            model = self.model(spec, day)
            forecasts = self.prediction(model, day)
            index = bars[SYMBOLS[0]].index

            def decide(i, current_weights):
                mu = {s: float(forecasts[s][i]) for s in model.symbols}
                return target_weights(mu, model.covariance_at(index[i]), current_weights,
                                      spec, symbols=model.symbols,
                                      shortable={s: True for s in model.symbols})

            sizer = lambda weights, prices, equity: integer_targets(weights, prices, equity, spec)
            opening = None
            target = decide
            if kind == "cash":
                target = None
            elif kind == "equal_weight_session":
                target = None
                opening = {s: spec.gross_limit / len(SYMBOLS) for s in SYMBOLS}
            row = replay_day(ledger, bars, day, target, sizer, opening)
            row.update(candidate=spec.name, model_train_last_date=model.trained_last_session,
                       model_train_before=model.trained_before,
                       training_session_count=len(model.training_sessions),
                       kind=kind)
            daily.append(row)
        return {"daily": daily, "fills": ledger.fills, "marks": ledger.marks,
                "summary": summarize(daily, ledger.marks)}


def select_on_past(candidate_daily: dict[str, list[dict[str, Any]]], before: str,
                   validation_dates: list[str], order: list[str]) -> tuple[str, list[dict[str, Any]]]:
    if any(day >= before for day in validation_dates):
        raise ValueError("Selection validation dates must precede evaluation")
    scores = []
    for name in order:
        by_day = {r["date"]: r for r in candidate_daily[name]}
        if any(day not in by_day for day in validation_dates):
            raise ValueError(f"Missing prior validation evidence for {name}")
        value = float(np.prod([1 + by_day[day]["net_return"] for day in validation_dates]) - 1)
        scores.append({"candidate": name, "selection_before": before,
                       "validation_start": validation_dates[0], "validation_end": validation_dates[-1],
                       "validation_dates": list(validation_dates), "score": value})
    # First-declared candidate breaks exact ties, without retrospective changes.
    best = max(range(len(scores)), key=lambda i: scores[i]["score"])
    return order[best], scores


def export_run(output: Path, prefix: str, result: dict[str, Any]) -> None:
    for key in ("daily", "fills", "marks"):
        pd.DataFrame(result[key]).to_csv(output / f"{prefix}_{key}.csv", index=False)
    write_new_json(output / f"{prefix}_summary.json", result["summary"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars-dir", type=Path, default=ROOT / "reports/quant_audit_20260912/bars")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports/quant_research_20260913")
    parser.add_argument("--starting-equity", type=float, default=100_000.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--commission-bps", type=float, default=0.0)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = ExecutionConfig(args.starting_equity, args.slippage_bps, args.commission_bps)
    specs = candidate_grid(args.slippage_bps + args.commission_bps)
    spec_by_name = {s.name: s for s in specs}
    files = {s: (args.bars_dir / f"{s}.parquet").resolve() for s in SYMBOLS}
    frames = {s: pd.read_parquet(files[s]) for s in SYMBOLS}
    sessions, common, coverage = complete_universe(frames, list(DATES))
    prior = [day for day in common if day < DATES[0]]
    if len(prior) < 15:
        raise ValueError("Need at least ten training and five preperiod validation sessions")
    validation_dates = prior[-5:]
    hashes = {s: sha256(path) for s, path in files.items()}
    source_paths = [ROOT / "backend/app/quant_policy.py", Path(__file__).resolve(),
                    ROOT / "backend/app/research/policy_replay.py"]
    source_hashes = {str(path.relative_to(ROOT)): sha256(path) for path in source_paths}
    registry = {
        "schema_version": 1, "created_at": now(),
        "kind": "predeclared_retrospective_walk_forward_shared_policy_research",
        "target_dates_previously_inspected_in_prior_research": True,
        "candidate_count": len(specs), "candidates": [asdict(s) for s in specs],
        "evaluation_dates": list(DATES), "validation_dates": validation_dates,
        "selection_method": "preperiod_5_session_compounded_net_return",
        "selection_tie_break": "first_candidate_in_declared_order",
        "execution": asdict(config), "data_hashes": hashes,
        "data_paths": {s: str(path) for s, path in files.items()},
        "source_hashes": source_hashes,
        "diagnostics_predeclared": ["cash", "equal_weight_session", "rolling_past_5_session_selection",
                                    "selected_spec_optimizer_cost_zero_with_identical_execution_cost",
                                    "selected_spec_fixed_orderflow_5bps_cost_stress"],
        "symbol_execution_order": list(SYMBOLS),
        "assumptions": [
            "All symbols use one cash account with signed integer shares; starting equity is not multiplied per symbol.",
            "Each forecast/scaler/covariance is fitted only to complete sessions strictly before its trading day.",
            "Forecast is signed horizon gross return, not calibrated success probability; near-close stationary-rate scaling is shared with live.",
            "A completed five-minute bar fixes weights and integer shares at its close prices/equity; unchanged integer intent fills next-open subject to feasibility, without latency.",
            "Each bar marks actual unchanged shares; changed market weights are inputs to the joint turnover-aware objective.",
            "Reductions precede additions; additions obey cash, gross=.95 and symbol=.70 after costs; price drift is reported.",
            "All positions liquidate at the precommitted 15:55 opening reference price; actual live market fills need not equal it.",
            "Every buy/sell pays explicit per-side slippage and commission, including reductions, reversals and liquidation.",
            "OHLCV does not reproduce real spreads, liquidity, impact, latency, borrow availability/fees, financing or broker rejections.",
            "All four stocks are assumed shortable in research; real borrow availability is not inferred from bars.",
            "Intraday drawdown includes open, close and every modeled fill; within-bar path is unknown and unmodeled.",
            "Target results for all candidates are diagnostic only; selected fixed spec is chosen solely on 8/31-preceding sessions.",
            "These target dates were already examined in an earlier report; this is retrospective walk-forward, not untouched holdout.",
            "Twelve candidates and five validation days imply material selection uncertainty; apparent gains are not established edge.",
            "Baselines and zero-objective-cost ablation are diagnostics outside the declared candidate selection set.",
            "Fixed-orderflow cost stress reprices identical quantities, may violate limits, and is not an executable revised strategy.",
        ],
    }
    # Exclusive creation happens before any fits/results. Reproduce into a new
    # directory, preserving all earlier attempts instead of overwriting losses.
    write_new_json(output / "trial_registry.json", registry)
    pd.DataFrame(coverage).to_csv(output / "coverage.csv", index=False)
    runner = ExperimentRunner(frames, sessions, config)
    validations, validation_results, evaluations, trials = {}, {}, {}, []
    for number, spec in enumerate(specs, 1):
        print(f"[{number:02d}/{len(specs)}] {spec.name}: fitting and preperiod validation", flush=True)
        validation = runner.run(dict.fromkeys(validation_dates, spec))
        validations[spec.name] = validation["daily"]
        validation_results[spec.name] = validation
        write_new_json(output / f"validation_{number:02d}.json", {
            "id": number, "recorded_at": now(), "spec": asdict(spec),
            "summary": validation["summary"], "daily": validation["daily"],
        })
        print(f"  preperiod validation {validation['summary']['net_return']:+.4%}", flush=True)
    order = [s.name for s in specs]
    selected_name, validation_scores = select_on_past(validations, DATES[0], validation_dates, order)
    selected_spec = spec_by_name[selected_name]
    # Materialize the selected specification *before* computing any target
    # results. The program cannot silently revise this selection afterwards.
    write_new_json(output / "frozen_selection.json", {
        "frozen_at": now(), "spec": asdict(selected_spec),
        "selection_method": registry["selection_method"], "scores": validation_scores,
        "target_results_computed_at_freeze": False,
    })
    print(f"Frozen preperiod selection: {selected_name}; now evaluating target dates", flush=True)
    for number, spec in enumerate(specs, 1):
        validation = validation_results[spec.name]
        # Each target period starts at the stated account balance, independently
        # of validation gains or losses.
        evaluation = runner.run(dict.fromkeys(DATES, spec))
        evaluations[spec.name] = evaluation
        trial = {"id": number, "recorded_at": now(), "spec": asdict(spec),
                 "validation": validation["summary"], "evaluation_diagnostic": evaluation["summary"],
                 "validation_daily": validation["daily"], "evaluation_daily": evaluation["daily"],
                 "evaluation_used_for_selection": False}
        write_new_json(output / f"trial_{number:02d}.json", trial)
        trials.append(trial)
        print(f"  validation {validation['summary']['net_return']:+.4%}; "
              f"target diagnostic {evaluation['summary']['net_return']:+.4%}; "
              f"fills {evaluation['summary']['fill_count']}", flush=True)
    selected = evaluations[selected_name]
    export_run(output, "selected", selected)
    pd.DataFrame(validation_scores).to_csv(output / "selection_scores.csv", index=False)
    # Freeze the final spec using *only* preperiod scores, then refit each date on
    # earlier data. The last saved artifact is fit through the last completed day.
    final_model = PolicyModel.fit(frames, train_before="2026-09-12", spec=selected_spec)
    policy_path = output / "selected_policy.json"
    final_model.save(policy_path)
    # Daily rolling selection is reported separately, never substituted for the
    # frozen artifact after observing which variant happens to win the targets.
    historical_daily = {name: validations[name] + evaluations[name]["daily"] for name in order}
    rolling_specs, rolling_selection = {}, []
    available = validation_dates + list(DATES)
    for day in DATES:
        previous = [d for d in available if d < day][-5:]
        name, scores = select_on_past(historical_daily, day, previous, order)
        rolling_specs[day] = spec_by_name[name]
        for row in scores:
            row["selected"] = row["candidate"] == name
        rolling_selection.extend(scores)
    rolling = runner.run(rolling_specs)
    export_run(output, "rolling", rolling)
    pd.DataFrame(rolling_selection).to_csv(output / "rolling_selection.csv", index=False)
    benchmarks = {}
    for kind in ("cash", "equal_weight_session"):
        result = runner.run(dict.fromkeys(DATES, selected_spec), kind=kind)
        export_run(output, kind, result)
        benchmarks[kind] = result["summary"]
    zero_cost_spec = replace(selected_spec, name=selected_name + "_objective_cost_zero", cost_bps=0.0)
    ablation = runner.run(dict.fromkeys(DATES, zero_cost_spec))
    export_run(output, "objective_cost_zero", ablation)
    stress = fixed_order_cost_stress(selected["fills"], selected["marks"], replace(config, slippage_bps=5.0))
    write_new_json(output / "fixed_orderflow_5bps_stress.json", stress)
    recent_daily = [row for row in selected["daily"] if row["date"] >= "2026-09-08"]
    recent_summary = summarize(recent_daily, selected["marks"])
    per_ticker = {
        symbol: {
            period: {"net_pnl": sum(row[f"{symbol}_net_pnl"] for row in rows),
                     "costs": sum(row[f"{symbol}_costs"] for row in rows),
                     "fill_count": sum(row[f"{symbol}_fill_count"] for row in rows)}
            for period, rows in (("two_week", selected["daily"]), ("recent_week", recent_daily))
        } for symbol in SYMBOLS
    }
    score = next(row["score"] for row in validation_scores if row["candidate"] == selected_name)
    summary = {
        "schema_version": 1, "status": "complete", "generated_at": now(),
        "evaluation_start": DATES[0], "evaluation_end": DATES[-1],
        "evaluation_dates": list(DATES), "selection_cutoff": validation_dates[-1],
        "selection_method": registry["selection_method"], "validation_dates": validation_dates,
        "starting_equity": config.starting_equity,
        "cost_bps_per_side": config.slippage_bps + config.commission_bps,
        "execution": asdict(config), "selected_spec": asdict(selected_spec),
        "selected_validation_score": score, "data_hashes": hashes,
        "data_paths": {s: str(path) for s, path in files.items()},
        "core_source_sha256": source_hashes["backend/app/quant_policy.py"],
        "source_hashes": source_hashes,
        "selected_policy_path": str(policy_path), "selected_policy_sha256": sha256(policy_path),
        "artifact_trained_before": final_model.trained_before,
        "artifact_trained_last_session": final_model.trained_last_session,
        "artifact_training_rows": final_model.training_rows,
        "trial_count": len(trials),
        "trials": [{"id": t["id"], "spec": t["spec"],
                    "validation_net_return": t["validation"]["net_return"],
                    "evaluation_net_return": t["evaluation_diagnostic"]["net_return"],
                    "selected": t["spec"]["name"] == selected_name} for t in trials],
        "portfolio": {"two_week": selected["summary"], "recent_week": recent_summary},
        "per_ticker": per_ticker, "daily": selected["daily"],
        "benchmarks": benchmarks, "rolling_selection_diagnostic": rolling["summary"],
        "objective_cost_zero_diagnostic": ablation["summary"],
        "fixed_orderflow_5bps_stress": stress,
        "retrospective": True, "paper_research_only": True,
        "deploy_evidence": "weak_small_retrospective_sample" if score > 0 else "weak_nonpositive_preperiod_validation",
        "target_results_used_to_choose_artifact": False,
        "assumptions": registry["assumptions"],
    }
    # Incomplete or failed runs have registry/trials, but never status=complete.
    write_new_json(output / "research_summary.json", summary)
    print(json.dumps({"selected": selected_name, "preperiod_score": score,
                      "two_week": selected["summary"], "recent_week": recent_summary,
                      "output": str(output)}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
