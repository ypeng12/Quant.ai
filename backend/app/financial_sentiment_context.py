"""Read-only, explicitly projected stock-context snapshots for research.

Importing this module does not initialize data collectors, models, accounts, or
the main application. Snapshot generation is a separate offline operation.
"""

from datetime import date, datetime, time
import ipaddress
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException


PUBLIC_CONTEXT_PATH = (
    Path(__file__).resolve().parents[2] / "reports" / "financial_sentiment_stock_context.json"
)
router = APIRouter()
NEW_YORK = ZoneInfo("America/New_York")
TICKER = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,4})?\Z")
LOCAL_PATH = re.compile(r"file:/{1,3}|/(?:Users|home|tmp|private|var|etc|Volumes)/|\b[A-Za-z]:[\\/]")
SUMMARY_NUMBERS = (
    "last_price", "previous_close", "change_pct", "gap_pct", "open_to_cutoff_pct",
    "excess_vs_spy_pp", "excess_vs_sector_pp", "mean_true_range_14", "sma20", "sma50",
    "session_vwap", "session_volume",
)


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected an object")
    return value


def _required(row: dict[str, Any], key: str) -> Any:
    if key not in row:
        raise ValueError("A required snapshot field is missing")
    return row[key]


def _rows(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("Expected a list")
    return value


def _text(value: Any, limit: int = 500) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or LOCAL_PATH.search(value) or any(ord(char) < 32 for char in value)):
        raise ValueError("Expected bounded public text without local paths")
    return value


def _enum(value: Any, allowed: set[str]) -> str:
    value = _text(value)
    if value not in allowed:
        raise ValueError("Unsupported snapshot state")
    return value


def _symbol(value: Any) -> str:
    value = _text(value, 15)
    if not TICKER.fullmatch(value):
        raise ValueError("Invalid ticker")
    return value


def _number(value: Any, *, nullable: bool = False, minimum: float | None = None,
            positive: bool = False) -> int | float | None:
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Expected a finite number")
    if (minimum is not None and value < minimum) or (positive and value <= 0):
        raise ValueError("Number is outside the supported range")
    return value


def _count(value: Any, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer count")
    return value


def _timestamp(value: Any, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    value = _text(value, 64)
    _instant(value)
    return value


def _instant(value: str) -> datetime:
    # Requiring T also rejects date-only values and non-ISO datetime separators.
    if "T" not in value:
        raise ValueError("Expected an ISO timestamp with a timezone")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("A timezone is required")
    return parsed


def _date(value: Any) -> str:
    value = _text(value, 10)
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("Expected a YYYY-MM-DD date")
    return value


def _url(value: Any) -> str:
    value = _text(value, 2048)
    parsed = urlsplit(value)
    host = parsed.hostname
    if (parsed.scheme != "https" or not host or parsed.username is not None
            or parsed.password is not None or any(char.isspace() for char in value)
            or "\\" in value or parsed.port not in (None, 443)):
        raise ValueError("Expected a public HTTPS source link")
    host = host.rstrip(".").lower()
    if "." not in host or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local source links are not public")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Local source links are not public")
    return value


def _texts(value: Any) -> list[str]:
    return [_text(item) for item in _rows(value)]


def _unique(rows: list[dict[str, Any]], key: str) -> None:
    if len({row[key] for row in rows}) != len(rows):
        raise ValueError("Duplicate snapshot records")


def _validate_public_context(data: Any) -> dict[str, Any]:
    """Recursively project the supported public schema and reject false timing."""
    data = _object(data)
    states = {
        "schema_version": "context-1.0",
        "mode": "Retrospective research snapshot",
        "prediction_status": "Not trained",
    }
    for key, expected in states.items():
        if _required(data, key) != expected:
            raise ValueError("Unsupported research snapshot state")
    generated_at = _timestamp(_required(data, "generated_at"))
    analysis_cutoff = _timestamp(_required(data, "analysis_cutoff"))
    cutoff = _instant(analysis_cutoff)
    if _instant(generated_at) < cutoff:
        raise ValueError("Snapshot generation precedes its analysis cutoff")
    cutoff_ny = cutoff.astimezone(NEW_YORK)
    symbol = _symbol(_required(data, "symbol"))
    summary_input = _object(_required(data, "summary"))
    summary = {key: _number(_required(summary_input, key), nullable=True,
                           positive=key in {"last_price", "previous_close", "sma20", "sma50", "session_vwap"},
                           minimum=0 if key in {"mean_true_range_14", "session_volume"} else None)
               for key in SUMMARY_NUMBERS}

    benchmarks = []
    for row in _rows(_required(data, "benchmarks")):
        row = _object(row)
        benchmarks.append({
            "symbol": _symbol(_required(row, "symbol")),
            **{key: _number(_required(row, key), nullable=True)
               for key in ("change_pct", "return_5d_pct", "return_20d_pct")},
        })
    _unique(benchmarks, "symbol")
    supported_symbols = {symbol, *(row["symbol"] for row in benchmarks)}

    intraday, daily = [], []
    seen_points: set[tuple[str, Any]] = set()
    for row in _rows(_required(data, "intraday")):
        row = _object(row)
        timestamp = _timestamp(_required(row, "timestamp"))
        point_time = _instant(timestamp)
        point_symbol = _symbol(_required(row, "symbol"))
        key = (point_symbol, point_time)
        if point_time > cutoff or key in seen_points or point_symbol not in supported_symbols:
            raise ValueError("Invalid, future, or duplicate intraday point")
        seen_points.add(key)
        intraday.append({
            "timestamp": timestamp, "symbol": point_symbol,
            "price": _number(_required(row, "price"), positive=True),
            "return_pct": _number(_required(row, "return_pct")),
            "volume": _number(_required(row, "volume"), minimum=0),
            "session": _enum(_required(row, "session"), {"premarket", "regular"}),
        })
    seen_points.clear()
    for row in _rows(_required(data, "daily")):
        row = _object(row)
        day = _date(_required(row, "date"))
        point_symbol = _symbol(_required(row, "symbol"))
        key = (point_symbol, day)
        if (day > cutoff_ny.date().isoformat() or key in seen_points
                or point_symbol not in supported_symbols
                or (day == cutoff_ny.date().isoformat() and cutoff_ny.time() < time(16))):
            raise ValueError("Invalid, uncompleted, or duplicate daily point")
        seen_points.add(key)
        daily.append({
            "date": day, "symbol": point_symbol,
            "close": _number(_required(row, "close"), positive=True),
            "return_pct": _number(_required(row, "return_pct")),
        })

    levels = []
    for row in _rows(_required(data, "levels")):
        row = _object(row)
        known_at = _timestamp(_required(row, "known_at"))
        if _instant(known_at) > cutoff:
            raise ValueError("A level was not known at the cutoff")
        levels.append({
            "id": _text(_required(row, "id"), 100),
            "label": _text(_required(row, "label"), 120),
            "price": _number(_required(row, "price"), positive=True),
            "known_at": known_at,
            "basis": _text(_required(row, "basis"), 300),
            "kind": _enum(_required(row, "kind"), {"prior_session", "rolling", "moving_average"}),
        })
    _unique(levels, "id")

    news_input = _object(_required(data, "news"))
    news = {
        "status": _text(_required(news_input, "status"), 100),
        "received_at": _timestamp(_required(news_input, "received_at"), nullable=True),
        **{key: _count(_required(news_input, key)) for key in
           ("records_total", "precutoff_publications", "usable_at_cutoff")},
        "items": [],
    }
    if not news["usable_at_cutoff"] <= news["precutoff_publications"] <= news["records_total"]:
        raise ValueError("Inconsistent news counts")
    for row in _rows(_required(news_input, "items")):
        row = _object(row)
        published_at = _timestamp(_required(row, "published_at"), nullable=True)
        received_at = _timestamp(_required(row, "received_at"), nullable=True)
        timing = _enum(_required(row, "timing"), {
            "received_after_cutoff", "available_at_cutoff", "publication_time_unknown",
        })
        if timing == "available_at_cutoff" and (
                published_at is None or received_at is None
                or _instant(published_at) > cutoff or _instant(received_at) > cutoff):
            raise ValueError("News availability is not supported by its timestamps")
        if timing == "publication_time_unknown" and published_at is not None:
            raise ValueError("News publication precision is inconsistent")
        if timing == "received_after_cutoff" and (
                received_at is None or _instant(received_at) <= cutoff):
            raise ValueError("News receipt is inconsistent with its timing label")
        news["items"].append({
            "id": _text(_required(row, "id"), 100),
            "source": _text(_required(row, "source"), 120),
            "published_at": published_at, "received_at": received_at, "timing": timing,
            "association": _enum(_required(row, "association"), {"direct", "sector", "macro"}),
            "summary": _text(_required(row, "summary"), 600),
            "url": _url(_required(row, "url")),
            "evidence_type": _enum(_required(row, "evidence_type"), {
                "reported_fact", "company_statement", "opinion", "unverified",
            }),
        })
    _unique(news["items"], "id")
    if (len(news["items"]) > news["records_total"]
            or sum(row["timing"] == "available_at_cutoff" for row in news["items"]) > news["usable_at_cutoff"]
            or sum(row["published_at"] is not None and _instant(row["published_at"]) <= cutoff
                   for row in news["items"]) > news["precutoff_publications"]):
        raise ValueError("Displayed news exceeds declared coverage")

    community_input = _object(_required(data, "community"))
    community = {
        "source": _enum(_required(community_input, "source"), {"Futu"}),
        "status": _text(_required(community_input, "status"), 100),
        **{key: _timestamp(_required(community_input, key), nullable=True)
           for key in ("received_at", "window_start", "window_end")},
        **{key: _count(_required(community_input, key)) for key in (
            "records", "unique_posts", "available_at_cutoff", "bullish", "bearish", "mixed", "unknown", "classified",
        )},
        "stance_balance": _number(_required(community_input, "stance_balance"), nullable=True),
        "method": _text(_required(community_input, "method")),
        "limitations": _texts(_required(community_input, "limitations")),
    }
    classified = community["bullish"] + community["bearish"] + community["mixed"]
    if (community["unique_posts"] > community["records"]
            or community["available_at_cutoff"] > community["unique_posts"]
            or community["classified"] != classified
            or classified + community["unknown"] != community["unique_posts"]):
        raise ValueError("Inconsistent community counts")
    directional = community["bullish"] + community["bearish"]
    balance = community["stance_balance"]
    if ((directional == 0 and balance is not None)
            or (directional > 0 and (balance is None or not math.isclose(
                balance, (community["bullish"] - community["bearish"]) / directional * 100,
                abs_tol=0.0051, rel_tol=0)))):
        raise ValueError("Stance balance must describe the observed directional counts")
    if (community["window_start"] is not None and community["window_end"] is not None
            and _instant(community["window_start"]) > _instant(community["window_end"])):
        raise ValueError("Community window is reversed")
    if community["available_at_cutoff"] and (
            community["received_at"] is None or _instant(community["received_at"]) > cutoff):
        raise ValueError("Community availability is not supported by its receipt")

    sources = []
    for row in _rows(_required(data, "sources")):
        row = _object(row)
        sources.append({
            "id": _text(_required(row, "id"), 100),
            "label": _text(_required(row, "label"), 120),
            "status": _text(_required(row, "status"), 100),
            "records": _count(_required(row, "records"), nullable=True),
            "received_at": _timestamp(_required(row, "received_at"), nullable=True),
            "detail": _text(_required(row, "detail")),
        })
    _unique(sources, "id")
    return {
        **states, "generated_at": generated_at, "analysis_cutoff": analysis_cutoff,
        "price_received_at": _timestamp(_required(data, "price_received_at"), nullable=True),
        "symbol": symbol, "summary": summary, "benchmarks": benchmarks,
        "intraday": intraday, "daily": daily, "levels": levels, "news": news,
        "community": community, "sources": sources,
        "limitations": _texts(_required(data, "limitations")),
    }


def load_public_context(path: Path | None = None) -> dict[str, Any]:
    """Read an offline export without collecting data or exposing private fields."""
    snapshot = path if path is not None else PUBLIC_CONTEXT_PATH
    try:
        return _validate_public_context(json.loads(snapshot.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="The stock context snapshot has not been generated.") from exc
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise HTTPException(status_code=503, detail="The saved stock context snapshot is invalid or unreadable.") from exc


@router.get("/context")
def research_context() -> dict[str, Any]:
    return load_public_context()
