"""Read-only access to the public financial sentiment data-audit snapshot.

This module does not import collectors, models, account clients, or the trading
application. The public snapshot is exported separately from private raw data.
"""

from datetime import date
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException


PUBLIC_SUMMARY_PATH = (
    Path(__file__).resolve().parents[2]
    / "reports"
    / "financial_sentiment_public_summary.json"
)
SOURCE_IDS = {"news", "futu", "prices", "sec", "x"}
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
