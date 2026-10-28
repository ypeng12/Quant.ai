#!/usr/bin/env python3
"""Frozen A / improved price C / price-plus-text B, offline and time ordered.

No broker imports, live configuration writes, or strategy promotion. The old
artifact cannot be evaluated before its training cutoff. All comparisons are
retrospective development evidence, including the simulated processing delay.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd
import exchange_calendars as xcals

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "research/financial_sentiment_using_prices"))
from app.quant_policy import PolicyModel, integer_targets, labeled_frame, normalize_bars, target_weights
from app.research.policy_replay import ExecutionConfig, ShareLedger, complete_universe, replay_day, summarize
from app.research.sentiment_alpha_candidate import PriceCandidate, TextReturnAdjustment, FIXED_SPEC
from quant_signal_adapter import (load_default_archives, build_asof_features,
    fit_residual_calibration, SentimentResidualAdapter, STRICT_MODE)

TRADED = ("NVDA", "SNDK", "TSLA")
INPUTS = (*TRADED, "MSTR")


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def calendar_dates(start, end):
    return [str(d.date()) for d in xcals.get_calendar("XNYS").sessions_in_range(start, end)]


def merge_prices(warmup_dir, capture_dir):
    frames, evidence = {}, {}
    for symbol in INPUTS:
        old_path, new_path = warmup_dir / f"{symbol}.parquet", capture_dir / f"{symbol}.parquet"
        old = normalize_bars(pd.read_parquet(old_path))
        new = normalize_bars(pd.read_parquet(new_path))
        overlap = old.index.intersection(new.index)
        differences = int((~np.isclose(old.loc[overlap].to_numpy(), new.loc[overlap].to_numpy(),
                                        rtol=1e-9, atol=1e-9)).any(axis=1).sum()) if len(overlap) else 0
        # Source precedence is set by date, never by observed returns.
        merged = pd.concat([old.loc[old.index < new.index.min()], new]).sort_index()
        if merged.index.has_duplicates:
            raise ValueError("Duplicate price timestamps")
        frames[symbol] = merged
        evidence[symbol] = dict(warmup_file=str(old_path), capture_file=str(new_path),
            warmup_sha256=digest(old_path), capture_sha256=digest(new_path),
            rows=len(merged), first=merged.index.min().isoformat(), last=merged.index.max().isoformat(),
            overlap_rows=len(overlap), revised_overlap_rows=differences,
            precedence="fresh Yahoo capture from its first timestamp; earlier archived Yahoo warmup")
    return frames, evidence


def diagnostic(daily, marks):
    close = pd.DataFrame(marks).query("phase == 'bar_close'")
    net = np.array([row["net_pnl"] for row in daily])
    return dict(mean_gross_exposure=float(close.gross_exposure.mean()),
                mean_abs_net_exposure=float(close.net_exposure.abs().mean()),
                mean_daily_turnover=float(np.mean([r["turnover_equity_multiple"] for r in daily])),
                pnl_excluding_best_day=float(net.sum() - net.max()),
                profitable_sessions=int((net > 0).sum()))


def run(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    model_path = Path(args.model)
    old = PolicyModel.load(model_path)
    if args.start < old.trained_before:
        raise ValueError("Old A's fit contains requested evaluation dates")
    frames, price_evidence = merge_prices(Path(args.warmup), Path(args.capture))
    dates = calendar_dates(args.start, args.end)
    sessions, _, coverage = complete_universe(frames, dates)
    observations, source_audit = load_default_archives(ROOT)
    source_paths = [Path(__file__), ROOT / "backend/app/research/sentiment_alpha_candidate.py",
        ROOT / "research/financial_sentiment_using_prices/quant_signal_adapter.py",
        ROOT / "backend/app/quant_policy.py", ROOT / "backend/app/research/policy_replay.py"]
    registration = dict(schema_version=1, status="registered", registered_at=pd.Timestamp.now(tz="UTC").isoformat(),
        requested_start=args.start, requested_end=args.end, starting_capital=args.capital,
        traded_symbols=TRADED, model_input_symbols=INPUTS, old_model_sha256=digest(model_path),
        A="Frozen original price_volume_h1_g50; no text",
        C=asdict(FIXED_SPEC), B="C plus prior-only same-30-minute text residual calibration",
        text=dict(mode=STRICT_MODE, lookback_hours=48, processing_delay_seconds=60,
            minimum_text_rows=100, minimum_sessions=5, minimum_nonoverlapping_intervals=30,
            ridge_alpha=10.0, max_abs_return_adjustment=0.0005,
            missing_policy="exact price-only C fallback; no invented neutral score"),
        training="Daily, prior complete days only; C base excludes its five-day calibration window. B uses earlier walk-forward C residuals only.",
        execution="Completed five-minute bar to next open; integer shares; flat at 15:55; common 95% gross/70% name limits",
        cost_scenarios_bps_per_side=[2.0, 5.0],
        cost_stress="Separate full cash/position replays at each execution cost; planning cost remains frozen at 2 bps in all models",
        evaluation_kind="retrospective_development", selected_for_live=False,
        source_hashes={str(p.relative_to(ROOT)): digest(p) for p in source_paths}, prices=price_evidence,
        limitations=["Not a complete reconstruction of actual brokerage performance.",
            "Yahoo historical OHLCV revisions, simulated arrival/processing and next-open fills; no verified live latency.",
            "Execution costs are assumptions; actual spreads, impact, borrow and financing are not reconstructed.",
            "Current three-stock universe; no claim of point-in-time universe selection.",
            "A and C differ in horizon, refresh and shrinkage; only B minus C isolates the text adapter.",
            "Price forecast gates and text sample gates are engineering rules, not proof of statistical significance.",
            "This interval includes previously inspected data; no blind-test or guaranteed-profit claim."])
    write(out / "preregistration.json", registration)
    write(out / "coverage.json", coverage)
    write(out / "text_source_audit.json", source_audit)
    for p in source_paths:
        dst = out / "source" / p.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
    states = {}
    for cost in (2.0, 5.0):
        for name in ("A", "C", "B", "equal_weight"):
            states[(cost, name)] = dict(ledger=ShareLedger(list(TRADED),
                ExecutionConfig(starting_equity=args.capital, slippage_bps=cost)), daily=[])
    examples, training_receipts, decision_rows = [], [], []
    counts, fallback = Counter(), Counter()
    old_indices = [old.symbols.index(s) for s in TRADED]
    for day in dates:
        candidate = PriceCandidate.fit(frames, day, traded_symbols=TRADED)
        day_inputs = {s: sessions[s][day] for s in INPUTS}
        bars = {s: sessions[s][day] for s in TRADED}
        index = bars[TRADED[0]].index
        old_predictions = old.forecast_frames({s: day_inputs[s] for s in old.symbols})
        price_predictions = candidate.forecast_frames(day_inputs)
        cutoff = pd.Timestamp(day, tz="America/New_York").isoformat()
        calibration = fit_residual_calibration(examples, cutoff, target_horizon_minutes=30)
        adapter = SentimentResidualAdapter(calibration, target_horizon_minutes=30, max_abs_adjustment=0.0005)
        snapshots, adjustments = {}, {}
        for i in range(76):
            at = index[i] + pd.Timedelta(minutes=5)
            changed = False
            for symbol in TRADED:
                snap = build_asof_features(observations, symbol, at.isoformat(), mode=STRICT_MODE,
                                          lookback_hours=48, processing_delay_seconds=60)
                result = adapter.predict(float(price_predictions[symbol].iloc[i]), snap)
                snapshots[(i, symbol)], adjustments[(i, symbol)] = snap, result
                counts["symbol_decisions"] += 1
                counts["usable_decisions"] += int(snap["has_text"])
                counts["changed_symbol_decisions"] += int(result["text_changed_prediction"])
                fallback[str(result["fallback_reason"])] += 1
                changed |= result["text_changed_prediction"]
                decision_rows.append(dict(date=day, decision_at=at.isoformat(), symbol=symbol,
                    A_mu=float(old_predictions[symbol].iloc[i]), C_mu=float(price_predictions[symbol].iloc[i]),
                    text_adjustment_full_30m=result["adjustment"], has_text=snap["has_text"],
                    evidence=snap["evidence"], feature_vector=snap["feature_vector"],
                    text_fallback=result["fallback_reason"], C_scale=candidate.scale))
            counts["changed_decisions"] += int(changed)
            counts["portfolio_decisions"] += 1
        for cost in (2.0, 5.0):
            for name in ("A", "C", "B", "equal_weight"):
                state = states[(cost, name)]
                def decide(i, current):
                    if name == "A":
                        return target_weights({s: float(old_predictions[s].iloc[i]) for s in TRADED},
                            old.covariance_at(index[i])[np.ix_(old_indices, old_indices)],
                            current, old.spec, symbols=TRADED, shortable=dict.fromkeys(TRADED, True))
                    text_adjustment = None
                    if name == "B":
                        text_adjustment = TextReturnAdjustment(
                            returns={s: adjustments[(i, s)]["adjustment"] for s in TRADED},
                            available_at=(index[i] + pd.Timedelta(minutes=5)).isoformat(), horizon_bars=6)
                    return candidate.weights(index[i], current,
                        {s: float(price_predictions[s].iloc[i]) for s in TRADED},
                        shortable=dict.fromkeys(TRADED, True), text_adjustment=text_adjustment)
                spec = old.spec if name == "A" else candidate.spec
                state["daily"].append(replay_day(state["ledger"], bars, day,
                    None if name == "equal_weight" else decide,
                    lambda w, p, e: integer_targets(w, p, e, spec),
                    dict.fromkeys(TRADED, 0.95 / len(TRADED)) if name == "equal_weight" else None))
        # Labels are appended only after the day's predictions/replays. The next
        # day's fit additionally enforces decision and label maturity timestamps.
        for symbol in TRADED:
            _, labels = labeled_frame(day_inputs[symbol], candidate.spec)
            for i in range(76):
                if not pd.notna(labels.iloc[i]):
                    continue
                examples.append(dict(snapshot=snapshots[(i, symbol)],
                    base_prediction=float(price_predictions[symbol].iloc[i]), realized_return=float(labels.iloc[i]),
                    label_start_at=(index[i] + pd.Timedelta(minutes=5)).isoformat(),
                    label_end_at=(index[i] + pd.Timedelta(minutes=35)).isoformat(), target_horizon_minutes=30))
        training_receipts.append(dict(date=day, price=candidate.audit, text=calibration))
        print(json.dumps(dict(day=day, scale=round(candidate.scale, 4), text_status=calibration["status"],
            pnl={n: round(states[(2.0, n)]["daily"][-1]["net_pnl"], 2) for n in ("A", "C", "B") })), flush=True)
        write(out / "progress.json", dict(last_completed_day=day, counts=dict(counts)))
    results = {}
    for (cost, name), state in states.items():
        folder = out / f"cost_{cost:g}bps" / name
        folder.mkdir(parents=True)
        for kind, rows in (("daily", state["daily"]), ("fills", state["ledger"].fills), ("marks", state["ledger"].marks)):
            pd.DataFrame(rows).to_csv(folder / f"{kind}.csv.gz", index=False, compression="gzip")
        result = {**summarize(state["daily"], state["ledger"].marks), **diagnostic(state["daily"], state["ledger"].marks)}
        write(folder / "summary.json", result)
        results[f"{cost:g}bps_{name}"] = result
    write(out / "training.json", training_receipts)
    pd.DataFrame(decision_rows).to_json(out / "decisions.jsonl.gz", orient="records", lines=True, compression="gzip")
    models_dir = out / "models"
    models_dir.mkdir()
    shutil.copy2(model_path, models_dir / "old_A.json")
    candidate.base.save(models_dir / "new_B_price_base.json")
    write(models_dir / "new_B.json", dict(kind="research_price_text_candidate_v1", price=candidate.audit,
        price_base_file="new_B_price_base.json", price_base_sha256=digest(models_dir / "new_B_price_base.json"),
        price_scale=candidate.scale, text_calibration=calibration,
        text_source_mode=STRICT_MODE, text_adjustment_cap=0.0005, selected_for_live=False,
        note="Last evaluated day's candidate; not retrained on its outcomes; use the offline runner, not live_runner."))
    text_report = dict(source_records=len(observations), **dict(counts), fallback_counts=dict(fallback),
        calibration_status=calibration["status"], fallback_reason=calibration.get("reason"),
        final_training_text_rows=calibration["training_text_rows"], final_training_sessions=calibration["training_sessions"],
        primary_asof_mode=STRICT_MODE, actual_historical_model_run_verified=False)
    registry = {**registration, "status": "complete", "completed_at": pd.Timestamp.now(tz="UTC").isoformat(),
                "results": results, "text": text_report}
    write(out / "registry.json", registry)
    export_public(out, registry, states, dates)


def export_public(out, registry, states, dates):
    descriptions = {
        "A": ("Old model A", "Frozen five-minute price model"),
        "C": ("Price-only control C", "Daily refreshed 30-minute model with prior-window shrinkage"),
        "B": ("New candidate B", "Improved price model plus time-audited text residual adapter"),
    }
    models = []
    for name in ("A", "B", "C"):
        r = registry["results"][f"2bps_{name}"]
        models.append(dict(id=name, name=descriptions[name][0], description=descriptions[name][1],
            **{k: r[k] for k in ["net_pnl", "net_return", "max_drawdown", "costs", "fill_count", "mean_gross_exposure", "mean_daily_turnover"]}))
    curves = [dict(date=day, **{name: states[(2.0, name)]["daily"][i]["ending_equity"] for name in ("A", "B", "C")})
              for i, day in enumerate(dates)]
    payload = dict(schema_version=1, generated_at=registry["completed_at"], evaluation_kind="retrospective_development",
        requested_start=dates[0], requested_end=dates[-1], evaluated_start=dates[0], evaluated_end=dates[-1],
        sessions=len(dates), starting_capital=registry["starting_capital"], currency="USD", models=models,
        curves=curves, text={k: registry["text"][k] for k in ["source_records", "usable_decisions", "changed_decisions", "calibration_status", "fallback_reason"]},
        coverage=dict(complete_requested_period=True, missing_sessions=[]),
        limitations=registry["limitations"] + [
            "Main chart assumes 2 bps execution friction per side. Full 5 bps replays are in the local report.",
            "September 1-11 is excluded because old A was trained through September 11.",
            "Complete replay coverage does not mean complete two-month brokerage records.",
            "Two-week company prediction remains a separate task; no ten-day return is added to the intraday forecast."], promoted=False)
    write(out / "public_comparison.json", payload)
    write(ROOT / "reports/financial_sentiment_strategy_comparison.json", payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warmup", default=str(ROOT / "reports/alpha_refresh_20261007/bars"))
    parser.add_argument("--capture", default=str(ROOT / "reports/quant_logic_review_20261028/yahoo_capture"))
    parser.add_argument("--model", default=str(ROOT / "reports/quant_research_20260913/selected_policy.json"))
    parser.add_argument("--start", default="2026-09-14")
    parser.add_argument("--end", default="2026-10-27")
    parser.add_argument("--capital", type=float, default=50_000.0)
    parser.add_argument("--output", required=True)
    run(parser.parse_args())
