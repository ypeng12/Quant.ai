"""Read-only, allowlisted public signal-explorer snapshot.

Importing this module does not import the trading application or model code.
"""
from datetime import date, datetime, timedelta
from functools import lru_cache
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import threading
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, Response

PUBLIC_SIGNALS_PATH = Path(__file__).resolve().parents[2] / "reports" / "financial_sentiment_signal_explorer.json"
router = APIRouter()
MAX_PUBLIC_BYTES = 25_000_000
LOCAL_PATH = re.compile(r"file:/{1,3}|/(?:Users|home|tmp|private|var|etc|Volumes)/|\b[A-Za-z]:[\\/]")
NY = ZoneInfo("America/New_York")
_CACHE_LOCK = threading.Lock()
_CACHE = None


def _obj(value):
    if not isinstance(value, dict):
        raise ValueError("Object required")
    return value


def _rows(value, maximum=500):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("Bounded list required")
    return value


def _text(value, maximum=1000, nullable=False):
    if value is None and nullable:
        return None
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or LOCAL_PATH.search(value) or any(ord(c) < 32 for c in value)):
        raise ValueError("Bounded public text required")
    return value


def _num(value, minimum=None, nullable=False):
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or (minimum is not None and value < minimum):
        raise ValueError("Finite number required")
    return value


def _integer(value, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError("Integer required")
    return value


def _bool(value):
    if type(value) is not bool:
        raise ValueError("Boolean required")
    return value


def _date(value):
    value = _text(value, 10)
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("ISO date required")
    return value


def _timestamp(value, nullable=False):
    if value is None and nullable:
        return None
    value = _text(value, 64)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Aware timestamp required")
    return value


@lru_cache(maxsize=8192)
def _time(value):
    return datetime.fromisoformat(_timestamp(value).replace("Z", "+00:00"))


def _symbol(value):
    value = _text(value, 15)
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", value):
        raise ValueError("Symbol required")
    return value


def _close(left, right, tolerance=0.000002):
    if not math.isclose(left, right, abs_tol=tolerance, rel_tol=1e-9):
        raise ValueError("Signal arithmetic does not reconcile")


def _model(value, model, point_time, has_decision):
    value = _obj(value)
    nominal = _integer(value["nominal_horizon_minutes"], 1)
    if nominal != (5 if model == "A" else 30):
        raise ValueError("Wrong model horizon")
    horizon = value["effective_horizon_minutes"]
    if horizon is not None:
        horizon = _integer(horizon, 1)
        if horizon > nominal or horizon % 5:
            raise ValueError("Invalid effective horizon")
    result = dict(forecast_bps=_num(value["forecast_bps"], nullable=True),
                  nominal_horizon_minutes=nominal, effective_horizon_minutes=horizon,
                  shares=_integer(value["shares"]), weight=_num(value["weight"]),
                  realized_bps=_num(value["realized_bps"], nullable=True),
                  realized_end_at=_timestamp(value["realized_end_at"], nullable=True))
    if has_decision != (result["forecast_bps"] is not None and horizon is not None):
        raise ValueError("Decision and forecast availability disagree")
    if has_decision:
        local = point_time.astimezone(NY)
        remaining = int((local.replace(hour=15, minute=55, second=0, microsecond=0) - local).total_seconds() / 60)
        if horizon != min(nominal, max(0, remaining)):
            raise ValueError("Effective horizon differs from the registered flatten policy")
    if not has_decision and (horizon is not None or result["forecast_bps"] is not None or result["realized_bps"] is not None):
        raise ValueError("Non-decision bar cannot carry a signal")
    if (result["realized_bps"] is None) != (result["realized_end_at"] is None):
        raise ValueError("Missing realized outcome must remain null")
    if result["realized_end_at"] is not None:
        endpoint = _time(result["realized_end_at"])
        local = point_time.astimezone(NY)
        flatten = local.replace(hour=15, minute=55, second=0, microsecond=0)
        if horizon is None or endpoint != point_time + timedelta(minutes=horizon) or endpoint > flatten:
            raise ValueError("Realized horizon is inconsistent")
    return result


def _text_signal(value, features, evidence, at, horizon):
    value = _obj(value)
    result = {key: _bool(value[key]) for key in ("has_text", "primary_asof_eligible")}
    result.update({key: _num(value[key]) for key in ("full_adjustment_bps", "effective_adjustment_bps")})
    result.update({key: _num(value[key], nullable=True) for key in ("raw_adjustment_bps", "intercept_bps", "clip_adjustment_bps", "rounding_adjustment_bps")})
    result["fallback_reason"] = _text(value["fallback_reason"], 200, nullable=True)
    source_features = _obj(value["feature_values"])
    if set(source_features) != set(features):
        raise ValueError("Feature-vector schema mismatch")
    result["feature_values"] = {name: _num(source_features[name]) for name in features}
    result["evidence_keys"] = [_text(key, 200) for key in _rows(value["evidence_keys"], 500)]
    if len(result["evidence_keys"]) != len(set(result["evidence_keys"])):
        raise ValueError("Duplicate evidence key")
    if result["has_text"] != bool(result["evidence_keys"]) or result["primary_asof_eligible"] != result["has_text"]:
        raise ValueError("Text eligibility and evidence disagree")
    for key in result["evidence_keys"]:
        if key not in evidence or not evidence[key]["receipt_verified"] or _time(evidence[key]["available_at"]) > at:
            raise ValueError("Unavailable text in a strict as-of signal")
    _close(result["effective_adjustment_bps"], result["full_adjustment_bps"] * horizon / 30)
    if abs(result["full_adjustment_bps"]) > 5.000002:
        raise ValueError("Text adjustment exceeds registered 5bp cap")
    contributions = value["contributions"]
    result["contributions"] = None
    if contributions is None:
        if result["fallback_reason"] is None or result["full_adjustment_bps"] != 0 or any(result[k] is not None for k in ("raw_adjustment_bps", "intercept_bps", "clip_adjustment_bps", "rounding_adjustment_bps")):
            raise ValueError("Unavailable contribution must preserve fallback state")
    else:
        if result["fallback_reason"] is not None or not result["has_text"]:
            raise ValueError("Contributions require an applied eligible signal")
        result["contributions"] = []
        for item in _rows(contributions, 100):
            item = _obj(item)
            name = _text(item["feature"], 100)
            if name not in features:
                raise ValueError("Unknown contribution feature")
            row = {"feature": name, **{k: _num(item[k]) for k in ("value", "standardized", "coefficient_bps", "contribution_bps")}}
            _close(row["value"], result["feature_values"][name], 1e-10)
            _close(row["contribution_bps"], row["standardized"] * row["coefficient_bps"], 1e-8)
            result["contributions"].append(row)
        if [r["feature"] for r in result["contributions"]] != features:
            raise ValueError("Contribution coverage/order mismatch")
        if any(result[k] is None for k in ("raw_adjustment_bps", "intercept_bps", "clip_adjustment_bps", "rounding_adjustment_bps")):
            raise ValueError("Incomplete contribution decomposition")
        _close(sum(r["contribution_bps"] for r in result["contributions"]) + result["intercept_bps"], result["raw_adjustment_bps"])
        _close(max(-5, min(5, result["raw_adjustment_bps"])) - result["raw_adjustment_bps"], result["clip_adjustment_bps"])
        _close(result["raw_adjustment_bps"] + result["clip_adjustment_bps"] + result["rounding_adjustment_bps"], result["full_adjustment_bps"])
        if abs(result["rounding_adjustment_bps"]) > .000002:
            raise ValueError("Unexpected serialization error")
    return result


def validate_public_signals(data):
    """Recursive allowlist with chronology, horizon and contribution invariants."""
    data = _obj(data)
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["evaluation_kind"] != "retrospective_development" or data["cost_bps_per_side"] != 2:
        raise ValueError("Unsupported signal snapshot")
    symbols = [_symbol(v) for v in _rows(data["symbols"], 20)]
    dates = [_date(v) for v in _rows(data["dates"], 200)]
    if not symbols or len(set(symbols)) != len(symbols) or not dates or dates != sorted(set(dates)):
        raise ValueError("Unique symbols and chronological dates required")
    definitions = [{"id": _text(_obj(v)["id"], 100), "label": _text(v["label"], 150), "unit": _text(v["unit"], 100), "detail": _text(v["detail"], 600)} for v in _rows(data["feature_definitions"], 100)]
    features = [v["id"] for v in definitions]
    if len(features) != len(set(features)) or not features:
        raise ValueError("Unique feature definitions required")
    evidence = {}
    raw_evidence = _obj(data["evidence"])
    if len(raw_evidence) > 2000:
        raise ValueError("Too much public evidence")
    for key, raw in raw_evidence.items():
        key, raw = _text(key, 200), _obj(raw)
        row = dict(source=_text(raw["source"], 10), source_id=_text(raw["source_id"], 128), title=_text(raw["title"], 120),
                   receipt_verified=_bool(raw["receipt_verified"]),
                   **{k: _timestamp(raw[k]) for k in ("published_at", "updated_at", "received_at", "available_at")})
        if row["source"] not in {"news", "futu"} or not row["receipt_verified"]:
            raise ValueError("Unsupported evidence source or receipt")
        if _time(row["updated_at"]) < _time(row["published_at"]) or _time(row["available_at"]) < max(_time(row[k]) for k in ("published_at", "updated_at", "received_at")) + timedelta(seconds=60):
            raise ValueError("Evidence availability contradicts its timestamps")
        evidence[key] = row
    series, series_ids, decision_count, changed_count = [], set(), 0, 0
    for raw in _rows(data["series"], 1000):
        raw = _obj(raw)
        symbol, day = _symbol(raw["symbol"]), _date(raw["date"])
        if symbol not in symbols or day not in dates or (symbol, day) in series_ids:
            raise ValueError("Unknown or duplicate series")
        series_ids.add((symbol, day))
        calibration = _obj(raw["text_calibration"])
        cal = {"status": _text(calibration["status"], 100), "reason": _text(calibration["reason"], 200, nullable=True),
               "training_text_rows": _integer(calibration["training_text_rows"], 0), "training_sessions": _integer(calibration["training_sessions"], 0),
               "training_cutoff": _timestamp(calibration["training_cutoff"])}
        points = []
        for raw_point in _rows(raw["points"], 100):
            raw_point = _obj(raw_point)
            at, start = _time(raw_point["timestamp"]), _time(raw_point["bar_start"])
            if at - start != timedelta(minutes=5) or at.astimezone(NY).date().isoformat() != day:
                raise ValueError("Invalid five-minute price bar")
            price = {k: _num(_obj(raw_point["price"])[k], 0 if k == "volume" else .0000001) for k in ("open", "high", "low", "close", "volume")}
            if price["low"] > min(price["open"], price["close"]) or price["high"] < max(price["open"], price["close"]):
                raise ValueError("Inconsistent OHLC bar")
            decision = _bool(raw_point["has_decision"])
            point = dict(timestamp=_timestamp(raw_point["timestamp"]), bar_start=_timestamp(raw_point["bar_start"]), price=price, has_decision=decision,
                         **{m: _model(raw_point[m], m, at, decision) for m in ("A", "C", "B")}, text=None)
            if decision:
                if _time(cal["training_cutoff"]) >= at:
                    raise ValueError("Future calibration in decision")
                decision_count += 1
                point["text"] = _text_signal(raw_point["text"], features, evidence, at, point["C"]["effective_horizon_minutes"])
                changed_count += int(abs(point["text"]["effective_adjustment_bps"]) > 1e-10)
                _close(point["B"]["forecast_bps"], point["C"]["forecast_bps"] + point["text"]["effective_adjustment_bps"])
                if point["B"]["effective_horizon_minutes"] != point["C"]["effective_horizon_minutes"] or point["B"]["realized_end_at"] != point["C"]["realized_end_at"] or point["B"]["realized_bps"] != point["C"]["realized_bps"]:
                    raise ValueError("B and C diagnostics must share the same outcome horizon")
            elif raw_point["text"] is not None:
                raise ValueError("Non-decision price bar cannot include text signal")
            points.append(point)
        times = [_time(p["timestamp"]) for p in points]
        if not times or times != sorted(set(times)) or any(b - a != timedelta(minutes=5) for a, b in zip(times, times[1:])):
            raise ValueError("Price time series must be unique and consecutive")
        bars_by_start = {_time(p["bar_start"]): p["price"] for p in points}
        for point in points:
            for model in ("A", "B", "C"):
                outcome = point[model]
                if outcome["realized_bps"] is None:
                    continue
                entry = bars_by_start.get(_time(point["timestamp"]))
                ending = bars_by_start.get(_time(outcome["realized_end_at"]) - timedelta(minutes=5))
                if entry is None or ending is None:
                    raise ValueError("Realized outcome lacks its saved price endpoints")
                _close(outcome["realized_bps"], (ending["close"] / entry["open"] - 1) * 10000)
        fills = []
        for item in _rows(raw["fills"], 3000):
            item = _obj(item)
            fill = dict(model=_text(item["model"], 1), timestamp=_timestamp(item["timestamp"]), side=_text(item["side"], 4),
                        quantity=_integer(item["quantity"]), fill_price=_num(item["fill_price"], .0000001), reason=_text(item["reason"], 100))
            if fill["model"] not in {"A", "B", "C"} or fill["side"] not in {"buy", "sell"} or fill["quantity"] == 0 or (fill["side"] == "buy") != (fill["quantity"] > 0) or _time(fill["timestamp"]).astimezone(NY).date().isoformat() != day:
                raise ValueError("Invalid saved simulated fill")
            fills.append(fill)
        scale = _num(raw["C_scale"], 0)
        if scale > 1:
            raise ValueError("Price calibration scale exceeds its registered bound")
        series.append(dict(symbol=symbol, date=day, C_scale=scale, text_calibration=cal, points=points, fills=fills))
    if series_ids != {(symbol, day) for symbol in symbols for day in dates}:
        raise ValueError("Missing symbol/date series")
    summary = _obj(data["summary"])
    result_summary = {k: _integer(summary[k], 0) for k in ("series_count", "decision_count", "changed_prediction_count")}
    result_summary["distinct_receipt_dates"] = [_date(v) for v in _rows(summary["distinct_receipt_dates"], 200)]
    receipt_dates = sorted({_time(e["received_at"]).astimezone(NY).date().isoformat() for e in evidence.values()})
    if result_summary != dict(series_count=len(series), decision_count=decision_count, changed_prediction_count=changed_count, distinct_receipt_dates=receipt_dates):
        raise ValueError("Summary counts do not match series evidence")
    default = _obj(data["default_selection"])
    default = {"symbol": _symbol(default["symbol"]), "date": _date(default["date"])}
    if (default["symbol"], default["date"]) not in series_ids:
        raise ValueError("Invalid default selection")
    if _time(data["generated_at"]).astimezone(NY).date().isoformat() < dates[-1]:
        raise ValueError("Report generated before its evaluation period")
    return dict(schema_version=1, generated_at=_timestamp(data["generated_at"]), evaluation_kind="retrospective_development", cost_bps_per_side=2.0,
                symbols=symbols, dates=dates, default_selection=default,
                tracks=[{"id": _text(_obj(v)["id"], 40), "label": _text(v["label"], 150), "status": _text(v["status"], 150), "as_of": _date(v["as_of"]), "detail": _text(v["detail"], 1000)} for v in _rows(data["tracks"], 20)],
                feature_definitions=definitions, summary=result_summary, evidence=evidence, series=series,
                limitations=[_text(v, 1500) for v in _rows(data["limitations"], 40)])


def _file_identity(path):
    stat = path.stat()
    if stat.st_size > MAX_PUBLIC_BYTES:
        raise ValueError("Public report exceeds size limit")
    # ctime detects ordinary in-place replacements even if mtime is restored.
    return (str(path.resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _validated_payload():
    """One bounded current-file cache; changed files are validated before serving.

    Warm reads avoid repeated parsing, validation and FastAPI jsonable_encoder.
    A cold/changed read verifies the file stayed unchanged across reading and
    caches its SHA256 plus canonical pre-serialized JSON and deterministic gzip.
    No stale payload is returned on missing, oversized, invalid or racing files.
    """
    global _CACHE
    with _CACHE_LOCK:
        path = Path(PUBLIC_SIGNALS_PATH)
        # A deployment may retain only the smaller gzip sidecar. An existing but
        # invalid plain JSON never falls back to a different file silently.
        if not path.exists():
            path = path.with_suffix(path.suffix + ".gz")
        identity = _file_identity(path)
        if _CACHE is not None and _CACHE["identity"] == identity:
            return _CACHE
        raw = path.read_bytes()
        if len(raw) > MAX_PUBLIC_BYTES or _file_identity(path) != identity:
            raise ValueError("Public snapshot changed while being read")
        raw_hash = hashlib.sha256(raw).hexdigest()
        if _CACHE is not None and _CACHE["raw_sha256"] == raw_hash:
            _CACHE = {**_CACHE, "identity": identity}
            return _CACHE
        decoded = raw
        if path.suffix == ".gz":
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                decoded = stream.read(MAX_PUBLIC_BYTES + 1)
            if len(decoded) > MAX_PUBLIC_BYTES:
                raise ValueError("Decompressed public report exceeds size limit")
        projected = validate_public_signals(json.loads(decoded))
        payload = json.dumps(projected, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        compressed = gzip.compress(payload, compresslevel=5, mtime=0)
        if _file_identity(path) != identity:
            raise ValueError("Public snapshot changed while being validated")
        _CACHE = {"identity": identity, "raw_sha256": raw_hash,
                  "etag": '"' + hashlib.sha256(payload).hexdigest() + '"',
                  "json": payload, "gzip": compressed}
        return _CACHE


def _accepts_gzip(header):
    wildcard = False
    for item in header.lower().split(","):
        parts = [part.strip() for part in item.split(";")]
        if parts[0] in {"gzip", "*"}:
            quality = 1.0
            for parameter in parts[1:]:
                if parameter.startswith("q="):
                    try:
                        quality = float(parameter[2:])
                    except ValueError:
                        quality = 0.0
            if parts[0] == "gzip":
                return quality > 0
            wildcard = quality > 0
    return wildcard


@router.get("/api/research/financial-sentiment/signals")
def read_signals(request: Request):
    try:
        cached = _validated_payload()
        headers = {"ETag": cached["etag"], "Vary": "Accept-Encoding", "Cache-Control": "private, no-cache"}
        if request.headers.get("if-none-match") == cached["etag"]:
            return Response(status_code=304, headers=headers)
        use_gzip = _accepts_gzip(request.headers.get("accept-encoding", ""))
        if use_gzip:
            headers["Content-Encoding"] = "gzip"
        return Response(content=cached["gzip"] if use_gzip else cached["json"],
                        media_type="application/json", headers=headers)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="The saved signal explorer has not been generated.") from None
    except (OSError, ValueError, TypeError, KeyError, OverflowError, EOFError):
        raise HTTPException(status_code=503, detail="The saved signal explorer is invalid or unreadable.") from None
