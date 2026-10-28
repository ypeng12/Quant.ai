"""Read-only public projection of a saved A/C/B development replay.

This module never starts trading, collection, or model fitting. Only the fixed
public report is read; unknown fields and private diagnostic paths are omitted.
"""

from datetime import date, datetime
import json
import math
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException


PUBLIC_COMPARISON_PATH = Path(__file__).resolve().parents[2] / "reports" / "financial_sentiment_strategy_comparison.json"
router = APIRouter()
LOCAL_PATH = re.compile(r"file:/{1,3}|/(?:Users|home|tmp|private|var|etc|Volumes)/|\b[A-Za-z]:[\\/]")
MODEL_IDS = ("A", "B", "C")


def _object(value):
    if not isinstance(value, dict):
        raise ValueError("Expected an object")
    return value


def _text(value, limit=600, nullable=False):
    if value is None and nullable:
        return None
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or LOCAL_PATH.search(value) or any(ord(c) < 32 for c in value)):
        raise ValueError("Expected bounded public text")
    return value


def _number(value, minimum=None, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Finite numeric value required")
    if minimum is not None and value < minimum:
        raise ValueError("Value below supported range")
    if maximum is not None and value > maximum:
        raise ValueError("Value above supported range")
    return value


def _count(value):
    if type(value) is not int or value < 0:
        raise ValueError("Nonnegative integer required")
    return value


def _rows(value, maximum=2000):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("Bounded list required")
    return value


def _date(value):
    value = _text(value, 10)
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("ISO date required")
    return value


def validate_public_comparison(data):
    """Project the schema, units, timing and accounting invariants."""
    data = _object(data)
    if (type(data["schema_version"]) is not int or data["schema_version"] != 1
            or data["evaluation_kind"] != "retrospective_development"
            or data["currency"] != "USD" or data["promoted"] is not False):
        raise ValueError("Unsupported comparison state")
    generated = _text(data["generated_at"], 64)
    instant = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    if "T" not in generated or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Timezone-aware generated timestamp required")
    dates = {key: _date(data[key]) for key in
             ("requested_start", "requested_end", "evaluated_start", "evaluated_end")}
    if not (dates["requested_start"] <= dates["evaluated_start"] <=
            dates["evaluated_end"] <= dates["requested_end"]):
        raise ValueError("Evaluation dates must lie within the requested period")
    if instant.date().isoformat() < dates["evaluated_end"]:
        raise ValueError("Report generated before evaluation period")
    capital = _number(data["starting_capital"], minimum=0.01)
    sessions = _count(data["sessions"])
    if sessions == 0:
        raise ValueError("No completed comparison sessions")
    models = []
    for value in _rows(data["models"], 3):
        value = _object(value)
        identifier = _text(value["id"], 1)
        if identifier not in MODEL_IDS:
            raise ValueError("Unsupported model identifier")
        item = {"id": identifier, "name": _text(value["name"], 120),
                "description": _text(value["description"], 1000)}
        for key in ("net_pnl", "net_return", "max_drawdown", "costs",
                    "mean_gross_exposure", "mean_daily_turnover"):
            item[key] = _number(value[key], minimum=0 if key in
                                {"costs", "mean_gross_exposure", "mean_daily_turnover"} else None,
                                maximum=0 if key == "max_drawdown" else None)
        item["fill_count"] = _count(value["fill_count"])
        if not math.isclose(item["net_pnl"], capital * item["net_return"], abs_tol=.02, rel_tol=1e-7):
            raise ValueError("Net return and net PnL disagree")
        models.append(item)
    by_id = {m["id"]: m for m in models}
    if len(models) != 3 or set(by_id) != set(MODEL_IDS):
        raise ValueError("One A, B and C model required")
    curves = []
    for value in _rows(data["curves"]):
        value = _object(value)
        curves.append({"date": _date(value["date"]),
                       **{identifier: _number(value[identifier]) for identifier in MODEL_IDS}})
    curve_dates = [row["date"] for row in curves]
    if (len(curves) != sessions or curve_dates != sorted(set(curve_dates)) or
            curve_dates[0] != dates["evaluated_start"] or curve_dates[-1] != dates["evaluated_end"]):
        raise ValueError("Curve dates and session coverage disagree")
    for identifier in MODEL_IDS:
        if not math.isclose(curves[-1][identifier], capital + by_id[identifier]["net_pnl"], abs_tol=.02, rel_tol=1e-7):
            raise ValueError("Ending equity and net PnL disagree")
    source_text = _object(data["text"])
    text = {key: _count(source_text[key]) for key in
            ("source_records", "usable_decisions", "changed_decisions")}
    text.update(calibration_status=_text(source_text["calibration_status"], 300),
                fallback_reason=_text(source_text["fallback_reason"], 1000, nullable=True))
    if text["changed_decisions"] > text["usable_decisions"]:
        raise ValueError("Changed decisions exceed usable text decisions")
    if text["changed_decisions"] == 0 and any(
            not math.isclose(row["B"], row["C"], abs_tol=.02, rel_tol=1e-9) for row in curves):
        raise ValueError("A zero-text-change run must preserve the price-only control curve")
    coverage_in = _object(data["coverage"])
    complete = coverage_in["complete_requested_period"]
    if type(complete) is not bool:
        raise ValueError("Explicit coverage boolean required")
    missing = [_date(item) for item in _rows(coverage_in["missing_sessions"])]
    if (missing != sorted(set(missing)) or any(day in curve_dates or not
            dates["requested_start"] <= day <= dates["requested_end"] for day in missing)
            or (complete and missing)):
        raise ValueError("Missing-session coverage is inconsistent")
    return {
        "schema_version": 1, "generated_at": generated,
        "evaluation_kind": "retrospective_development", **dates,
        "sessions": sessions, "starting_capital": capital, "currency": "USD",
        "models": [by_id[identifier] for identifier in MODEL_IDS], "curves": curves,
        "text": text, "coverage": {"complete_requested_period": complete,
                                    "missing_sessions": missing},
        "limitations": [_text(item, 1000) for item in _rows(data["limitations"], 40)],
        "promoted": False,
    }


@router.get("/api/research/financial-sentiment/comparison")
def read_comparison():
    try:
        if PUBLIC_COMPARISON_PATH.stat().st_size > 2_000_000:
            raise ValueError("Report exceeds public size limit")
        data = json.loads(PUBLIC_COMPARISON_PATH.read_text(encoding="utf-8"))
        return validate_public_comparison(data)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="The saved strategy comparison has not been generated.") from None
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        raise HTTPException(status_code=503, detail="The saved strategy comparison is unavailable or failed validation.") from None
