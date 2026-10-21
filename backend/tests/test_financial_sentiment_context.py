"""Exercise the read-only router without importing the trading application."""

import copy
import json
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import financial_sentiment_context as context
from app import financial_sentiment_research as research


@pytest.fixture
def snapshot():
    return {
        "schema_version": "context-1.0",
        "generated_at": "2026-10-12T12:15:00-04:00",
        "analysis_cutoff": "2026-10-12T12:00:00-04:00",
        "price_received_at": "2026-10-12T12:10:00-04:00",
        "symbol": "SNDK", "mode": "Retrospective research snapshot",
        "prediction_status": "Not trained",
        "summary": {
            "last_price": 95.0, "previous_close": 100.0, "change_pct": -5.0,
            "gap_pct": -3.0, "open_to_cutoff_pct": -2.06, "excess_vs_spy_pp": -5.2,
            "excess_vs_sector_pp": -3.0, "mean_true_range_14": 4.0, "sma20": 102.0,
            "sma50": None, "session_vwap": 96.0, "session_volume": 1000,
        },
        "benchmarks": [{"symbol": "SPY", "change_pct": 0.2,
                        "return_5d_pct": 1.1, "return_20d_pct": None}],
        "intraday": [
            {"timestamp": "2026-10-12T09:00:00-04:00", "symbol": "SNDK", "price": 97.0,
             "return_pct": -3.0, "volume": 100, "session": "premarket"},
            {"timestamp": "2026-10-12T16:00:00Z", "symbol": "SNDK", "price": 95.0,
             "return_pct": -5.0, "volume": 200, "session": "regular"},
        ],
        "daily": [{"date": "2026-10-09", "symbol": "SNDK", "close": 100.0, "return_pct": -1.0}],
        "levels": [{"id": "previous_close", "label": "Previous close", "price": 100.0,
                    "known_at": "2026-10-09T16:00:00-04:00", "basis": "Previous completed session close.",
                    "kind": "prior_session"}],
        "news": {
            "status": "Sampled", "received_at": "2026-10-12T12:05:00-04:00",
            "records_total": 2, "precutoff_publications": 2, "usable_at_cutoff": 1,
            "items": [
                {"id": "competition", "source": "Company", "published_at": "2026-10-10T12:00:00Z",
                 "received_at": "2026-10-12T09:00:00-04:00", "timing": "available_at_cutoff",
                 "association": "sector", "summary": "A producer announced a memory development plan.",
                 "url": "https://example.org/company/plan", "evidence_type": "company_statement"},
                {"id": "late_receipt", "source": "Publisher", "published_at": "2026-10-12T08:00:00-04:00",
                 "received_at": "2026-10-12T12:05:00-04:00", "timing": "received_after_cutoff",
                 "association": "macro", "summary": "An earlier report was collected after the cutoff.",
                 "url": "https://example.org/markets/context", "evidence_type": "reported_fact"},
            ],
        },
        "community": {
            "source": "Futu", "received_at": "2026-10-12T12:05:00-04:00", "status": "Sampled",
            "records": 6, "unique_posts": 5, "available_at_cutoff": 0,
            "window_start": "2026-10-10T00:00:00Z", "window_end": "2026-10-12T14:00:00Z",
            "bullish": 2, "bearish": 1, "mixed": 1, "unknown": 1, "classified": 4,
            "stance_balance": 33.33, "method": "Rules applied to unique sampled posts.",
            "limitations": ["The sample is incomplete and is not a return forecast."],
        },
        "sources": [{"id": "prices", "label": "Market prices", "status": "Sampled", "records": 3,
                     "received_at": "2026-10-12T12:10:00-04:00", "detail": "Raw price context only."}],
        "limitations": ["Retrospective context is not a validated trading signal."],
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(context, "PUBLIC_CONTEXT_PATH", tmp_path / "public_context.json")
    app = FastAPI()
    app.include_router(research.router)
    with TestClient(app) as test_client:
        yield test_client


def write_snapshot(snapshot):
    context.PUBLIC_CONTEXT_PATH.write_text(json.dumps(snapshot), encoding="utf-8")


def test_reads_snapshot_under_existing_research_prefix(client, snapshot):
    write_snapshot(snapshot)
    response = client.get("/api/research/financial-sentiment/context")
    assert response.status_code == 200
    assert response.json() == snapshot
    assert client.post("/api/research/financial-sentiment/context").status_code == 405
    assert client.get("/api/research/financial-sentiment/health").json()["trading_enabled"] is False


def test_allowlist_recursively_removes_raw_text_paths_and_account_fields(client, snapshot):
    exported = copy.deepcopy(snapshot)

    def inject(value):
        if isinstance(value, dict):
            for child in list(value.values()):
                inject(child)
            value.update(raw_article_text="Secret body", account_id="Private account",
                         local_path="/Users/owner/private.json", token="Private token")
        elif isinstance(value, list):
            for child in value:
                inject(child)

    inject(exported)
    write_snapshot(exported)
    response = client.get("/api/research/financial-sentiment/context")
    assert response.status_code == 200
    assert response.json() == snapshot


def test_missing_snapshot_is_404_without_generating_it(client):
    response = client.get("/api/research/financial-sentiment/context")
    assert response.status_code == 404
    assert "not been generated" in response.json()["detail"]
    assert not context.PUBLIC_CONTEXT_PATH.exists()


@pytest.mark.parametrize("content", ["{broken", "[]", "null"])
def test_invalid_snapshot_is_503_without_private_error_details(client, content):
    context.PUBLIC_CONTEXT_PATH.write_text(content, encoding="utf-8")
    response = client.get("/api/research/financial-sentiment/context")
    assert response.status_code == 503
    assert str(context.PUBLIC_CONTEXT_PATH) not in response.text


@pytest.mark.parametrize("path,value", [
    (("schema_version",), "context-2.0"),
    (("mode",), "Live forecast"),
    (("prediction_status",), "Trained"),
    (("symbol",), "../../private"),
    (("analysis_cutoff",), "2026-10-12T12:00:00"),
    (("analysis_cutoff",), "2026-10-12"),
    (("generated_at",), "2026-10-12T11:59:00-04:00"),
    (("price_received_at",), "2026-10-12T12:10:00"),
    (("summary", "change_pct"), True),
    (("summary", "change_pct"), float("nan")),
    (("summary", "last_price"), 0),
    (("summary", "session_volume"), -1),
    (("benchmarks", 0, "return_5d_pct"), float("inf")),
    (("intraday", 1, "timestamp"), "2026-10-12T16:00:01Z"),
    (("intraday", 1, "timestamp"), None),
    (("intraday", 0, "price"), None),
    (("intraday", 0, "volume"), True),
    (("intraday", 0, "symbol"), "MU"),
    (("intraday", 0, "session"), "afterhours"),
    (("daily", 0, "date"), "2026-10-13"),
    (("daily", 0, "date"), "2026-10-12"),
    (("daily", 0, "date"), "2026-10-09T00:00:00Z"),
    (("levels", 0, "known_at"), "2026-10-12T12:00:01-04:00"),
    (("news", "records_total"), True),
    (("news", "usable_at_cutoff"), 3),
    (("news", "items", 0, "published_at"), None),
    (("news", "items", 0, "received_at"), None),
    (("news", "items", 0, "received_at"), "2026-10-12T12:01:00-04:00"),
    (("news", "items", 0, "published_at"), "2026-10-12T12:01:00-04:00"),
    (("news", "items", 0, "timing"), "publication_time_unknown"),
    (("news", "items", 1, "received_at"), "2026-10-12T11:59:00-04:00"),
    (("news", "items", 0, "url"), "javascript:alert(1)"),
    (("news", "items", 0, "url"), "https://user:password@example.org/news"),
    (("news", "items", 0, "url"), "https://127.0.0.1/news"),
    (("news", "items", 0, "url"), "https://localhost/news"),
    (("news", "items", 0, "url"), "https://example.org:99999/news"),
    (("news", "items", 0, "summary"), "/Users/owner/private.json"),
    (("news", "items", 0, "summary"), "x" * 601),
    (("community", "records"), 4),
    (("community", "classified"), 3),
    (("community", "unknown"), 0),
    (("community", "available_at_cutoff"), 1),
    (("community", "stance_balance"), 100),
    (("community", "stance_balance"), None),
    (("community", "window_end"), "2026-10-01T00:00:00Z"),
    (("sources", 0, "records"), -1),
    (("sources", 0, "detail"), "file:///private/source.json"),
    (("limitations",), "Not a list"),
])
def test_invalid_numbers_timing_states_and_private_values_rejected(client, snapshot, path, value):
    node = snapshot
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    write_snapshot(snapshot)
    assert client.get("/api/research/financial-sentiment/context").status_code == 503


@pytest.mark.parametrize("path", [
    ("price_received_at",), ("summary", "sma50"), ("news", "received_at"),
    ("news", "items", 0, "published_at"), ("community", "window_end"),
])
def test_missing_fields_are_not_silently_converted_to_null(client, snapshot, path):
    node = snapshot
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    write_snapshot(snapshot)
    assert client.get("/api/research/financial-sentiment/context").status_code == 503


@pytest.mark.parametrize("field", ["benchmarks", "intraday", "daily", "levels", "sources"])
def test_duplicate_points_and_records_rejected(client, snapshot, field):
    snapshot[field].append(copy.deepcopy(snapshot[field][0]))
    write_snapshot(snapshot)
    assert client.get("/api/research/financial-sentiment/context").status_code == 503


def test_same_instant_with_different_offsets_is_still_a_duplicate(client, snapshot):
    point = copy.deepcopy(snapshot["intraday"][1])
    point["timestamp"] = "2026-10-12T12:00:00-04:00"
    snapshot["intraday"].append(point)
    write_snapshot(snapshot)
    assert client.get("/api/research/financial-sentiment/context").status_code == 503


def test_missing_source_samples_and_zero_directional_stance_are_honest_nulls(client, snapshot):
    snapshot["summary"] = {key: None for key in snapshot["summary"]}
    snapshot["price_received_at"] = None
    for field in ("intraday", "daily", "levels"):
        snapshot[field] = []
    snapshot["news"] = {"status": "Unavailable", "received_at": None, "records_total": 0,
                        "precutoff_publications": 0, "usable_at_cutoff": 0, "items": []}
    snapshot["community"].update(bullish=0, bearish=0, mixed=0, unknown=5, classified=0, stance_balance=None)
    snapshot["sources"][0].update(records=None, received_at=None, status="Unavailable")
    write_snapshot(snapshot)
    response = client.get("/api/research/financial-sentiment/context")
    assert response.status_code == 200
    assert response.json() == snapshot


def test_unknown_publication_time_is_preserved_without_claiming_availability(client, snapshot):
    snapshot["news"]["items"][0].update(published_at=None, timing="publication_time_unknown")
    snapshot["news"].update(precutoff_publications=1, usable_at_cutoff=0)
    write_snapshot(snapshot)
    assert client.get("/api/research/financial-sentiment/context").json() == snapshot


def test_daily_cutoff_uses_new_york_date_not_utc_date(client, snapshot):
    snapshot["analysis_cutoff"] = "2026-10-13T01:00:00Z"  # October 12, 21:00 in New York.
    snapshot["generated_at"] = "2026-10-13T01:10:00Z"
    snapshot["news"]["items"] = []
    snapshot["daily"][0]["date"] = "2026-10-13"
    write_snapshot(snapshot)
    assert client.get("/api/research/financial-sentiment/context").status_code == 503
