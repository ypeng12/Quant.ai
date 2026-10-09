#!/usr/bin/env python3
"""Finite, preregistered offline comparison of refresh, horizon and risk sizing.

No broker imports, live writes or automatic promotion. Execution friction is an
assumption, never a statement of actual account charges.
"""
import argparse
from copy import copy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.quant_policy import PolicyModel, PolicySpec, integer_targets, normalize_bars, target_weights
from app.research.policy_replay import ExecutionConfig, ShareLedger, complete_universe, replay_day, summarize, fixed_order_cost_stress

TRADED = ("NVDA", "SNDK", "TSLA")
INPUTS = (*TRADED, "MSTR")


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exposure_metrics(daily, marks):
    close = pd.DataFrame(marks).query("phase == 'bar_close'")
    returns = pd.DataFrame(daily).net_return
    return dict(mean_gross_exposure=float(close.gross_exposure.mean()),
                mean_abs_net_exposure=float(close.net_exposure.abs().mean()),
                daily_return_std=float(returns.std(ddof=1)),
                mean_abs_daily_return=float(returns.abs().mean()),
                mean_daily_turnover=float(pd.DataFrame(daily).turnover_equity_multiple.mean()))


def run(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    frozen = PolicyModel.load(args.model)
    specs = [replace(frozen.spec, name="frozen_h1"),
             *[PolicySpec(f"daily_refit_h{h}", horizon_bars=h, risk_aversion=50) for h in (1, 3, 6)],
             PolicySpec("daily_refit_h1_risk10", horizon_bars=1, risk_aversion=10),
             replace(frozen.spec, name="equal_weight_session")]
    files = {s: Path(args.bars) / f"{s}.parquet" for s in INPUTS}
    sources = [Path(__file__), ROOT / "backend/app/quant_policy.py",
               ROOT / "backend/app/research/policy_replay.py",
               ROOT / "backend/app/research/causal_week_replay.py"]
    registration = dict(status="registered", registered_at=pd.Timestamp.now(tz="UTC").isoformat(),
        start=args.start, end=args.end, capital=args.capital, traded_symbols=TRADED,
        model_inputs=INPUTS, candidates=[asdict(s) for s in specs],
        training="Expanding prior full sessions; same 2026-08-10 starting history for all daily refits",
        execution="Completed-bar intent, next open, integer shares, existing 15:55 liquidation; 2 bps assumed friction",
        evaluation="Newly evaluated historical window, not prospective or untouched holdout",
        selection="Report all six candidates, no automatic live promotion; reduced risk aversion is an isolated sizing experiment",
        source_hashes={str(p.relative_to(ROOT)): digest(p) for p in sources},
        data_hashes={s: digest(p) for s, p in files.items()}, frozen_model_sha256=digest(Path(args.model)),
        limitations=["Yahoo OHLCV; no timestamped quotes, partial fills, borrow or latency reconstruction",
                    "Actual explicit fees and financing unverified; 0/2/5 bps are assumed friction scenarios",
                    "Contemporary three-stock universe, not point-in-time universe selection",
                    "Frozen model has different historical training window; refresh comparison includes that window difference",
                    "Risk10 is research only, same 95% gross and 70% single-name caps",
                    "Six short-window comparisons cannot establish persistent alpha"])
    write(out / "preregistration.json", registration)
    for p in sources:
        dest = out / "source" / p.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(p.read_bytes())
    frames = {s: normalize_bars(pd.read_parquet(p)) for s, p in files.items()}
    # Exchange calendar catches a missing full day, not just missing individual bars.
    import exchange_calendars as xcals
    dates = [str(d.date()) for d in xcals.get_calendar("XNYS").sessions_in_range(args.start, args.end)]
    sessions, _, coverage = complete_universe(frames, dates)
    write(out / "coverage.json", coverage)
    fit_cache, results = {}, {}
    for spec in specs:
        ledger = ShareLedger(list(TRADED), ExecutionConfig(starting_equity=args.capital, slippage_bps=2))
        daily, training = [], []
        for day in dates:
            model = None
            if spec.name != "equal_weight_session":
                if spec.name == "frozen_h1":
                    model = frozen
                else:
                    key = (spec.horizon_bars, day)
                    if key not in fit_cache:
                        fit_cache[key] = PolicyModel.fit(frames, day, spec)
                    model = copy(fit_cache[key])
                if model.trained_last_session >= day:
                    raise ValueError("Training overlaps evaluation")
                model = copy(model)
                model.spec = spec
                training.append(dict(date=day, last_training_session=model.trained_last_session))
                forecasts = model.forecast_frames({s: sessions[s][day] for s in model.symbols})
                indices = [model.symbols.index(s) for s in TRADED]
            bars = {s: sessions[s][day] for s in TRADED}
            index = bars[TRADED[0]].index

            def decide(i, current):
                mu = {s: float(forecasts[s].iloc[i]) for s in TRADED}
                cov = model.covariance_at(index[i])[np.ix_(indices, indices)]
                return target_weights(mu, cov, current, spec, symbols=TRADED,
                                      shortable=dict.fromkeys(TRADED, True))

            benchmark = spec.name == "equal_weight_session"
            daily.append(replay_day(ledger, bars, day, None if benchmark else decide,
                lambda w, p, e: integer_targets(w, p, e, spec),
                dict.fromkeys(TRADED, spec.gross_limit / len(TRADED)) if benchmark else None))
            print(spec.name, day, round(daily[-1]["net_pnl"], 2), flush=True)
        folder = out / spec.name
        folder.mkdir()
        for name, rows in (("daily", daily), ("fills", ledger.fills), ("marks", ledger.marks)):
            pd.DataFrame(rows).to_csv(folder / f"{name}.csv.gz", index=False, compression="gzip")
        write(folder / "training.json", training)
        result = dict(**summarize(daily, ledger.marks), **exposure_metrics(daily, ledger.marks),
            fixed_order_cost_stress={str(bps): fixed_order_cost_stress(ledger.fills, ledger.marks,
                ExecutionConfig(starting_equity=args.capital, slippage_bps=bps)) for bps in (0, 2, 5)},
            chronological_halves=[summarize(part, ledger.marks) for part in (daily[:len(daily)//2], daily[len(daily)//2:])])
        write(folder / "summary.json", result)
        results[spec.name] = result
        write(out / "progress.json", results)
    write(out / "registry.json", dict(**{**registration, "status": "complete"}, results=results,
        completed_at=pd.Timestamp.now(tz="UTC").isoformat()))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bars", required=True)
    p.add_argument("--model", default=str(ROOT / "reports/quant_research_20260913/selected_policy.json"))
    p.add_argument("--output", required=True)
    p.add_argument("--start", default="2026-09-15")
    p.add_argument("--end", default="2026-10-06")
    p.add_argument("--capital", type=float, default=47006.42)
    run(p.parse_args())
