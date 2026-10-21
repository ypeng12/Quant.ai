"""Read-only access to the public financial sentiment data-audit snapshot.

This module does not import collectors, models, account clients, or the trading
application. The public snapshot is exported separately from private raw data.
"""

from datetime import date, datetime
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException


PUBLIC_SUMMARY_PATH = (
    Path(__file__).resolve().parents[2]
    / "reports"
    / "financial_sentiment_public_summary.json"
)
SOURCE_IDS = {"news", "futu", "prices", "sec", "x"}
PUBLIC_REPORT_PATH = PUBLIC_SUMMARY_PATH.with_name("financial_sentiment_prototype_summary.json")
REPORT_SYMBOLS = {"PLTR", "AMZN", "MSFT"}
router = APIRouter(prefix="/api/research/financial-sentiment", tags=["Financial Sentiment Research"])


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _count(value: Any, field: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    # bool is an int subclass; it is not a valid observed record count.
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _validate_public_summary(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("summary must be an object")
    audit_date = _text(data.get("audit_date"), "audit_date")
    if date.fromisoformat(audit_date).isoformat() != audit_date:
        raise ValueError("audit_date must use YYYY-MM-DD")
    expected_states = {
        "model_status": "Not trained",
        "evaluation_status": "Not evaluated",
        "current_stage": "Data audit",
    }
    for field, expected in expected_states.items():
        if data.get(field) != expected:
            raise ValueError(f"{field} does not describe the supported data-audit stage")
    if data.get("labels_are_predictions") is not False:
        raise ValueError("exploratory labels must not be presented as predictions")

    sources = data.get("sources")
    if not isinstance(sources, list) or len(sources) != len(SOURCE_IDS):
        raise ValueError("sources must include each configured source exactly once")
    public_sources = []
    seen = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("each source must be an object")
        source_id = _text(source.get("id"), "source.id")
        if source_id not in SOURCE_IDS or source_id in seen:
            raise ValueError("source ids must be configured and unique")
        if "records" not in source:
            raise ValueError("each source must declare its observed count or null")
        seen.add(source_id)
        public_sources.append({
            "id": source_id,
            "name": _text(source.get("name"), "source.name"),
            "records": _count(source.get("records"), "source.records", nullable=True),
            "status": _text(source.get("status"), "source.status"),
            "detail": _text(source.get("detail"), "source.detail"),
        })

    # Return an explicit allowlist. Extra local export metadata or raw text must
    # never be included automatically in this public endpoint.
    return {
        "project": _text(data.get("project"), "project"),
        "audit_date": audit_date,
        **expected_states,
        "exploratory_labels": _count(data.get("exploratory_labels"), "exploratory_labels"),
        "labels_are_predictions": False,
        "sources": public_sources,
    }


def load_public_summary(path: Path | None = None) -> dict[str, Any]:
    """Read and validate an exported snapshot; never synthesize missing counts."""
    snapshot = path if path is not None else PUBLIC_SUMMARY_PATH
    try:
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        return _validate_public_summary(data)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="Research data audit summary is not available. Export the read-only audit summary first.",
        ) from exc
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Research data audit summary is invalid or unreadable.",
        ) from exc


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value


def _timestamp(value: Any, field: str, *, date_allowed: bool = False) -> str:
    value = _text(value, field)
    if date_allowed and len(value) == 10:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError(f"{field} must be an ISO date")
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return value


def _number_or_null(value: Any, field: str) -> int | float | None:
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ValueError(f"{field} must be finite or null")
    return value


def _source_url(value: Any) -> str:
    value = _text(value, "source_url")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or any(char.isspace() or ord(char) < 32 for char in value)):
        raise ValueError("source_url must be a public HTTPS link without credentials")
    return value


def _validate_public_report(data: Any) -> dict[str, Any]:
    """Project only the supported public report schema; never expose raw input."""
    data = _object(data, "report")
    states = {
        "schema_version": "1.0",
        "analysis_mode": "Retrospective evidence review",
        "extraction_method": "Rules v1 + FinBERT tone",
        "model_status": "Pretrained inference only",
        "prediction_status": "Not trained",
        "ab_status": "Not evaluated",
    }
    for field, expected in states.items():
        if data.get(field) != expected:
            raise ValueError(f"Unsupported report {field}")
    coverage = _object(data.get("coverage"), "coverage")
    public_companies = []
    seen_symbols = set()
    for company in _list(data.get("companies"), "companies"):
        company = _object(company, "company")
        symbol = _text(company.get("symbol"), "symbol")
        if symbol not in REPORT_SYMBOLS or symbol in seen_symbols:
            raise ValueError("Report companies must be supported and unique")
        seen_symbols.add(symbol)
        prices = _object(company.get("price_context"), "price_context")
        sentiment = _object(company.get("sentiment"), "sentiment")
        events = []
        seen_events = set()
        for event in _list(company.get("events"), "events"):
            event = _object(event, "event")
            event_id = _text(event.get("id"), "event.id")
            if event_id in seen_events or type(event.get("headline_only")) is not bool:
                raise ValueError("Events need unique ids and an explicit headline_only flag")
            seen_events.add(event_id)
            reported = event.get("earliest_reported_at")
            events.append({
                "id": event_id,
                **{field: _text(event.get(field), f"event.{field}") for field in
                   ("event_type", "claim_kind", "summary", "tone")},
                "article_count": _count(event.get("article_count"), "event.article_count"),
                "earliest_reported_at": None if reported is None else _timestamp(
                    reported, "earliest_reported_at", date_allowed=True),
                "source_urls": [_source_url(url) for url in _list(event.get("source_urls"), "source_urls")],
                "headline_only": event["headline_only"],
            })
        public_companies.append({
            "symbol": symbol,
            **{field: _count(company.get(field), field) for field in
               ("article_count", "headline_only_count", "cluster_count")},
            "price_context": {
                "status": _text(prices.get("status"), "price_context.status"),
                **{field: _number_or_null(prices.get(field), field) for field in
                   ("return_pct", "excess_vs_spy_pp", "excess_vs_sector_pp")},
                "sector_benchmark": _text(prices.get("sector_benchmark"), "sector_benchmark"),
            },
            "sentiment": {field: _count(sentiment.get(field), f"sentiment.{field}")
                          for field in ("positive", "negative", "neutral", "unavailable")},
            **{field: [_text(item, field) for item in _list(company.get(field), field)]
               for field in ("findings", "limitations")},
            "events": events,
        })
    if not public_companies:
        raise ValueError("Report must contain at least one supported company")
    return {
        **states,
        "generated_at": _timestamp(data.get("generated_at"), "generated_at"),
        "price_asof": _timestamp(data.get("price_asof"), "price_asof"),
        "coverage": {field: _count(coverage.get(field), f"coverage.{field}") for field in
                     ("articles_loaded", "article_company_pairs", "classified_pairs", "clusters")},
        "companies": public_companies,
    }


def load_public_report(path: Path | None = None) -> dict[str, Any]:
    """Read an offline export; a GET never collects data or runs inference."""
    snapshot = path if path is not None else PUBLIC_REPORT_PATH
    try:
        return _validate_public_report(json.loads(snapshot.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="The evidence report has not been generated.") from exc
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(status_code=503, detail="The saved evidence report is invalid or unreadable.") from exc


@router.get("/report")
def research_report() -> dict[str, Any]:
    return load_public_report()


@router.get("/status")
def research_status() -> dict[str, Any]:
    return load_public_summary()


@router.get("/health")
def research_health() -> dict[str, Any]:
    """Describe this router only, not the surrounding Quant.ai trading service."""
    return {
        "status": "ok",
        "mode": "research",
        "trading_enabled": False,
        "collection_running": False,
    }


from .financial_sentiment_context import router as context_router

router.include_router(context_router)
