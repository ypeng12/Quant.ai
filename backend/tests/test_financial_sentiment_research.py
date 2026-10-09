import copy
import json
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import financial_sentiment_research as research


@pytest.fixture
def summary():
    return {
        "project": "Train Financial Sentiment Analysis Using Prices",
        "audit_date": "2026-10-07",
        "model_status": "Not trained",
        "evaluation_status": "Not evaluated",
        "current_stage": "Data audit",
        "exploratory_labels": 90,
        "labels_are_predictions": False,
        "sources": [
            {"id": "news", "name": "Company news", "records": 187,
             "status": "Partial", "detail": "152 records include article bodies."},
            {"id": "futu", "name": "Futu community", "records": 120,
             "status": "Sampled", "detail": "118 unique posts; coverage is incomplete."},
            {"id": "prices", "name": "Market prices", "records": 2730,
             "status": "Sampled", "detail": "Regular-session price bars."},
            {"id": "sec", "name": "SEC filings", "records": 94,
             "status": "Metadata only", "detail": "14 key filings; primary document retrieval failed."},
            {"id": "x", "name": "X", "records": None,
             "status": "Not connected", "detail": "No data has been collected."},
        ],
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "PUBLIC_SUMMARY_PATH", tmp_path / "public_summary.json")
    app = FastAPI()
    app.include_router(research.router)
    with TestClient(app) as test_client:
        yield test_client


def write_summary(summary):
    research.PUBLIC_SUMMARY_PATH.write_text(json.dumps(summary), encoding="utf-8")


def test_status_uses_fixture_snapshot_and_preserves_research_limits(client, summary):
    write_summary(summary)
    response = client.get("/api/research/financial-sentiment/status")
    assert response.status_code == 200
    assert response.json() == summary
    assert response.json()["labels_are_predictions"] is False
    assert response.json()["sources"][-1]["records"] is None


def test_status_does_not_return_unapproved_export_fields(client, summary):
    with_private_fields = copy.deepcopy(summary)
    with_private_fields["raw_article_text"] = "Private fixture content"
    with_private_fields["sources"][0]["raw_records"] = ["Private fixture record"]
    write_summary(with_private_fields)
    response = client.get("/api/research/financial-sentiment/status")
    assert response.status_code == 200
    assert response.json() == summary


def test_missing_summary_returns_503_without_inventing_data(client):
    response = client.get("/api/research/financial-sentiment/status")
    assert response.status_code == 503
    assert "not available" in response.json()["detail"]
    assert "sources" not in response.json()


def test_invalid_json_returns_503(client):
    research.PUBLIC_SUMMARY_PATH.write_text("{broken", encoding="utf-8")
    response = client.get("/api/research/financial-sentiment/status")
    assert response.status_code == 503
    assert "invalid" in response.json()["detail"]


@pytest.mark.parametrize("field,value", [
    ("model_status", "Trained"),
    ("evaluation_status", "Profitable"),
    ("labels_are_predictions", True),
    ("exploratory_labels", -1),
    ("exploratory_labels", True),
    ("audit_date", "2026-99-99"),
])
def test_invalid_or_misleading_snapshot_states_are_rejected(client, summary, field, value):
    summary[field] = value
    write_summary(summary)
    assert client.get("/api/research/financial-sentiment/status").status_code == 503


@pytest.mark.parametrize("bad_records", [-1, True, "187"])
def test_source_counts_require_nonnegative_integers(client, summary, bad_records):
    summary["sources"][0]["records"] = bad_records
    write_summary(summary)
    assert client.get("/api/research/financial-sentiment/status").status_code == 503


def test_duplicate_sources_are_rejected(client, summary):
    summary["sources"][-1] = copy.deepcopy(summary["sources"][0])
    write_summary(summary)
    assert client.get("/api/research/financial-sentiment/status").status_code == 503


def test_health_is_independent_of_snapshot_and_has_no_trading_or_collection(client):
    response = client.get("/api/research/financial-sentiment/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "mode": "research",
        "trading_enabled": False, "collection_running": False,
    }
