"""Serve the retained research audit without starting collectors or trading services."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "reports/market_impact_data_audit_20261007"
PLAN = ROOT / "docs/financial_sentiment_using_prices_plan.md"


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(503, "Local audit data is unavailable or invalid. Restore the retained audit snapshot.") from None


def create_app(audit_dir: Path = AUDIT, plan_path: Path = PLAN) -> FastAPI:
    api = FastAPI(title="Quant.ai · Financial Sentiment Using Prices", version="0.1.0")

    @api.get("/api/research/financial-sentiment/health")
    def health():
        return {"status": "ok", "mode": "research", "collection_running": False, "trading_enabled": False}

    @api.get("/api/research/financial-sentiment/status")
    def status():
        news = read_json(audit_dir / "alpaca/summary.json")
        futu = read_json(audit_dir / "futu/summary.json")
        sec = read_json(audit_dir / "sec/summary.json")
        validation = read_json(audit_dir / "validation.json")
        return {
            "project": "Quant.ai · Financial Sentiment Using Prices", "mode": "research", "audit_date": "2026-10-07",
            "model_status": "Not trained", "evaluation_status": "Not evaluated",
            "current_stage": "Data audit", "next_stage": "Persistent collection",
            "sources": [
                {"id": "news", "name": "Company news", "records": news["news"]["unique_ids"],
                 "status": "Historical snapshot", "detail": f'{news["news"]["with_body"]} articles include body text; event deduplication remains pending.'},
                {"id": "futu", "name": "Futu community", "records": futu["total_rows"],
                 "status": "Historical snapshot", "detail": f'{futu["global_unique_post_ids"]} unique post IDs; author and interaction fields were not provided.'},
                {"id": "prices", "name": "Stock and benchmark prices", "records": validation["rth_bars"],
                 "status": "Historical snapshot", "detail": "Regular-session five-minute bars across seven symbols and five trading days."},
                {"id": "sec", "name": "SEC filings", "records": sec["totals"]["window_filings"],
                 "status": "Metadata only", "detail": f'{sec["totals"]["window_key_filings"]} key filings in the 90-day window; document access was unsuccessful.'},
                {"id": "x", "name": "X", "records": None,
                 "status": "Not connected", "detail": "Access was researched; no structured post sample has been collected."},
            ],
            "exploratory_labels": validation["valid_exploratory_label_rows"],
            "labels_are_predictions": False,
            "plan_url": "/api/research/financial-sentiment/plan",
        }

    @api.get("/api/research/financial-sentiment/events")
    def events(source: Literal["news", "futu"] = "news",
               symbol: str | None = Query(None, pattern=r"^[A-Z]{1,5}$"),
               limit: int = Query(20, ge=1, le=100)):
        if source == "news":
            raw = read_json(audit_dir / "alpaca/news_normalized.json")
            items = [{"id": row["id"], "symbols": row["symbols"], "title": row["headline"],
                      "published_at": row["created_at"], "source": "Benzinga",
                      "has_body": bool(row["text"]), "received_at": None} for row in raw]
        else:
            # One post can appear in several symbol queries; merge its symbol associations.
            grouped = {}
            for row in read_json(audit_dir / "futu/all_normalized.json"):
                key = row["post_id"]
                if key not in grouped:
                    grouped[key] = {"id": key, "symbols": [], "title": row["title"] or row["excerpt"],
                                    "published_at": row["published_at"], "source": "Futu",
                                    "has_body": bool(row["excerpt"]),
                                    "received_at": row.get("response_received_at")}
                if row["query_symbol"] not in grouped[key]["symbols"]:
                    grouped[key]["symbols"].append(row["query_symbol"])
            items = list(grouped.values())
        if symbol:
            items = [item for item in items if symbol in item["symbols"]]
        items.sort(key=lambda item: (item["published_at"] or "", item["id"]), reverse=True)
        return {"items": items[:limit], "total": len(items), "source": source, "snapshot": True}

    @api.get("/api/research/financial-sentiment/plan", response_class=PlainTextResponse)
    def plan():
        try:
            return plan_path.read_text(encoding="utf-8")
        except OSError:
            raise HTTPException(503, "The local research plan is unavailable.") from None

    return api


app = create_app()
