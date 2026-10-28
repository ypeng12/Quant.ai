#!/usr/bin/env python3
"""Audit saved execution evidence offline without importing trading services.

Output contains pseudonymous operation IDs, not broker/account identifiers.
FIFO results are conditional on zero opening inventory and complete fills;
neither the ledger nor these diagnostics establish actual account returns.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

BUY = {"BUY", "COVER", "PARTIAL_COVER", "PYRAMID_BUY", "TIER2_ADD_BUY"}
SELL = {"SELL", "SHORT", "PARTIAL_SELL", "PYRAMID_SHORT", "TIER2_ADD_SHORT"}


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_bounded(path: Path, timeout: float = 8) -> bytes:
    """An offloaded/unreadable source must not stall the complete audit."""
    result = subprocess.run(
        [sys.executable, "-c", "from pathlib import Path;import sys;sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())", str(path)],
        capture_output=True, check=True, timeout=timeout,
    )
    return result.stdout


def normalize(row: dict) -> dict:
    action = str(row.get("action", "")).upper()
    side = 1 if action in BUY else -1 if action in SELL else 0
    if not side or row.get("order_status") not in (None, "filled"):
        raise ValueError("Unknown side or non-final execution")
    qty, price = Decimal(str(row.get("shares"))), Decimal(str(row.get("price")))
    if not qty.is_finite() or not price.is_finite() or qty <= 0 or price <= 0:
        raise ValueError("Nonpositive/nonfinite execution")
    stamp = datetime.fromisoformat(row["time"])
    symbol = row["ticker"]
    signature = (symbol, stamp.isoformat(), side, str(qty.normalize()), str(price.normalize()))
    raw_identity = "order:" + str(row["order_id"]) if row.get("order_id") else "signature:" + json.dumps(signature)
    return {
        "operation_id": digest(raw_identity.encode())[:24], "signature": signature,
        "identity_basis": "broker_order" if row.get("order_id") else "unverified_signature",
        "symbol": symbol, "time": stamp.isoformat(), "date": stamp.date().isoformat(),
        "side": side, "qty": qty, "price": price,
        "accounting_status": row.get("accounting_status", "unverified"),
        "source_pnl_complete_claim": row.get("pnl_complete") is True,
        "recorded_pnl": row.get("pnl"),
        "forecast_present": all(k in row for k in ("expected_return", "prediction_at", "horizon")),
        "strategy_version_present": bool(row.get("strategy_version") or row.get("model_version")),
        "generic_reason": str(row.get("reason", "")).startswith("Alpaca Broker"),
        "explicit_fees_present": any(k in row for k in ("commission", "fee", "fees")),
    }


def deduplicate(sources: list[tuple[str, list[dict]]]) -> tuple[list[dict], dict]:
    groups, rejected = defaultdict(list), Counter()
    for source, rows in sources:
        for row in rows:
            try:
                item = normalize(row)
            except (ValueError, TypeError, KeyError, ArithmeticError):
                rejected[source] += 1
                continue
            item["source"] = source
            groups[item["operation_id"]].append(item)
    accepted, conflicts, duplicate_count = [], [], 0
    for identifier, copies in groups.items():
        if len({x["signature"] for x in copies}) != 1:
            conflicts.append({"operation_id": identifier, "copies": len(copies), "reason": "conflicting_order_snapshots_excluded"})
            continue
        # Prefer stronger accounting evidence, never add repeated snapshots.
        best = max(copies, key=lambda x: (x["source_pnl_complete_claim"], x["forecast_present"]))
        best["source_copies"] = len(copies)
        duplicate_count += len(copies) - 1
        accepted.append(best)
    accepted.sort(key=lambda x: (x["time"], x["operation_id"]))
    return accepted, {"duplicates_removed": duplicate_count, "conflicting_operations": conflicts,
                      "rejected_records_by_source": dict(rejected),
                      "signature_only_operations": sum(x["identity_basis"] == "unverified_signature" for x in accepted),
                      "signature_deduplication_cannot_verify_identity": True}


def conditional_fifo(rows: list[dict]) -> tuple[list[dict], dict]:
    lots, matches = defaultdict(deque), []
    for row in rows:
        remaining, side = row["qty"], row["side"]
        queue = lots[row["symbol"]]
        while remaining and queue and queue[0]["side"] != side:
            entry = queue[0]
            qty = min(remaining, entry["remaining"])
            gross = entry["side"] * (row["price"] - entry["price"]) * qty
            notional = (entry["price"] + row["price"]) * qty
            minutes = (datetime.fromisoformat(row["time"]) - datetime.fromisoformat(entry["time"])).total_seconds() / 60
            matches.append({
                "entry_operation_id": entry["operation_id"], "exit_operation_id": row["operation_id"],
                "symbol": row["symbol"], "entry_time": entry["time"], "exit_time": row["time"],
                "quantity": float(qty), "holding_minutes": minutes,
                "gross_price_pnl_conditional": float(gross),
                "cost_sensitivity": [{"assumed_bps_per_side": bps,
                    "conditional_pnl_after_assumed_cost": float(gross - notional * Decimal(bps) / 10000),
                    "positive_gross_erased_by_assumed_cost": 0 < gross <= notional * Decimal(bps) / 10000}
                    for bps in (2, 5, 10)],
                "classification": "adverse_realized_price_move" if gross < 0 else "favorable_realized_price_move" if gross > 0 else "flat_realized_price_move",
                "prediction_error_proven": False,
            })
            entry["remaining"] -= qty
            remaining -= qty
            if not entry["remaining"]:
                queue.popleft()
        if remaining:
            queue.append({**row, "remaining": remaining})
    residual = {symbol: float(sum(x["remaining"] * x["side"] for x in queue)) for symbol, queue in lots.items()}
    return matches, residual


def audit_action_logs(logs: list[str]) -> dict:
    """Retain logged claims without inventing model calibration or fill linkage."""
    parsed = []
    for raw in logs:
        stamp = re.search(r"^\[([^]]+)\]", raw)
        operation = re.search(r"\[([A-Z][A-Z0-9.-]*)\]\s*(BUY|SELL|SHORT|COVER)\s*×\s*([\d.]+)", raw)
        expected = re.search(r"E\[PnL\]=([+-]?[\d.]+)R", raw)
        probability = re.search(r"P_win=([\d.]+)%", raw)
        if not all((stamp, operation, expected)):
            continue
        parsed.append({"log_id": digest(raw.encode())[:24], "time": stamp[1], "symbol": operation[1],
            "action": operation[2], "quantity": float(operation[3]), "logged_expected_r": float(expected[1]),
            "logged_win_score_pct": float(probability[1]) if probability else None,
            "entry_submission_message": "Submitting Order" in raw and operation[2] in ("BUY", "SHORT"),
            "forecast_calibration_verified": False, "link_to_actual_fill_verified": False})
    entries = [r for r in parsed if r["entry_submission_message"]]
    return {"raw_log_count": len(logs), "parsed_log_count": len(parsed),
        "days_present": sorted({r["time"][:10] for r in parsed}),
        "entry_submission_messages": len(entries),
        "entries_with_negative_logged_expectation": sum(r["logged_expected_r"] < 0 for r in entries),
        "entries_with_nonpositive_logged_expectation": sum(r["logged_expected_r"] <= 0 for r in entries),
        "entries_with_logged_win_score_below_50": sum(r["logged_win_score_pct"] is not None and r["logged_win_score_pct"] < 50 for r in entries),
        "entries": entries,
        "interpretation": "Negative logged expectation at entry is an internal-consistency review candidate. A score below 50% alone does not imply negative expectancy. These logs do not identify the current model version, calibrated probability, prediction horizon, or confirmed fill; do not attribute them to current policy automatically."}


def build_audit(sources: list[tuple[str, list[dict]]], start: str, end: str) -> dict:
    rows, dedup = deduplicate(sources)
    timestamp_sides = defaultdict(set)
    for row in rows:
        timestamp_sides[(row["symbol"], row["time"])].add(row["side"])
    dedup["same_timestamp_opposite_side_groups"] = sum(len(sides) > 1 for sides in timestamp_sides.values())
    matches, residual = conditional_fifo(rows)
    selected = [r for r in rows if start <= r["date"] <= end]
    selected_matches = [r for r in matches if start <= r["exit_time"][:10] <= end]
    by_exit = defaultdict(list)
    for match in selected_matches:
        by_exit[match["exit_operation_id"]].append(match)
    operations = []
    for row in selected:
        closing = by_exit[row["operation_id"]]
        operations.append({
            "operation_id": row["operation_id"], "time": row["time"], "symbol": row["symbol"],
            "side": "buy" if row["side"] == 1 else "sell", "quantity": float(row["qty"]),
            "fill_price": float(row["price"]), "source_copies": row["source_copies"],
            "identity_basis": row["identity_basis"], "source_accounting_status": row["accounting_status"],
            "source_pnl_complete_claim": row["source_pnl_complete_claim"],
            "recorded_pnl_not_account_return": row["recorded_pnl"],
            "conditional_matched_price_pnl": sum(x["gross_price_pnl_conditional"] for x in closing) if closing else None,
            "classifications": {
                "prediction_error": "unverifiable_without_original_forecast_horizon_and_input_snapshot",
                "direction_right_but_cost_insufficient": "scenario_only" if any(c["positive_gross_erased_by_assumed_cost"] for m in closing for c in m["cost_sensitivity"]) else "not_established",
                "turnover": "short_holding_review_candidate" if any(m["holding_minutes"] <= 5 for m in closing) else "not_classified_as_error",
                "execution_error": "unverifiable_without_arrival_quote_and_submission_timestamps",
                "missing_evidence": [name for name, exists in (("original_forecast", row["forecast_present"]), ("strategy_version", row["strategy_version_present"]), ("explicit_fees", row["explicit_fees_present"])) if not exists],
            },
        })
    return {
        "schema_version": "quant-decision-audit-1", "requested_start": start, "requested_end_inclusive": end,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_saved_execution_evidence_only", "actual_account_return_verified": False,
        "opening_inventory_verified": False, "fill_completeness_verified": False,
        "broker_paper_or_live_account_type_verified": False, "fees_verified": False,
        "timestamp_timezone": "source_naive_timestamps; original exchange timezone not encoded",
        "all_history_first": min((r["date"] for r in rows), default=None),
        "all_history_last": max((r["date"] for r in rows), default=None),
        "coverage": {"unique_operations_in_window": len(selected), "days_with_records": sorted({r["date"] for r in selected}),
                     "daily_counts": dict(sorted(Counter(r["date"] for r in selected).items())),
                     "generic_broker_reasons": sum(r["generic_reason"] for r in selected),
                     "original_forecasts_available": sum(r["forecast_present"] for r in selected),
                     "strategy_versions_available": sum(r["strategy_version_present"] for r in selected),
                     "recorded_complete_pnl_claims": sum(r["source_pnl_complete_claim"] for r in selected)},
        "deduplication": dedup, "conditional_fifo_assumption": "Zero inventory at first saved execution, complete fills thereafter, no verified fees; matched lots are not independent trades.",
        "conditional_fifo_net_quantity_changes": residual,
        "conditional_matched_lots_in_window": len(selected_matches),
        "conditional_gross_price_pnl_in_window": sum(r["gross_price_pnl_conditional"] for r in selected_matches),
        "conditional_outcomes": dict(Counter(r["classification"] for r in selected_matches)),
        "short_holding_matched_lots_le_5min": sum(r["holding_minutes"] <= 5 for r in selected_matches),
        "cost_sensitivity": [{"assumed_bps_per_side": bps,
            "gross_winners_erased_by_assumed_cost": sum(r["cost_sensitivity"][i]["positive_gross_erased_by_assumed_cost"] for r in selected_matches),
            "conditional_matched_pnl_after_assumed_cost": sum(r["cost_sensitivity"][i]["conditional_pnl_after_assumed_cost"] for r in selected_matches)} for i, bps in enumerate((2, 5, 10))],
        "operations": operations, "conditional_matches": selected_matches,
        "limitations": ["No-record days cannot be interpreted as zero trades or zero profit.",
            "A losing realization does not prove an irrational decision or forecast error.",
            "FIFO is an accounting pairing, not a reconstructed strategy decision or independently verified round trip.",
            "Equal-time opposite-side orders use deterministic ID ordering; execution chronology is unavailable and FIFO lot allocation may differ.",
            "No deposits, withdrawals, dividends, financing, opening equity, marked inventory or complete broker statement: actual account return unavailable.",
            "No claim that unavailable historic sentiment would have prevented any particular loss."],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--start", default="2026-09-01")
    parser.add_argument("--end", default="2026-10-28")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Choose a fresh output file; existing audit is immutable")
    root = args.root.resolve()
    files = [root / "backend/trade_history.json", root / "backend/data/datasets/trade_history_archive.json"]
    files += sorted((root / "backend/data/datasets/daily_archives").glob("trades_*.json"))
    sources, provenance, action_logs = [], [], []
    for path in files:
        entry = {"path": str(path.relative_to(root))}
        try:
            raw = load_bounded(path)
            data = json.loads(raw)
            rows = data["trade_history"]
            if path == root / "backend/trade_history.json":
                action_logs = [item for item in data.get("action_logs", []) if isinstance(item, str)
                               and args.start <= item[1:11] <= args.end]
            entry.update(sha256=digest(raw), records=len(rows), status="read")
            sources.append((entry["path"], rows))
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            entry.update(status="unavailable", error_type=type(exc).__name__)
        provenance.append(entry)
    if not sources:
        raise ValueError("No readable execution evidence")
    audit = build_audit(sources, args.start, args.end)
    audit["audit_script_sha256"] = digest(Path(__file__).read_bytes())
    audit["action_log_evidence"] = audit_action_logs(action_logs)
    audit["source_files"] = provenance
    audit["source_files_unavailable"] = sum(s["status"] != "read" for s in provenance)
    audit["bar_manifests"] = []
    for name in ("reports/quant_audit_20260912/bars/manifest.json", "reports/alpha_refresh_20261007/bars/manifest.json"):
        path = root / name
        try:
            raw = load_bounded(path)
            data = json.loads(raw)
            audit["bar_manifests"].append({"path": name, "sha256": digest(raw), "status": "manifest_only_not_new_download",
                "symbols": {symbol: {k: item.get(k) for k in ("first", "last", "regular_rows", "interval", "sha256")} for symbol, item in data.items()}})
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            audit["bar_manifests"].append({"path": name, "status": "unavailable", "error_type": type(exc).__name__})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(audit, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    args.output.chmod(0o600)
    print(json.dumps({k: audit[k] for k in ("coverage", "source_files_unavailable", "all_history_first", "all_history_last", "conditional_outcomes", "short_holding_matched_lots_le_5min")}, indent=2))


if __name__ == "__main__":
    main()
