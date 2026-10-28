#!/usr/bin/env python3
"""Export an auditable public signal explorer from an existing offline replay.

No models are fit and no orders are sent. Existing replay decisions, training
artifacts, prices, simulated holdings and fills are read without modification.
Forward price outcomes are added only as explicitly retrospective diagnostics.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import html
import json
import math
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
MODELS = ("A", "C", "B")
FEATURE_DETAILS = {
    "news_log_count": ("News volume", "log(1 + records)", "Source-associated news records available at this decision."),
    "futu_log_count": ("Futu volume", "log(1 + records)", "Observed Futu records; not a count of all retail investors."),
    "news_stance_balance": ("News keyword stance", "-1 to 1", "Limited keyword balance among scored single-company titles; not a return probability."),
    "futu_stance_balance": ("Futu keyword stance", "-1 to 1", "Limited keyword stance among scored records. Missing and ambiguous posts are not neutral votes."),
    "news_scored_fraction": ("News stance coverage", "fraction", "Fraction of eligible news records with a known keyword stance."),
    "futu_scored_fraction": ("Futu stance coverage", "fraction", "Fraction of eligible posts with a known keyword stance."),
    "unique_text_fraction": ("Distinct title fraction", "fraction", "Exact normalized title diversity; not independently verified event novelty."),
    "mean_publication_age_fraction": ("Publication age", "fraction of 48 hours", "Mean publication age, capped at the recorded lookback window."),
    "mean_receipt_age_fraction": ("Availability age", "fraction of 48 hours", "Mean age after verified receipt plus the declared simulated processing delay."),
    "any_text_missing": ("All text missing", "0 or 1", "One means no eligible text. Zero is not a neutral sentiment label."),
    "news_missing": ("News missing", "0 or 1", "One means no eligible news at this decision."),
    "futu_missing": ("Futu missing", "0 or 1", "One means no eligible Futu posts at this decision."),
}


def stamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timezone-aware timestamps required")
    return parsed


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()


def read_csv(path):
    with gzip.open(path, "rt") as stream:
        return list(csv.DictReader(stream))


def verify_path(path, expected, root):
    path = Path(path).resolve()
    if not path.is_relative_to((root / "reports").resolve()) or sha(path) != expected:
        raise ValueError("Saved source path or SHA256 does not match replay evidence")
    return path


def short_evidence(item, input_hashes, root, cache):
    """Read only a hash-allowlisted normalized row; never export its body/path."""
    path = Path(item["provenance"]["normalized_file"]).resolve()
    if str(path) not in input_hashes:
        raise ValueError("Evidence normalized source is absent from the capture audit")
    if path not in cache:
        verify_path(path, input_hashes[str(path)], root)
        cache[path] = json.loads(path.read_text())
    row = cache[path][item["provenance"]["normalized_row"]]
    title = clean(row.get("headline", row.get("title", "")))
    body = clean(row.get("text", row.get("excerpt", "")))
    digest = hashlib.sha256((title + "\n" + body).encode()).hexdigest()
    if digest != item["content_hash"]:
        raise ValueError("Evidence text differs from the saved decision version")
    public_title = title[:117] + "..." if len(title) > 120 else title
    return {"source": item["source"], "source_id": item["source_id"], "title": public_title,
            **{key: item[key] for key in ("published_at", "updated_at", "received_at", "available_at", "receipt_verified")}}


def explain_text(decision, calibration, effective_minutes, cap):
    names, values = calibration["feature_names"], decision["feature_vector"]
    if len(names) != len(values) or set(names) != set(FEATURE_DETAILS):
        raise ValueError("Unknown text feature schema")
    full_bps = float(decision["text_adjustment_full_30m"]) * 10000
    output = dict(has_text=bool(decision["has_text"]), primary_asof_eligible=bool(decision["has_text"]),
                  full_adjustment_bps=full_bps, effective_adjustment_bps=full_bps * effective_minutes / 30,
                  raw_adjustment_bps=None, intercept_bps=None, clip_adjustment_bps=None,
                  rounding_adjustment_bps=None, fallback_reason=decision["text_fallback"],
                  feature_values=dict(zip(names, values)), contributions=None, evidence_keys=[])
    if decision["text_fallback"] is not None:
        if full_bps != 0:
            raise ValueError("Fallback decision contains a nonzero text adjustment")
        return output
    if not decision["has_text"] or calibration["status"] != "fitted_development_only":
        raise ValueError("Applied text adjustment lacks text or fitted calibration")
    if stamp(calibration["training_cutoff"]) >= stamp(decision["decision_at"]):
        raise ValueError("Calibration is not prior to the decision")
    contributions = []
    for name, value, mean, scale, coefficient in zip(names, values, calibration["means"], calibration["scales"], calibration["weights"]):
        if scale <= 0:
            raise ValueError("Invalid training scale")
        standardized = (value - mean) / scale
        contributions.append(dict(feature=name, value=value, standardized=standardized,
                                  coefficient_bps=coefficient * 10000,
                                  contribution_bps=standardized * coefficient * 10000))
    intercept = calibration["intercept"] * 10000
    raw = intercept + sum(c["contribution_bps"] for c in contributions)
    clipped = max(-cap * 10000, min(cap * 10000, raw))
    rounding = full_bps - clipped
    # Decisions were serialized at ten decimal places in return units.
    if abs(rounding) > 0.000002:
        raise ValueError("Recorded text delta does not reconcile with frozen calibration")
    output.update(raw_adjustment_bps=raw, intercept_bps=intercept,
                  clip_adjustment_bps=clipped - raw, rounding_adjustment_bps=rounding,
                  contributions=contributions)
    return output


def realized_price_return(bars_by_start, decision_at, horizon_minutes):
    """Next open to the last included bar close; no returns past flatten time."""
    end = decision_at + timedelta(minutes=horizon_minutes)
    entry = bars_by_start.get(decision_at)
    final = bars_by_start.get(end - timedelta(minutes=5))
    if horizon_minutes <= 0 or entry is None or final is None:
        return None, None
    expected = decision_at
    while expected < end:
        if expected not in bars_by_start:
            return None, None
        expected += timedelta(minutes=5)
    return (final["close"] / entry["open"] - 1.0) * 10000, end.isoformat()


def price_bert_track(summary):
    """Describe a separate 2023 experiment without changing the replay series."""
    if (summary["schema_version"] != 1 or summary["model"] != "price_label_bert"
            or summary["evaluation_kind"] != "retrospective_development"
            or summary["test_start"] != "2023-09-01" or summary["horizon_sessions"] != 10
            or summary["target"] != "company minus SPY split-adjusted price return"
            or summary["promoted"] is not False or summary["alpha_established"] is not False):
        raise ValueError("Unsupported independent price-label BERT summary")
    steps, planned = summary["actual_optimizer_steps"], summary["planned_optimizer_steps"]
    if type(steps) is not int or type(planned) is not int or not 0 <= steps <= planned:
        raise ValueError("Invalid actual optimizer-step receipt")
    companies = summary["completed_companies"]
    if not isinstance(companies, list) or len(set(companies)) != len(companies) or not set(companies) <= {"A", "AMZN", "MSFT"}:
        raise ValueError("Invalid completed-company receipt")
    complete = summary["status"] == "complete"
    if summary["status"] not in {"complete", "incomplete"}:
        raise ValueError("Only finalized training summaries may be exported")
    trained = steps == planned and steps > 0 and set(companies) == {"A", "AMZN", "MSFT"}
    if complete and (not trained
                     or summary["heldout_predictions_completed"] is not True
                     or summary["heldout_outcomes_opened"] is not True
                     or {c["company"] for c in summary["cases"]} != set(companies)):
        raise ValueError("Completed training claim lacks actual training/evaluation evidence")
    for key in ("training_rows", "heldout_rows"):
        if type(summary[key]) is not int or summary[key] <= 0:
            raise ValueError("Invalid training/evaluation row count")
    status = ("Final-layer fine-tuning and evaluation completed" if complete else
              "Final-layer training complete; evaluation incomplete" if trained else "Training incomplete")
    return dict(id="transformer", label="Price-label BERT: separate 2023 experiment",
                status=status,
                as_of=stamp(summary["generated_at"]).astimezone(NY).date().isoformat(),
                detail=f"{steps}/{planned} real optimizer steps; {len(companies)} completed companies. "
                       "Universe: Agilent (A), Amazon (AMZN), Microsoft (MSFT); ticker A is not strategy A. "
                       f"Final encoder layer and regression head only; {summary['training_rows']} training rows and "
                       f"{summary['heldout_rows']} held-out rows. Target: 10-session company-minus-SPY split-adjusted "
                       "price return; split 2023-09-01. Independent 2023 retrospective experiment, not an input to "
                       "these 2026 A/C/B curves. No alpha established or live promotion.")


def build_export(comparison_dir, root=ROOT):
    directory, root = Path(comparison_dir), Path(root)
    registry = json.loads((directory / "registry.json").read_text())
    registration = json.loads((directory / "preregistration.json").read_text())
    source_audit = json.loads((directory / "text_source_audit.json").read_text())
    training = {row["date"]: row for row in json.loads((directory / "training.json").read_text())}
    if registry["status"] != "complete" or registry["evaluation_kind"] != "retrospective_development":
        raise ValueError("Only completed saved development comparisons are supported")
    with gzip.open(directory / "decisions.jsonl.gz", "rt") as stream:
        decisions = [json.loads(line) for line in stream]
    symbols, dates = list(registry["traded_symbols"]), sorted(training)
    decision_lookup = {(r["symbol"], stamp(r["decision_at"])): r for r in decisions}
    if len(decision_lookup) != len(decisions):
        raise ValueError("Duplicate saved decisions")
    marks, fills, input_files = {}, {}, [directory / n for n in ("registry.json", "preregistration.json", "training.json", "decisions.jsonl.gz", "text_source_audit.json")]
    for model in MODELS:
        folder = directory / "cost_2bps" / model
        input_files.extend([folder / "marks.csv.gz", folder / "fills.csv.gz"])
        marks[model] = {(r["date"], stamp(r["timestamp"])): r for r in read_csv(folder / "marks.csv.gz") if r["phase"] == "bar_close"}
        fills[model] = read_csv(folder / "fills.csv.gz")
    prices = {}
    for symbol in symbols:
        evidence = registry["prices"][symbol]
        current = verify_path(evidence["capture_file"], evidence["capture_sha256"], root)
        prior = verify_path(evidence["warmup_file"], evidence["warmup_sha256"], root)
        input_files.extend([current, prior])
        fresh, old = pd.read_parquet(current), pd.read_parquet(prior)
        frame = pd.concat([old.loc[old.index < fresh.index.min()], fresh]).sort_index()
        if frame.index.tz is None or frame.index.has_duplicates:
            raise ValueError("Price timestamps are ambiguous")
        frame.columns = [str(c).lower() for c in frame.columns]
        prices[symbol] = frame
    evidence_catalog, evidence_cache, series = {}, {}, []
    changed, default_selection = 0, None
    input_hashes = source_audit["input_sha256"]
    cap = registration["text"]["max_abs_return_adjustment"]
    for day in dates:
        for symbol in symbols:
            frame = prices[symbol]
            selected = frame.loc[frame.index.tz_convert(NY).date == datetime.fromisoformat(day).date()]
            expected = pd.date_range(f"{day} 09:30", periods=78, freq="5min", tz="America/New_York")
            if list(selected.index) != list(expected):
                raise ValueError("Explorer requires the same complete replay price session")
            bars = {index.to_pydatetime(): {k: float(row[k]) for k in ("open", "high", "low", "close", "volume")} for index, row in selected.iterrows()}
            points = []
            for bar_start, price in bars.items():
                at = bar_start + timedelta(minutes=5)
                decision = decision_lookup.get((symbol, at))
                point = dict(timestamp=at.isoformat(), bar_start=bar_start.isoformat(), price=price, has_decision=decision is not None, text=None)
                remaining = max(0, int((at.replace(hour=15, minute=55) - at).total_seconds() / 60))
                effective = min(30, remaining)
                if decision is not None:
                    text = explain_text(decision, training[day]["text"], effective, cap)
                    for item in decision["evidence"]:
                        if not item["receipt_verified"] or stamp(item["available_at"]) > at:
                            raise ValueError("Saved decision includes unavailable text")
                        key = item["source"] + ":" + item["source_id"] + ":" + item["content_hash"][:16]
                        public = short_evidence(item, input_hashes, root, evidence_cache)
                        if key in evidence_catalog and evidence_catalog[key] != public:
                            raise ValueError("Evidence version key collision")
                        evidence_catalog[key] = public
                        text["evidence_keys"].append(key)
                    if text["has_text"] != bool(text["evidence_keys"]):
                        raise ValueError("Text coverage and decision evidence disagree")
                    point["text"] = text
                    if abs(text["effective_adjustment_bps"]) > 1e-10:
                        changed += 1
                        if default_selection is None:
                            default_selection = {"symbol": symbol, "date": day}
                for model in MODELS:
                    mark = marks[model][(day, at)]
                    if not math.isclose(float(mark[f"{symbol}_price"]), price["close"], rel_tol=1e-9, abs_tol=1e-8):
                        raise ValueError("Replay mark and saved price differ")
                    nominal = 5 if model == "A" else 30
                    horizon = min(nominal, remaining) if decision is not None else None
                    forecast, realized, realized_end = None, None, None
                    if decision is not None:
                        forecast = decision["A_mu" if model == "A" else "C_mu"] * 10000
                        if model == "B":
                            forecast += point["text"]["effective_adjustment_bps"]
                        realized, realized_end = realized_price_return(bars, at, horizon)
                    point[model] = dict(forecast_bps=forecast, nominal_horizon_minutes=nominal,
                                        effective_horizon_minutes=horizon, shares=int(mark[f"{symbol}_shares"]),
                                        weight=float(mark[f"{symbol}_weight"]), realized_bps=realized,
                                        realized_end_at=realized_end)
                points.append(point)
            public_fills = [dict(model=model, timestamp=r["fill_time"], side=r["side"],
                                 quantity=int(r["quantity"]), fill_price=float(r["fill_price"]), reason=r["reason"])
                            for model in MODELS for r in fills[model] if r["date"] == day and r["symbol"] == symbol]
            public_fills.sort(key=lambda r: (r["timestamp"], r["model"]))
            calibration = training[day]["text"]
            series.append(dict(symbol=symbol, date=day, C_scale=training[day]["price"]["scale"],
                               text_calibration={k: calibration[k] for k in ("status", "reason", "training_text_rows", "training_sessions", "training_cutoff")},
                               points=points, fills=public_fills))
    receipt_dates = sorted({stamp(e["received_at"]).astimezone(NY).date().isoformat() for e in evidence_catalog.values()})
    mock_path = root / "reports/financial_sentiment_runs/daily_execution_20261027/acceptance_receipt.json"
    mock = json.loads(mock_path.read_text()) if mock_path.exists() else None
    tracks = [
        dict(id="A", label="Original price model A", status="Frozen model replayed", as_of=dates[-1], detail="Five-minute predictions and saved simulated holdings; no text inputs."),
        dict(id="C", label="Price-only control C", status="Prior-only daily calibration replayed", as_of=dates[-1], detail="Thirty-minute price model with earlier-session shrinkage and explicit near-close scaling."),
        dict(id="B", label="Price and text candidate B", status=training[dates[-1]]["text"]["status"], as_of=dates[-1], detail="Same-horizon residual adapter. A change in prediction does not necessarily change an order or establish alpha."),
    ]
    if mock is not None:
        input_files.append(mock_path)
        tracks.append(dict(id="transformer_mock_history", label="October 27 transformer pipeline rehearsal",
                           status="Historical mock receipt; no model training", as_of="2026-10-27",
                           detail=f"This retained historical receipt records {mock['optimizer_steps']} real optimizer steps "
                                  f"and {mock['completed_mock_day_step_markers']} mock day-step markers. "
                                  "Mock markers do not count as model training; this is not the latest model status."))
        if mock["optimizer_steps"] != 0 or mock["model_loaded"] is not False:
            raise ValueError("Historical mock receipt changed meaning")
    bert_summary = root / "reports/financial_sentiment_price_bert.json"
    if bert_summary.exists():
        input_files.append(bert_summary)
        tracks.append(price_bert_track(json.loads(bert_summary.read_text())))
    result = dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                  evaluation_kind="retrospective_development", cost_bps_per_side=2.0,
                  symbols=symbols, dates=dates, default_selection=default_selection or {"symbol": symbols[0], "date": dates[0]},
                  tracks=tracks,
                  feature_definitions=[dict(id=name, label=values[0], unit=values[1], detail=values[2]) for name, values in FEATURE_DETAILS.items()],
                  summary=dict(series_count=len(series), decision_count=len(decisions), changed_prediction_count=changed, distinct_receipt_dates=receipt_dates),
                  evidence=evidence_catalog, series=series,
                  limitations=[
                      "Saved retrospective development replay; this is not a live signal feed or a forecast made at the historical timestamp.",
                      "A predicts five minutes; C and B predict thirty minutes. Compare their forecast magnitudes and errors only at matching horizons.",
                      "Near the 15:55 exit, thirty-minute predictions and covariance use an explicit linear horizon-scaling assumption.",
                      "Displayed shares and weights are actual saved simulated holdings at bar close, not target allocations; markers are simulated fills.",
                      "Realized returns use a later next-open-to-end-close price window. They are retrospective gross diagnostics, not information available to the decision or portfolio PnL.",
                      "Text availability uses verified response receipt plus a simulated 60-second delay; the historical extraction/model execution clock was not recorded.",
                      "Feature contributions explain this linear model's arithmetic, not why a stock moved or whether text caused a profitable trade.",
                      "Multiple decision dates can reuse the same source batch. This replay has only " + str(len(receipt_dates)) + " distinct receipt dates among displayed evidence.",
                      "Missing text, unavailable calibration and unknown lexical stance are distinct states. Zero adjustment may mean a deliberate price-only fallback.",
                      "Short titles are evidence locators; article bodies, author/account identifiers and local file paths are excluded.",
                      "Only the 2 bps per-side replay is visualized here; the saved comparison separately retains the 5 bps stress replay.",
                  ])
    audit = dict(created_at=result["generated_at"], input_sha256={str(p.resolve()): sha(p) for p in input_files},
                 source_normalization_sha256={str(p): input_hashes[str(p)] for p in evidence_cache},
                 series=len(series), decisions=len(decisions), evidence_versions=len(evidence_catalog),
                 changed_symbol_predictions=changed, existing_replay_modified=False)
    return result, audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, default=ROOT / "reports/quant_logic_review_20261028/comparison_v1")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/financial_sentiment_signal_explorer.json")
    parser.add_argument("--audit-output", type=Path, default=ROOT / "reports/quant_logic_review_20261028/signal_explorer_export_audit.json")
    args = parser.parse_args(argv)
    if args.output.resolve().is_relative_to(args.comparison.resolve()) or args.audit_output.resolve().is_relative_to(args.comparison.resolve()):
        raise ValueError("Explorer outputs must not modify the frozen comparison directory")
    result, audit = build_export(args.comparison)
    # Standalone module validation does not import main_api, accounts or brokers.
    sys.path.insert(0, str(ROOT / "backend"))
    from app.financial_sentiment_signals import validate_public_signals
    result = validate_public_signals(result)
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    audit["public_sha256"] = sha(args.output)
    audit["public_bytes"] = args.output.stat().st_size
    gzip_output = args.output.with_suffix(args.output.suffix + ".gz")
    gzip_output.write_bytes(gzip.compress(payload.encode("utf-8"), compresslevel=5, mtime=0))
    audit["public_gzip_sha256"] = sha(gzip_output)
    audit["public_gzip_bytes"] = gzip_output.stat().st_size
    audit["generator_sha256"] = sha(Path(__file__))
    audit["validator_sha256"] = sha(ROOT / "backend/app/financial_sentiment_signals.py")
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "bytes": audit["public_bytes"], "gzip_bytes": audit["public_gzip_bytes"], **result["summary"]}))


if __name__ == "__main__":
    main()
