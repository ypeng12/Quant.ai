#!/usr/bin/env python3
"""Private market-data packet and bounded, broker-free cloud research replay.

The public repository contains code only. Input packets and detailed simulated
ledgers are stored in a private dataset. This never imports the API or runner.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from app.quant_policy import integer_targets, normalize_bars
from app.research.policy_replay import ExecutionConfig, ShareLedger, complete_universe, replay_day, summarize

SYMBOLS = ("NVDA", "SNDK", "TSLA")
INPUTS = (*SYMBOLS, "MSTR")
COSTS = (2., 5., 10.)
PACKET_ID = "profitability_v2_20261028"
FIRST_RUN = "40788629742"
REFRESH_RUN = "40790388222"
PACKET_SOURCE = "Archived Yahoo OHLCV with fixed fresh-capture precedence; strict receipt features from frozen v1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")


def prepare(destination):
    """Local packaging only; no model fitting or parameter search."""
    from run_quant_sentiment_comparison import merge_prices
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=False)
    frames, _ = merge_prices(ROOT / "reports/alpha_refresh_20261007/bars",
                             ROOT / "reports/quant_logic_review_20261028/yahoo_capture")
    frozen = ROOT / "reports/quant_logic_review_20261028/comparison_v1"
    registration = json.loads((frozen / "preregistration.json").read_text())
    for symbol, frame in frames.items():
        frame.to_parquet(out / f"{symbol}.parquet")
    # No titles, bodies, account transactions, credentials, or absolute paths.
    rows = []
    with gzip.open(frozen / "decisions.jsonl.gz", "rt") as source:
        for line in source:
            row = json.loads(line)
            evidence_ids = sorted({hashlib.sha256((str(e["source"])+":"+str(e["source_id"])+":"+
                str(e["content_hash"])).encode()).hexdigest() for e in row.get("evidence", [])})
            safe = {k: row[k] for k in ("date", "decision_at", "symbol", "A_mu", "C_mu",
                "text_adjustment_full_30m", "has_text", "feature_vector", "text_fallback", "C_scale")}
            safe["evidence_signature"] = hashlib.sha256(json.dumps(evidence_ids).encode()).hexdigest()
            safe["evidence_ids"] = evidence_ids
            safe["event_ids"] = sorted({hashlib.sha256((str(e["source"])+":"+str(e["source_id"])).encode()).hexdigest()
                                        for e in row.get("evidence", [])})
            rows.append(safe)
    with gzip.open(out / "decisions.jsonl.gz", "wt") as handle:
        for row in rows:
            handle.write(json.dumps(row, allow_nan=False) + "\n")
    shutil.copy2(frozen / "training.json", out / "training.json")
    for cost in (2, 5):
        for name in ("A", "B", "C", "equal_weight"):
            source = frozen / f"cost_{cost}bps" / name
            target = out / "baseline" / f"cost_{cost}bps" / name
            target.mkdir(parents=True)
            for filename in ("summary.json", "daily.csv.gz", "fills.csv.gz"):
                if (source / filename).exists():
                    shutil.copy2(source / filename, target / filename)
    manifest = dict(schema_version=1, packet_id=PACKET_ID,
        prepared_at=pd.Timestamp.now(tz="UTC").isoformat(),
        input_symbols=list(INPUTS), traded_symbols=list(SYMBOLS), starting_capital=50000.,
        start=registration["requested_start"], end=registration["requested_end"],
        dates=sorted({r["date"] for r in rows}), evaluation_kind="already_inspected_retrospective_development",
        source=PACKET_SOURCE,
        private_dataset_only=True, contains_actual_account_transactions=False,
        contains_raw_news=False, contains_credentials=False,
        files={str(p.relative_to(out)): sha(p) for p in sorted(out.rglob("*")) if p.is_file()})
    write(out / "manifest.json", manifest)
    verify_packet(out)
    print(json.dumps(dict(packet=PACKET_ID, files=len(manifest["files"]),
        bytes=sum(p.stat().st_size for p in out.rglob("*") if p.is_file()), dates=len(manifest["dates"]))))


def verify_packet(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    fields = {"schema_version", "packet_id", "prepared_at", "input_symbols", "traded_symbols",
              "starting_capital", "start", "end", "dates", "evaluation_kind", "source",
              "private_dataset_only", "contains_actual_account_transactions", "contains_raw_news",
              "contains_credentials", "files"}
    if not isinstance(manifest, dict) or set(manifest) != fields:
        raise ValueError("Fixed packet manifest schema fields mismatch")
    if (not isinstance(manifest["prepared_at"], str)
            or pd.Timestamp(manifest["prepared_at"]).tz is None
            or pd.isna(pd.Timestamp(manifest["prepared_at"]))
            or manifest["source"] != PACKET_SOURCE):
        raise ValueError("Packet capture provenance metadata is invalid")
    required = {f"{symbol}.parquet" for symbol in INPUTS} | {"decisions.jsonl.gz", "training.json"}
    required |= {f"baseline/cost_{cost}bps/{name}/{filename}"
                 for cost in (2, 5) for name in ("A", "B", "C", "equal_weight")
                 for filename in ("summary.json", "daily.csv.gz", "fills.csv.gz")}
    expected_dates = pd.bdate_range("2026-09-14", "2026-10-27").strftime("%Y-%m-%d").tolist()
    # This fixed packet covers 32 regular sessions with no weekday exchange
    # holiday in its declared interval. This is not a generic market calendar.
    if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or manifest.get("packet_id") != PACKET_ID
            or manifest.get("input_symbols") != list(INPUTS)
            or manifest.get("traded_symbols") != list(SYMBOLS)
            or type(manifest.get("starting_capital")) not in (int, float)
            or manifest["starting_capital"] != 50000.0
            or manifest.get("start") != expected_dates[0]
            or manifest.get("end") != expected_dates[-1]
            or manifest.get("dates") != expected_dates
            or manifest.get("evaluation_kind") != "already_inspected_retrospective_development"):
        raise ValueError("Fixed packet schema, universe, capital or date contract mismatch")
    if (manifest.get("private_dataset_only") is not True
            or any(manifest.get(flag) is not False for flag in
                   ("contains_actual_account_transactions", "contains_credentials", "contains_raw_news"))):
        raise ValueError("Private numeric packet privacy flags must be explicit booleans")
    if not isinstance(manifest.get("files"), dict) or set(manifest["files"]) != required:
        raise ValueError("Manifest must bind exactly the 30 required numeric input files")
    actual = {str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file()}
    if actual != required | {"manifest.json"}:
        raise ValueError("Packet contains missing or unmanifested files")
    for name, expected in manifest["files"].items():
        path = (folder / name).resolve()
        if (not isinstance(expected, str) or len(expected) != 64
                or any(c not in "0123456789abcdef" for c in expected)
                or not path.is_relative_to(folder.resolve()) or sha(path) != expected):
            raise ValueError("Input manifest hash mismatch")
    return manifest


def statistics(daily, ledger):
    result = summarize(daily, ledger.marks)
    values = np.asarray([r["net_pnl"] for r in daily])
    close = [m for m in ledger.marks if m["phase"] == "bar_close"]
    result.update(mean_gross_exposure=float(np.mean([m["gross_exposure"] for m in close])),
        pnl_excluding_best_day=float(values.sum() - values.max()),
        pnl_excluding_best_three_days=float(values.sum() - np.sort(values)[-3:].sum()),
        gross_profit_to_cost=(result["gross_pnl"] / result["costs"] if result["costs"] else None),
        best_day=float(values.max()), worst_day=float(values.min()),
        per_symbol={s:float(sum(d[f"{s}_net_pnl"] for d in daily)) for s in SYMBOLS},
        weekly_pnl={str(k):float(v) for k,v in pd.Series(values,
            index=pd.to_datetime([d["date"] for d in daily])).groupby(
                lambda x: str(x.to_period("W-FRI"))).sum().items()})
    # A day is the resampling unit, not a bar. This is descriptive development
    # uncertainty, not a search-adjusted p-value or proof of future profits.
    rng = np.random.default_rng(61028)
    draws = rng.choice(values, size=(2000, len(values)), replace=True).sum(axis=1)
    result["day_bootstrap_net_pnl_interval_95"] = np.quantile(draws, [.025,.975]).tolist()
    return result


def execute(packet, destination, experiment="entry_bound"):
    """Persist overall state; publish complete summary only after all components."""
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=False)
    progress = dict(status="running", stage="validating_packet",
                    started_at=pd.Timestamp.now(tz="UTC").isoformat(),
                    completed_candidates=[], candidate_completed_dates={})

    def update_progress(**changes):
        progress.update(changes)
        progress["updated_at"] = pd.Timestamp.now(tz="UTC").isoformat()
        write(out / "progress.json", progress)

    update_progress()
    try:
        report = (_execute(packet, out, update_progress) if experiment == "entry_bound"
                  else _execute(packet, out, update_progress, experiment=experiment))
        if report.get("status") != "complete" or report.get("text_ablations_status") != "complete":
            raise ValueError("Overall completion requires completed text ablations")
        write(out / "summary.json", report)
        update_progress(status="complete", stage="complete", completed_at=pd.Timestamp.now(tz="UTC").isoformat())
        print(json.dumps(dict(completed=True, elapsed_seconds=round(report["duration_seconds"],1))), flush=True)
        return report
    except BaseException as exc:
        update_progress(status="failed", stage_at_failure=progress["stage"],
                        error_type=type(exc).__name__, complete_summary_available=False)
        raise


def _execute(packet, destination, update_progress, experiment="entry_bound"):
    from app.research.profit_signal_candidates import CANDIDATES, ProfitSignalModel, SignalHoldingState, executable_open_labels, candidate_registry
    packet, out = Path(packet), Path(destination)
    manifest = verify_packet(packet)
    frames = {s: normalize_bars(pd.read_parquet(packet / f"{s}.parquet")) for s in INPUTS}
    dates = manifest["dates"]
    sessions, _, _ = complete_universe(frames, dates)
    started = time.monotonic()
    if experiment not in ("entry_bound", "refresh_price", "macro_context"):
        raise ValueError("Unknown fixed experiment")
    definitions = CANDIDATES
    builder = None
    context_audit = None
    costs = COSTS if experiment != "macro_context" else (5., 10.)
    if experiment in ("refresh_price", "macro_context"):
        from app.research.profit_signal_candidates import REFRESH_CANDIDATES
        definitions = REFRESH_CANDIDATES
    if experiment == "macro_context":
        from app.research.macro_price_context import make_macro_feature_builder
        names = ("ridge30_single_refresh_price", "ridge30_plan_refresh_price")
        definitions = {"macro_"+n:replace(REFRESH_CANDIDATES[n],name="macro_"+n) for n in names}
        source = packet.parent / "macro_context/market_daily.json"
        if sha(source) != "93b330d286ef097a18f539fcba1d961f6ecd6e1643b312759b79812b849c4525":
            raise ValueError("Registered market context capture hash differs")
        builder = make_macro_feature_builder(frames, json.loads(source.read_text()), evaluation_end="2026-10-27")
        context_audit = dict(builder.audit, source_sha256=sha(source))
    names = list(definitions)
    fixed_forecasts = {}
    forecast_sources = {}
    if experiment == "refresh_price":
        for name in names:
            path = packet.parent / "results" / FIRST_RUN / name.removesuffix("_refresh_price") / "cost_5bps/decisions.jsonl.gz"
            with gzip.open(path, "rt") as handle:
                rows = [json.loads(line) for line in handle]
            if len(rows) != len(dates)*76:
                raise ValueError("Frozen forecast row coverage differs")
            fixed_forecasts[name] = rows
            forecast_sources[name] = sha(path)
    registration = dict(schema_version=1, experiment="fixed_signal_candidates_v2_"+experiment,
        registered_at=pd.Timestamp.now(tz="UTC").isoformat(),
        code_revision=os.environ.get("GITHUB_SHA", "local_fixture_only"),
        cloud_run_id=os.environ.get("GITHUB_RUN_ID"), packet_manifest_sha256=sha(packet / "manifest.json"),
        start=dates[0], end=dates[-1], sessions=len(dates), capital=50000.,
        candidates=names, candidate_specs={name:asdict(value) for name,value in definitions.items()},
        costs_bps_per_side=list(costs), primary_cost=5., macro_context_audit=context_audit,
        frozen_forecast_source_hashes=forecast_sources,
        package_versions={name:importlib.metadata.version(name) for name in
            ("numpy", "pandas", "scipy", "scikit-learn", "osqp", "pyarrow")},
        main_comparison="identical 50k capital, dates, universe, next-open integer ledger, 95% gross and 70% name cap",
        controls="A/B/C retained from immutable v1; new optimizer costs match each execution-cost scenario",
        training="every decision day uses only earlier matured labels; no parameter search or outcome-selected candidate",
        evaluation_kind=manifest["evaluation_kind"], selected_for_live=False,
        source_hashes={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),
            ROOT/"backend/app/research/profit_signal_candidates.py",
            ROOT/"backend/app/research/policy_replay.py", ROOT/"backend/app/research/direction_policy.py"]},
        limitations=["Already inspected development period, not independent validation.",
            "Current universe is not a point-in-time security master.",
            "OHLCV next-open execution and costs are assumptions, with no market-impact/borrow verification.",
            "An expiry or active-trading rule is an experiment, not proof of alpha.",
            "All candidates reported; no automatic promotion or order submission."])
    extra_sources = ([ROOT/"backend/app/research/macro_price_context.py",
                      ROOT/"research/financial_sentiment_using_prices/macro_context_protocol.json"]
                     if experiment == "macro_context" else
                     [ROOT/"research/financial_sentiment_using_prices/price_clock_diagnostic_protocol.json"]
                     if experiment == "refresh_price" else
                     [ROOT/"research/financial_sentiment_using_prices/profitability_v2_protocol.json"])
    registration["source_hashes"].update({str(p.relative_to(ROOT)):sha(p) for p in extra_sources})
    write(out / "registration.json", registration)
    if experiment == "refresh_price":
        from probe_sentiment_reproduction import run_probe
        run_probe(packet, out / "reproduction_probe")
    results = {}
    completed_candidates, completed_dates = [], {}
    for name in names:
        completed_dates[name] = []
        update_progress(stage="running_candidates", current_candidate=name,
                        completed_candidates=list(completed_candidates), candidate_completed_dates=completed_dates)
        states = {cost:dict(ledger=ShareLedger(list(SYMBOLS), ExecutionConfig(
            starting_equity=50000., slippage_bps=cost)), daily=[], diagnostics=[]) for cost in costs}
        training = []
        forecast_audit = []
        for day in dates:
            model = (ProfitSignalModel.fit(frames, day, definitions[name]) if builder is None
                     else ProfitSignalModel.fit(frames, day, definitions[name], feature_builder=builder))
            day_frames = {s:sessions[s][day] for s in INPUTS}
            bars = {s:day_frames[s] for s in SYMBOLS}
            index = bars[SYMBOLS[0]].index
            forecasts = model.forecast_frames(day_frames)
            refit_difference = None
            if experiment == "refresh_price":
                rows = [r for r in fixed_forecasts[name] if r["date"] == day]
                frozen_index = pd.DatetimeIndex([pd.Timestamp(r["decision_at"])-pd.Timedelta(minutes=5) for r in rows]).tz_convert("America/New_York")
                if not frozen_index.equals(index[:76]):
                    raise ValueError("Frozen price predictions must match every completed decision bar")
                frozen = {s:pd.DataFrame([{int(h):v for h,v in r["forecasts"][s].items()} for r in rows],
                                         index=frozen_index) for s in SYMBOLS}
                refit_difference = max(float(np.max(np.abs(forecasts[s].loc[frozen_index].to_numpy()-frozen[s].to_numpy())))
                                       for s in SYMBOLS)
                if refit_difference > 1e-12:
                    raise ValueError("Paired price forecasts differ beyond numerical precision")
                # The holding-clock pair consumes the exact original Python JSON
                # values, not a refit's nearly identical floating-point outputs.
                forecasts = frozen
            training.append(dict(date=day, audit=model.audit, max_abs_refit_vs_frozen_forecast=refit_difference))
            for cost, record in states.items():
                holding_state = SignalHoldingState()
                def decide(i, current):
                    values = {s:{int(h):float(forecasts[s].iloc[i][h]) for h in forecasts[s]} for s in SYMBOLS}
                    model_input = (model.forecast_snapshot(forecasts, index[i])
                                   if experiment in ("refresh_price", "macro_context") else values)
                    weights, info = model.allocate(index[i], current, model_input,
                        state=holding_state, cost_bps=cost)
                    record["diagnostics"].append(dict(date=day, decision_at=(index[i]+pd.Timedelta(minutes=5)).isoformat(),
                        forecasts=values, current=current, target=weights, explanation=info))
                    return weights
                record["daily"].append(replay_day(record["ledger"], bars, day, decide, integer_targets))
            # Ex-post diagnostics only, after every cost arm has completed this
            # day's decisions. These outcomes never enter allocation/selection.
            for symbol in SYMBOLS:
                for horizon in forecasts[symbol]:
                    labels, ends = executable_open_labels(bars[symbol], int(horizon))
                    for stamp in labels.index[labels.notna()]:
                        forecast_audit.append(dict(date=day, symbol=symbol, horizon=int(horizon),
                            decision_at=(stamp+pd.Timedelta(minutes=5)).isoformat(),
                            label_end=ends.loc[stamp].isoformat(),
                            predicted=float(forecasts[symbol].loc[stamp,horizon]), actual=float(labels.loc[stamp])))
            completed_dates[name].append(day)
            update_progress(current_date=day, candidate_completed_dates=completed_dates)
        write(out / name / "training.json", training)
        audit = pd.DataFrame(forecast_audit)
        audit.to_csv(out / name / "forecast_audit.csv.gz", index=False)
        accuracy = []
        for (symbol, horizon), group in audit.groupby(["symbol", "horizon"]):
            p, y = group.predicted.to_numpy(), group.actual.to_numpy()
            accuracy.append(dict(symbol=symbol, horizon=int(horizon), overlapping_rows=len(p),
                mae_bps=float(np.mean(np.abs(p-y))*10000), zero_mae_bps=float(np.mean(np.abs(y))*10000),
                direction_accuracy=float(np.mean(np.sign(p)==np.sign(y))),
                correlation=(float(np.corrcoef(p,y)[0,1]) if np.std(p)>0 and np.std(y)>0 else None),
                mean_prediction_bps=float(p.mean()*10000), mean_actual_bps=float(y.mean()*10000),
                predicted_above_roundtrip_10bps_fraction=float(np.mean(np.abs(p)>.001))))
        write(out / name / "forecast_quality.json", accuracy)
        for cost, record in states.items():
            target = out / name / f"cost_{int(cost)}bps"
            target.mkdir(parents=True)
            result = statistics(record["daily"], record["ledger"])
            pd.DataFrame(record["daily"]).to_csv(target / "daily.csv", index=False)
            pd.DataFrame(record["ledger"].fills).to_csv(target / "fills.csv.gz", index=False)
            # Detailed action diagnostics stay private; public logs contain only aggregate progress.
            with gzip.open(target / "decisions.jsonl.gz", "wt") as h:
                for row in record["diagnostics"]: h.write(json.dumps(row, allow_nan=False) + "\n")
            write(target / "summary.json", result)
            results[f"{name}/{int(cost)}bps"] = result
        completed_candidates.append(name)
        update_progress(completed_candidates=list(completed_candidates))
        print(json.dumps(dict(completed_candidate=name, sessions=len(dates))), flush=True)
    baselines = {}
    for p in (packet / "baseline").rglob("summary.json"):
        baselines[str(p.relative_to(packet / "baseline").parent)] = json.loads(p.read_text())
    report = dict(status="partial", registration=registration, candidates=results,
        frozen_baselines=baselines, duration_seconds=time.monotonic()-started,
        positive_at_primary_cost=[n for n in names if results[f"{n}/5bps"]["net_pnl"]>0],
        text_ablations_status="pending", selected_for_live=False)
    write(out / "summary.partial.json", report)
    if experiment in ("refresh_price", "macro_context"):
        previous = packet.parent / "results" / FIRST_RUN
        old = json.loads((previous / "summary.json").read_text())
        text_receipt = json.loads((previous / "text_ablations/summary.json").read_text())
        if (text_receipt.get("status") != "complete" or
                old["registration"]["code_revision"] != "ea86c7ea9be535322abed6624dc5455af2e51ca0" or
                old["registration"]["packet_manifest_sha256"] != sha(packet / "manifest.json")):
            raise ValueError("Prior paired comparison receipt mismatch")
        pairs = {}
        for name in (names if experiment == "refresh_price" else []):
            base = name.removesuffix("_refresh_price")
            for cost in costs:
                key = f"{name}/{int(cost)}bps"
                before = old["candidates"][f"{base}/{int(cost)}bps"]
                after = results[key]
                pairs[key] = {field:after[field]-before[field] for field in
                    ("net_pnl", "gross_pnl", "costs", "fill_count", "mean_gross_exposure")}
        if experiment == "macro_context":
            context_control_path = packet.parent / "results" / REFRESH_RUN / "summary.json"
            control = json.loads(context_control_path.read_text())
            if (control.get("status") != "complete" or
                    control["registration"]["code_revision"] != "51591441acfd7669694879ab1cb3cccf09a9871f" or
                    control["registration"]["packet_manifest_sha256"] != sha(packet/"manifest.json")):
                raise ValueError("Macro comparison control receipt mismatch")
            for name in names:
                for cost in costs:
                    key = f"{name}/{int(cost)}bps"
                    before = control["candidates"][f"{name.removeprefix('macro_')}/{int(cost)}bps"]
                    after = results[key]
                    pairs[key] = {field:after[field]-before[field] for field in
                        ("net_pnl", "gross_pnl", "costs", "fill_count", "mean_gross_exposure")}
            report["context_control_summary_sha256"] = sha(context_control_path)
        report.update(status="complete", text_ablations_status="complete",
            text_ablations_execution="Reused prior complete receipt; not rerun in the price-clock diagnostic",
            prior_text_reproduction_passed=text_receipt["frozen_reproduction_passed"],
            prior_result_sha256=sha(previous / "summary.json"), paired_differences=pairs,
            prior_entry_bound_results=old["candidates"],
            context_comparison_run=("40790388222" if experiment == "macro_context" else None),
            duration_seconds=time.monotonic()-started, completed_at=pd.Timestamp.now(tz="UTC").isoformat())
        return report
    update_progress(stage="running_text_ablations")
    from replay_sentiment_ablations import run_ablations
    decisions = pd.read_json(packet / "decisions.jsonl.gz", lines=True)
    training_receipts = json.loads((packet / "training.json").read_text())
    text_result = run_ablations(frames, decisions, training_receipts, dates,
        out / "text_ablations", frozen_root=packet / "baseline")
    saved_text = json.loads((out / "text_ablations/summary.json").read_text())
    if text_result.get("status") != "complete" or saved_text.get("status") != "complete":
        raise ValueError("Text ablation completion receipt is missing or incomplete")
    report.update(status="complete", text_ablations_status="complete",
                  text_ablations_summary_sha256=sha(out / "text_ablations/summary.json"),
                  duration_seconds=time.monotonic()-started, completed_at=pd.Timestamp.now(tz="UTC").isoformat())
    return report


def transfer(operation, repo, folder, revision=None):
    from huggingface_hub import HfApi, snapshot_download
    api = HfApi()
    info = api.repo_info(repo_id=repo, repo_type="dataset", revision=revision)
    if not info.private:
        raise ValueError("Research inputs and detailed outputs require a private dataset")
    if operation == "download":
        snapshot_download(repo_id=repo, repo_type="dataset", revision=revision,
            allow_patterns=[f"{PACKET_ID}/input/*", f"{PACKET_ID}/results/{FIRST_RUN}/summary.json",
                            f"{PACKET_ID}/results/{FIRST_RUN}/text_ablations/summary.json",
                            f"{PACKET_ID}/results/{FIRST_RUN}/*/cost_5bps/decisions.jsonl.gz",
                            f"{PACKET_ID}/results/{REFRESH_RUN}/summary.json",
                            f"{PACKET_ID}/macro_context/market_daily.json"], local_dir=folder)
    else:
        run = os.environ.get("GITHUB_RUN_ID", "manual")
        api.upload_folder(repo_id=repo, repo_type="dataset", folder_path=folder,
            path_in_repo=f"{PACKET_ID}/results/{run}", commit_message="Bounded offline signal research results")
        print(json.dumps(dict(uploaded=True, run_id=run)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "run", "download", "upload"])
    parser.add_argument("--folder", required=True)
    parser.add_argument("--packet")
    parser.add_argument("--repo", default="Ypeng12/quant-research-compute")
    parser.add_argument("--revision")
    parser.add_argument("--experiment", choices=["entry_bound", "refresh_price", "macro_context"], default="entry_bound")
    args = parser.parse_args()
    if args.operation == "prepare": prepare(args.folder)
    elif args.operation == "run": execute(args.packet, args.folder, args.experiment)
    else: transfer(args.operation, args.repo, args.folder, args.revision)
