import sys
from pathlib import Path

from fastapi.testclient import TestClient

from backend.signal_lab.api import AUDIT, create_app


def test_audit_counts_and_honest_model_status():
    result = TestClient(create_app()).get("/api/research/signal-lab/status")
    assert result.status_code == 200
    data = result.json()
    counts = {s["id"]: s["records"] for s in data["sources"]}
    assert counts == {"news": 187, "futu": 120, "prices": 2730, "sec": 94, "x": None}
    assert data["exploratory_labels"] == 90
    assert data["labels_are_predictions"] is False
    assert data["model_status"] == "Not trained"


def test_futu_deduplicates_and_filters_without_inventing_arrival_times():
    client = TestClient(create_app())
    all_rows = client.get("/api/research/signal-lab/events?source=futu&limit=100").json()
    assert all_rows["total"] == 118
    assert len({row["id"] for row in all_rows["items"]}) == 100
    assert all(row["received_at"] is None for row in all_rows["items"])
    filtered = client.get("/api/research/signal-lab/events?source=futu&symbol=PLTR&limit=100").json()
    assert filtered["total"] == 30
    assert all("PLTR" in row["symbols"] for row in filtered["items"])


def test_invalid_source_and_limit_are_rejected():
    client = TestClient(create_app())
    assert client.get("/api/research/signal-lab/events?source=../../.env").status_code == 422
    assert client.get("/api/research/signal-lab/events?limit=10001").status_code == 422


def test_missing_snapshot_is_explicit(tmp_path: Path):
    client = TestClient(create_app(audit_dir=tmp_path))
    assert client.get("/api/research/signal-lab/status").status_code == 503
    assert client.get("/api/research/signal-lab/health").json()["status"] == "ok"


def test_research_app_has_no_trading_routes_or_imports():
    client = TestClient(create_app())
    assert client.post("/api/live/start").status_code == 404
    assert "app.broker.live_runner" not in sys.modules
    assert "backend.main_api" not in sys.modules
    assert client.get("/api/research/signal-lab/plan").status_code == 200
