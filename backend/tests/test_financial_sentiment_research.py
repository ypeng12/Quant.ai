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
    monkeypatch.setattr(research, "PUBLIC_REPORT_PATH", tmp_path / "public_report.json")
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


@pytest.fixture
def report():
    company = {
        "symbol": "PLTR", "article_count": 3, "headline_only_count": 1, "cluster_count": 1,
        "price_context": {"status": "Available", "return_pct": 2.4,
                          "excess_vs_spy_pp": 1.2, "excess_vs_sector_pp": None,
                          "sector_benchmark": "IGV"},
        "sentiment": {"positive": 1, "negative": 0, "neutral": 1, "unavailable": 1},
        "findings": ["One candidate rating event was identified."],
        "limitations": ["Reported timestamps do not prove first system receipt."],
        "events": [{"id": "rating-event", "event_type": "analyst_rating",
                    "claim_kind": "analyst_opinion", "summary": "An analyst changed the rating.",
                    "article_count": 3, "earliest_reported_at": "2026-10-08T10:23:06Z",
                    "source_urls": ["https://example.org/news/rating"],
                    "tone": "positive", "headline_only": False}],
    }
    return {
        "schema_version": "1.0", "generated_at": "2026-10-09T21:40:00+00:00",
        "price_asof": "2026-10-09T16:00:00-04:00",
        "analysis_mode": "Retrospective evidence review",
        "extraction_method": "Rules v1 + FinBERT tone", "model_status": "Pretrained inference only",
        "prediction_status": "Not trained", "ab_status": "Not evaluated",
        "coverage": {"articles_loaded": 3, "article_company_pairs": 3,
                     "classified_pairs": 3, "clusters": 1},
        "companies": [company],
    }


def write_report(report):
    research.PUBLIC_REPORT_PATH.write_text(json.dumps(report), encoding="utf-8")


def test_report_reads_independent_export_without_requiring_old_audit(client, report):
    write_report(report)
    response = client.get("/api/research/financial-sentiment/report")
    assert response.status_code == 200
    assert response.json() == report
    assert client.get("/api/research/financial-sentiment/status").status_code == 503
    assert client.post("/api/research/financial-sentiment/report").status_code == 405


def test_report_allowlist_excludes_private_fields_at_every_level(client, report):
    private = copy.deepcopy(report)
    for container in (private, private["coverage"], private["companies"][0],
                      private["companies"][0]["price_context"], private["companies"][0]["sentiment"],
                      private["companies"][0]["events"][0]):
        container["raw_article_text"] = "Private raw source text"
        container["model_probability"] = 0.99
    write_report(private)
    response = client.get("/api/research/financial-sentiment/report")
    assert response.status_code == 200
    assert response.json() == report


def test_missing_report_does_not_substitute_the_audit_or_generate_data(client, summary):
    write_summary(summary)
    response = client.get("/api/research/financial-sentiment/report")
    assert response.status_code == 404
    assert "not been generated" in response.json()["detail"]
    assert not research.PUBLIC_REPORT_PATH.exists()
    assert client.get("/api/research/financial-sentiment/status").json() == summary


def test_invalid_report_json_is_distinct_from_not_generated(client):
    research.PUBLIC_REPORT_PATH.write_text("{broken", encoding="utf-8")
    response = client.get("/api/research/financial-sentiment/report")
    assert response.status_code == 503
    assert "invalid" in response.json()["detail"]


@pytest.mark.parametrize("path,value", [
    (("prediction_status",), "Trained"),
    (("model_status",), "Custom trained model"),
    (("analysis_mode",), "Live forecast"),
    (("ab_status",), "Profitable"),
    (("schema_version",), "2.0"),
    (("generated_at",), "2026-10-09T21:40:00"),
    (("price_asof",), "not a date"),
    (("coverage", "articles_loaded"), True),
    (("coverage", "classified_pairs"), -1),
    (("companies",), []),
    (("companies", 0, "symbol"), "NVDA"),
    (("companies", 0, "price_context", "return_pct"), float("nan")),
    (("companies", 0, "price_context", "excess_vs_spy_pp"), float("inf")),
    (("companies", 0, "price_context", "return_pct"), True),
    (("companies", 0, "sentiment", "positive"), "1"),
    (("companies", 0, "events", 0, "headline_only"), "false"),
    (("companies", 0, "events", 0, "earliest_reported_at"), "2026-10-08T10:23:06"),
    (("companies", 0, "events", 0, "source_urls"), ["javascript:alert(1)"]),
    (("companies", 0, "events", 0, "source_urls"), ["https://user:secret@example.org/news"]),
    (("companies", 0, "findings"), "Not a list"),
])
def test_invalid_or_misleading_report_is_rejected(client, report, path, value):
    node = report
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    write_report(report)
    assert client.get("/api/research/financial-sentiment/report").status_code == 503


@pytest.mark.parametrize("location", ["companies", "events"])
def test_duplicate_report_records_are_rejected(client, report, location):
    rows = report["companies"] if location == "companies" else report["companies"][0]["events"]
    rows.append(copy.deepcopy(rows[0]))
    write_report(report)
    assert client.get("/api/research/financial-sentiment/report").status_code == 503


@pytest.mark.parametrize("reported_at", [None, "2026-10-08"])
def test_unknown_or_date_only_event_time_preserves_precision(client, report, reported_at):
    report["companies"][0]["events"][0]["earliest_reported_at"] = reported_at
    write_report(report)
    response = client.get("/api/research/financial-sentiment/report")
    assert response.status_code == 200
    assert response.json()["companies"][0]["events"][0]["earliest_reported_at"] == reported_at
