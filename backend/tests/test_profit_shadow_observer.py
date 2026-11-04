"""Fake-only observer isolation tests: no network, broker or orders are imported."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from app.broker.profit_shadow_observer import ProfitShadowObserver, SYMBOLS, INPUTS, _stamp


def request(at="2026-08-17T10:05:00-04:00"):
    now = pd.Timestamp(at)
    frames = {s: pd.DataFrame({"close": [100., 101.]},
                              index=pd.date_range(now.floor("5min") - pd.Timedelta(minutes=10), periods=2, freq="5min"))
              for s in INPUTS}
    return dict(frames=frames, current=dict.fromkeys(INPUTS, 0.), equity=50_000.,
                allowed=set(SYMBOLS), shortable=dict.fromkeys(INPUTS, True), now=now,
                liquidation_at=now.normalize() + pd.Timedelta(hours=15, minutes=55),
                baseline={"target_weights": dict.fromkeys(INPUTS, 0.),
                          "target_shares": dict.fromkeys(INPUTS, 0), "model": "active_policy",
                          "model_sha256": "a" * 64, "decision_id": "decision-1",
                          "bar_time": (now.floor("5min") - pd.Timedelta(minutes=5)).isoformat()})


class FakeModel:
    def __init__(self):
        self.spec = SimpleNamespace(name="ridge30_plan")
        self.trained_before = "2026-08-17"
        self.state = SimpleNamespace(last_stamp=None)
        self.last_decision = None
        self.calls = []
        self.entered = threading.Event()
        self.release = None
        self.error = None

    def shadow_targets(self, frames, current, equity, **kwargs):
        self.entered.set()
        if self.release:
            assert self.release.wait(5)
        if self.error:
            raise self.error
        self.calls.append(dict(frames=frames, current=current, equity=equity, **kwargs))
        self.last_decision = _stamp(kwargs["as_of"]) - timedelta(minutes=5)
        self.state.last_stamp = self.last_decision
        return {"execution_enabled": False,
                "target_weights": {"NVDA": .1, "SNDK": -.05, "TSLA": 0.},
                "target_shares": {"NVDA": 49, "SNDK": -24, "TSLA": 0},
                "diagnostics": {"cost_assumption_bps": 5, "cost_verified": False}}


@pytest.fixture
def observer(tmp_path, monkeypatch):
    value = ProfitShadowObserver(tmp_path / "private-model.json", tmp_path / "journal")
    model = FakeModel()
    value._model_hash = "b" * 64
    monkeypatch.setattr(value, "_load_model", lambda: model)
    yield value, model
    if model.release:
        model.release.set()
    value.close()


def wait_for(observer, predicate):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        status = observer.status()
        if predicate(status):
            return status
        time.sleep(.005)
    pytest.fail(f"Observer condition not reached: {observer.status()}")


def test_not_configured_and_construction_status_have_no_worker_or_files(tmp_path):
    value = ProfitShadowObserver(None, tmp_path / "journal")
    assert value.status()["state"] == "not_configured"
    assert value.observe(**request()) is False
    assert value._worker is None and not (tmp_path / "journal").exists()
    configured = ProfitShadowObserver(tmp_path / "missing")
    assert configured.status()["state"] == "waiting_for_decision"
    assert configured._worker is None


def test_observation_is_async_copies_inputs_and_preserves_originals(observer):
    value, model = observer
    model.release = threading.Event()
    payload = request()
    before = time.monotonic()
    assert value.observe(**payload)
    assert time.monotonic() - before < .25
    assert model.entered.wait(2)
    # The background calculation remains blocked while the caller continues.
    assert value.status()["state"] == "computing"
    payload["frames"]["NVDA"].iloc[-1, 0] = 999.
    payload["baseline"]["target_shares"]["NVDA"] = 999
    payload["current"]["NVDA"] = .9
    model.release.set()
    status = wait_for(value, lambda s: s["comparison_count"] == 1)
    assert status["max_abs_weight_delta"] == .1
    assert model.calls[0]["frames"]["NVDA"].iloc[-1, 0] == 101.
    assert model.calls[0]["current"]["NVDA"] == 0.
    assert status["execution_enabled"] is False


def test_journal_compares_same_observed_inventory_without_pnl_and_public_details(observer):
    value, _ = observer
    payload = request()
    payload["baseline"]["api_key"] = "should-not-be-recorded"
    value.observe(**payload)
    status = wait_for(value, lambda s: s["comparison_count"] == 1)
    path = next(value.journal_directory.glob("*.jsonl"))
    record = json.loads(path.read_text())
    assert record["candidate_pnl"] is None and record["execution_enabled"] is False
    assert record["delta_shares"] == {"NVDA": 49, "SNDK": -24, "TSLA": 0}
    assert record["baseline_only_symbols"] == ["MSTR"]
    assert record["baseline"]["decision_id"] == "decision-1"
    assert "should-not-be-recorded" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert status["journal_state"] == "written" and status["differing_target_count"] == 2
    public = json.dumps(status)
    for forbidden in (str(value.path), "target_shares", "target_weights", "equity", "decision-1"):
        assert forbidden not in public


def test_same_bar_is_idempotent_even_when_baseline_changes(observer):
    value, model = observer
    value.observe(**request())
    wait_for(value, lambda s: s["comparison_count"] == 1)
    payload = request()
    payload["baseline"]["target_weights"]["NVDA"] = .5
    value.observe(**payload)
    status = wait_for(value, lambda s: s["duplicate_count"] == 1)
    assert len(model.calls) == status["comparison_count"] == 1
    assert status["reason_code"] == "same_bar_already_observed"
    assert status["max_abs_weight_delta"] == .1  # Remains the original comparison.
    assert len(next(value.journal_directory.glob("*.jsonl")).read_text().splitlines()) == 1


def test_integer_share_differences_do_not_round_through_float(observer):
    value, _ = observer
    payload = request()
    original = 2**53 + 1
    payload["baseline"]["target_shares"]["NVDA"] = original
    value.observe(**payload)
    wait_for(value, lambda s: s["comparison_count"] == 1)
    record = json.loads(next(value.journal_directory.glob("*.jsonl")).read_text())
    assert record["delta_shares"]["NVDA"] == 49 - original


def test_busy_worker_has_one_latest_pending_snapshot(observer):
    value, model = observer
    model.release = threading.Event()
    value.observe(**request())
    assert model.entered.wait(2)
    value.observe(**request("2026-08-17T10:10:00-04:00"))
    value.observe(**request("2026-08-17T10:15:00-04:00"))
    assert value.status()["skipped_count"] == 1
    model.release.set()
    status = wait_for(value, lambda s: s["comparison_count"] == 2)
    assert len(model.calls) == 2
    assert model.calls[-1]["as_of"].minute == 15
    assert status["bar_time"].startswith("2026-08-17T10:10")


@pytest.mark.parametrize("kind,reason", [
    ("stale", "model_session_mismatch"),
    ("nonflat", "holding_start_unknown"),
    ("gap", "holding_observation_gap"),
    ("missing", "input_symbols_missing"),
    ("wrong_clock", "baseline_clock_mismatch"),
])
def test_unavailable_evidence_is_explicit_without_calculating(observer, kind, reason):
    value, model = observer
    payload = request()
    if kind == "stale":
        model.trained_before = "2026-08-16"
    elif kind == "nonflat":
        payload["current"]["NVDA"] = .1
    elif kind == "gap":
        model.last_decision = model.state.last_stamp = _stamp("2026-08-17T09:45:00-04:00")
        payload["current"]["NVDA"] = .1
    elif kind == "missing":
        del payload["frames"]["MSTR"]
    else:
        payload["baseline"]["bar_time"] = "2026-08-17T09:55:00-04:00"
    value.observe(**payload)
    status = wait_for(value, lambda s: s["state"] == "unavailable")
    assert status["reason_code"] == reason
    assert status["comparison_count"] == 0 and not model.calls


def test_failed_calculation_isolated_and_error_message_is_not_published(observer):
    value, model = observer
    model.error = RuntimeError("/private/account-secret/model.json")
    payload = request()
    value.observe(**payload)
    status = wait_for(value, lambda s: s["state"] == "unavailable")
    assert status["error_type"] == "RuntimeError"
    assert "account-secret" not in json.dumps(status)
    assert payload["baseline"]["target_shares"] == dict.fromkeys(INPUTS, 0)
    model.error = None
    value.observe(**payload)
    assert wait_for(value, lambda s: s["comparison_count"] == 1)["state"] == "observed"


def test_invalid_baseline_does_not_kill_worker_or_leak_text(observer):
    value, _ = observer
    bad = request()
    bad["baseline"] = "private-secret"
    value.observe(**bad)
    status = wait_for(value, lambda s: s["state"] == "unavailable")
    assert status["reason_code"] == "baseline_unavailable"
    assert "private-secret" not in json.dumps(status)
    value.observe(**request())
    wait_for(value, lambda s: s["comparison_count"] == 1)


def test_journal_failure_does_not_invalidate_target_comparison(observer, tmp_path):
    value, _ = observer
    occupied = tmp_path / "file-not-directory"
    occupied.write_text("occupied")
    value.journal_directory = occupied
    value.observe(**request())
    status = wait_for(value, lambda s: s["comparison_count"] == 1)
    assert status["state"] == "observed" and status["journal_state"] == "unavailable"


def test_artifact_reload_hashes_bytes_and_does_not_reset_state_for_timestamp_only(tmp_path, monkeypatch):
    from app.research.profit_signal_shadow import ProfitSignalShadowModel
    models = []
    def load(path):
        models.append(FakeModel())
        return models[-1]
    monkeypatch.setattr(ProfitSignalShadowModel, "load", load)
    path = tmp_path / "artifact.json"
    path.write_text('{"fixture":1}')
    value = ProfitShadowObserver(path)
    first = value._load_model()
    first.state.last_stamp = "existing-state"
    path.touch()
    assert value._load_model() is first and len(models) == 1
    assert value._model_hash == hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_text('{"fixture":2}')
    second = value._load_model()
    assert second is not first and second.state.last_stamp is None
    assert len(models) == 2


def test_thread_start_failure_returns_without_raising(observer, monkeypatch):
    value, _ = observer
    def fail(_self):
        raise RuntimeError("private-thread-detail")
    monkeypatch.setattr(threading.Thread, "start", fail)
    assert not value.observe(**request())
    status = value.status()
    assert status["state"] == "unavailable" and status["error_type"] == "RuntimeError"
    assert value._worker is None and value._pending is None
    assert "private-thread-detail" not in json.dumps(status)
