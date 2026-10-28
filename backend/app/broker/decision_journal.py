"""Private append-only decision receipts; no broker/config/network imports."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re

TEXT_FIELDS = {"kind", "decision_id", "model_name", "model_sha256", "trained_before",
               "bar_open_at", "signal_cutoff_at", "broker_clock_at", "client_order_id",
               "symbol", "side", "status", "broker_order_ref", "blocked_reason", "intent_reason"}
NUMBER_FIELDS = {"horizon_minutes", "assumed_cost_bps_per_side", "quantity"}
BOOL_FIELDS = {"cost_verified", "text_applied", "reducing", "submission_success"}
NUMBER_MAPS = {"expected_gross_return_bps", "current_weights", "target_weights", "target_shares", "bar_close_prices"}
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")


def pseudonym(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def project_record(payload):
    """Allowlist receipts; account identifiers and arbitrary diagnostics drop."""
    record = {"schema_version": 1}
    if payload.get("kind") not in {"decision", "order_intent", "order_result", "blocked_submission"}:
        raise ValueError("Unknown decision receipt kind")
    for key in TEXT_FIELDS:
        if key in payload:
            value = payload[key]
            if not isinstance(value, str) or len(value) > 256 or any(ord(c) < 32 for c in value):
                raise ValueError("Invalid receipt text")
            record[key] = value
    for key in NUMBER_FIELDS:
        if key in payload:
            value = payload[key]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Invalid receipt number")
            record[key] = value
    for key in BOOL_FIELDS:
        if key in payload:
            if type(payload[key]) is not bool:
                raise ValueError("Invalid receipt flag")
            record[key] = payload[key]
    for key in NUMBER_MAPS:
        if key in payload:
            values = payload[key]
            if (not isinstance(values, dict) or any(not SYMBOL.fullmatch(s) for s in values)
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in values.values())):
                raise ValueError("Invalid symbol-number map")
            record[key] = values
    if "input_sha256" in payload:
        values = payload["input_sha256"]
        if (not isinstance(values, dict) or any(not SYMBOL.fullmatch(s) for s in values)
                or any(not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for v in values.values())):
            raise ValueError("Invalid input hashes")
        record["input_sha256"] = values
    if not record.get("decision_id"):
        raise ValueError("Decision receipt requires a correlation ID")
    record["recorded_at"] = datetime.now(timezone.utc).isoformat()
    record["historical_gap_backfilled"] = False
    return record


def append_receipt(directory, payload):
    record = project_record(payload)
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / f"decisions-{record['recorded_at'][:10]}.jsonl"
    body = (json.dumps(record, sort_keys=True, allow_nan=False) + "\n").encode()
    if len(body) > 128_000:
        raise ValueError("Decision receipt is unexpectedly large")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "ab") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    return {"status": "recorded", "kind": record["kind"], "decision_id": record["decision_id"],
            "recorded_at": record["recorded_at"]}
