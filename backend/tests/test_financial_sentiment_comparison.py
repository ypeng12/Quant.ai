"""Exercise the saved comparison API without importing the trading service."""

import copy
import json
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import financial_sentiment_comparison as comparison


@pytest.fixture
def snapshot():
    return {
        "schema_version": 1, "generated_at": "2026-10-28T12:00:00-04:00",
        "evaluation_kind": "retrospective_development", "requested_start": "2026-10-01",
        "requested_end": "2026-10-05", "evaluated_start": "2026-10-01",
        "evaluated_end": "2026-10-02", "sessions": 2, "starting_capital": 100000., "currency": "USD",
        "models": [{"id": ident, "name": ident, "description": "Saved research candidate.",
                    "net_pnl": pnl, "net_return": pnl/100000, "max_drawdown": -.01,
                    "costs": 20., "fill_count": 2, "mean_gross_exposure": .5,
                    "mean_daily_turnover": 1.} for ident, pnl in (("A", -100), ("B", 50), ("C", 50))],
        "curves": [{"date": "2026-10-01", "A": 99950., "B": 100020., "C": 100020.},
                   {"date": "2026-10-02", "A": 99900., "B": 100050., "C": 100050.}],
        "text": {"source_records": 3, "usable_decisions": 0, "changed_decisions": 0,
                 "calibration_status": "Unavailable", "fallback_reason": "No calibrated text return signal."},
        "coverage": {"complete_requested_period": False, "missing_sessions": ["2026-10-05"]},
        "limitations": ["Assumed friction; not broker account performance."], "promoted": False,
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(comparison, "PUBLIC_COMPARISON_PATH", tmp_path / "comparison.json")
    app = FastAPI()
    app.include_router(comparison.router)
    with TestClient(app) as value:
        yield value


def write(snapshot):
    comparison.PUBLIC_COMPARISON_PATH.write_text(json.dumps(snapshot), encoding="utf-8")


def test_public_projection_and_read_only_route(client, snapshot):
    value = copy.deepcopy(snapshot)
    def inject(item):
        if isinstance(item, dict):
            for child in list(item.values()):
                inject(child)
            item.update(account_id="secret", raw_body="private text", path="/Users/private/data")
        elif isinstance(item, list):
            for child in item:
                inject(child)
    inject(value)
    write(value)
    response = client.get("/api/research/financial-sentiment/comparison")
    assert response.status_code == 200
    assert response.json() == snapshot
    assert client.post("/api/research/financial-sentiment/comparison").status_code == 405


def test_missing_report_is_not_generated(client):
    assert client.get("/api/research/financial-sentiment/comparison").status_code == 404
    assert not comparison.PUBLIC_COMPARISON_PATH.exists()


@pytest.mark.parametrize("path,value", [
    (("schema_version",), True), (("promoted",), True),
    (("models", 0, "net_pnl"), float("nan")),
    (("models", 0, "net_return"), .5),
    (("models", 0, "costs"), -1),
    (("models", 0, "fill_count"), True),
    (("models", 0, "max_drawdown"), .1),
    (("models", 0, "description"), "/Users/private/data"),
    (("models", 1, "id"), "A"),
    (("curves", 1, "A"), 100000),
    (("curves", 0, "B"), 100100),
    (("curves", 1, "date"), "2026-10-01"),
    (("sessions",), 3), (("generated_at",), "2026-10-28T12:00:00"),
    (("evaluated_end",), "2026-10-06"),
    (("text", "changed_decisions"), 1),
    (("coverage", "complete_requested_period"), True),
])
def test_invalid_evidence_is_unavailable_without_private_paths(client, snapshot, path, value):
    cursor = snapshot
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    write(snapshot)
    response = client.get("/api/research/financial-sentiment/comparison")
    assert response.status_code == 503
    assert str(comparison.PUBLIC_COMPARISON_PATH) not in response.text


@pytest.mark.parametrize("value", ["{broken", "null", "[]", "{}"])
def test_malformed_report_is_unavailable(client, value):
    comparison.PUBLIC_COMPARISON_PATH.write_text(value)
    assert client.get("/api/research/financial-sentiment/comparison").status_code == 503
