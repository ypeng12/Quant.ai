#!/usr/bin/env python3
"""Private market-data packet and bounded, broker-free cloud research replay.

The public repository contains code only. Input packets and detailed simulated
ledgers are stored in a private dataset. This never imports the API or runner.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
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
        source="Archived Yahoo OHLCV with fixed fresh-capture precedence; strict receipt features from frozen v1",
        private_dataset_only=True, contains_actual_account_transactions=False,
        contains_raw_news=False, contains_credentials=False,
        files={str(p.relative_to(out)): sha(p) for p in sorted(out.rglob("*")) if p.is_file()})
    write(out / "manifest.json", manifest)
    print(json.dumps(dict(packet=PACKET_ID, files=len(manifest["files"]),
        bytes=sum(p.stat().st_size for p in out.rglob("*") if p.is_file()), dates=len(manifest["dates"]))))


def verify_packet(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()) or sha(path) != expected:
            raise ValueError("Input manifest hash mismatch")
    if manifest["contains_actual_account_transactions"] or manifest["contains_credentials"]:
        raise ValueError("Account information is not an eligible cloud research input")
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


def execute(packet, destination):
    from app.research.profit_signal_candidates import CANDIDATES, ProfitSignalModel, SignalHoldingState, executable_open_labels, candidate_registry
    packet, out = Path(packet), Path(destination)
    manifest = verify_packet(packet)
    out.mkdir(parents=True, exist_ok=False)
    frames = {s: normalize_bars(pd.read_parquet(packet / f"{s}.parquet")) for s in INPUTS}
    dates = manifest["dates"]
    sessions, _, _ = complete_universe(frames, dates)
    started = time.monotonic()
    names = list(CANDIDATES)
    registration = dict(schema_version=1, experiment="fixed_signal_candidates_v2",
        registered_at=pd.Timestamp.now(tz="UTC").isoformat(),
        code_revision=os.environ.get("GITHUB_SHA", "local_fixture_only"),
        cloud_run_id=os.environ.get("GITHUB_RUN_ID"), packet_manifest_sha256=sha(packet / "manifest.json"),
        start=dates[0], end=dates[-1], sessions=len(dates), capital=50000.,
        candidates=names, candidate_specs=candidate_registry(), costs_bps_per_side=list(COSTS), primary_cost=5.,
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
    write(out / "registration.json", registration)
    results = {}
    for name in names:
        states = {cost:dict(ledger=ShareLedger(list(SYMBOLS), ExecutionConfig(
            starting_equity=50000., slippage_bps=cost)), daily=[], diagnostics=[]) for cost in COSTS}
        training = []
        forecast_audit = []
        for day in dates:
            model = ProfitSignalModel.fit(frames, day, CANDIDATES[name])
            day_frames = {s:sessions[s][day] for s in INPUTS}
            bars = {s:day_frames[s] for s in SYMBOLS}
            index = bars[SYMBOLS[0]].index
            forecasts = model.forecast_frames(day_frames)
            training.append(dict(date=day, audit=model.audit))
            for cost, record in states.items():
                holding_state = SignalHoldingState()
                def decide(i, current):
                    values = {s:{int(h):float(forecasts[s].iloc[i][h]) for h in forecasts[s]} for s in SYMBOLS}
                    weights, info = model.allocate(index[i], current, values,
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
        print(json.dumps(dict(completed_candidate=name, sessions=len(dates))), flush=True)
    baselines = {}
    for p in (packet / "baseline").rglob("summary.json"):
        baselines[str(p.relative_to(packet / "baseline").parent)] = json.loads(p.read_text())
    write(out / "summary.json", dict(registration=registration, candidates=results,
        frozen_baselines=baselines, duration_seconds=time.monotonic()-started,
        positive_at_primary_cost=[n for n in names if results[f"{n}/5bps"]["net_pnl"]>0],
        selected_for_live=False))
    from replay_sentiment_ablations import run_ablations
    decisions = pd.read_json(packet / "decisions.jsonl.gz", lines=True)
    training_receipts = json.loads((packet / "training.json").read_text())
    run_ablations(frames, decisions, training_receipts, dates,
        out / "text_ablations", frozen_root=packet / "baseline")
    print(json.dumps(dict(completed=True, elapsed_seconds=round(time.monotonic()-started,1))), flush=True)


def transfer(operation, repo, folder, revision=None):
    from huggingface_hub import HfApi, snapshot_download
    api = HfApi()
    info = api.repo_info(repo_id=repo, repo_type="dataset", revision=revision)
    if not info.private:
        raise ValueError("Research inputs and detailed outputs require a private dataset")
    if operation == "download":
        snapshot_download(repo_id=repo, repo_type="dataset", revision=revision,
            allow_patterns=f"{PACKET_ID}/input/*", local_dir=folder)
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
    args = parser.parse_args()
    if args.operation == "prepare": prepare(args.folder)
    elif args.operation == "run": execute(args.packet, args.folder)
    else: transfer(args.operation, args.repo, args.folder, args.revision)
