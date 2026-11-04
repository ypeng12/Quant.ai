import hashlib
import json
import stat

import pytest

from app.broker.profit_shadow_artifact import prepare_shadow_artifact


@pytest.fixture(autouse=True)
def clear_configuration(monkeypatch):
    monkeypatch.delenv("QUANT_SHADOW_POLICY_PATH", raising=False)
    monkeypatch.delenv("QUANT_SHADOW_POLICY_JSON", raising=False)


def test_unconfigured_and_path_only_do_not_write(tmp_path, monkeypatch):
    assert prepare_shadow_artifact(tmp_path) == (None, {})
    monkeypatch.setenv("QUANT_SHADOW_POLICY_PATH", "private/model.json")
    assert prepare_shadow_artifact(tmp_path) == (str(tmp_path / "private/model.json"), {})
    assert list(tmp_path.iterdir()) == []


def test_inline_model_is_exact_private_atomic_materialization(tmp_path, monkeypatch):
    raw = json.dumps({"kind": "profit_signal_shadow_v1", "deployment": "shadow_only",
                      "trained_before": "2026-11-05", "spec": {"name": "ridge30_plan"}})
    monkeypatch.setenv("QUANT_SHADOW_POLICY_JSON", raw)
    path, metadata = prepare_shadow_artifact(tmp_path)
    from pathlib import Path
    path = Path(path)
    assert path.read_text() == raw
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert metadata == {"model_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                        "model_trained_before": "2026-11-05", "candidate": "ridge30_plan"}
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("raw", ['{"kind":"live"}', 'broken', ' ' * 65537])
def test_invalid_inline_does_not_replace_existing(tmp_path, monkeypatch, raw):
    path = tmp_path / "model.json"
    path.write_text("previous-model")
    monkeypatch.setenv("QUANT_SHADOW_POLICY_PATH", str(path))
    monkeypatch.setenv("QUANT_SHADOW_POLICY_JSON", raw)
    with pytest.raises(ValueError):
        prepare_shadow_artifact(tmp_path)
    assert path.read_text() == "previous-model"


def test_failed_atomic_replace_preserves_old_model_and_removes_temp(tmp_path, monkeypatch):
    path = tmp_path / "model.json"
    path.write_text("previous-model")
    monkeypatch.setenv("QUANT_SHADOW_POLICY_PATH", str(path))
    monkeypatch.setenv("QUANT_SHADOW_POLICY_JSON", json.dumps(
        {"kind": "profit_signal_shadow_v1", "deployment": "shadow_only"}))
    def fail_replace(*args):
        raise OSError("fixture failure")
    monkeypatch.setattr("app.broker.profit_shadow_artifact.os.replace", fail_replace)
    with pytest.raises(OSError):
        prepare_shadow_artifact(tmp_path)
    assert path.read_text() == "previous-model"
    assert list(tmp_path.iterdir()) == [path]


def test_private_configuration_metadata_never_becomes_public_text(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_SHADOW_POLICY_JSON", json.dumps({
        "kind": "profit_signal_shadow_v1", "deployment": "shadow_only",
        "trained_before": {"private": "private-token"}, "spec": {"name": "private-token"}}))
    _, metadata = prepare_shadow_artifact(tmp_path)
    assert set(metadata) == {"model_sha256"}
    assert "private-token" not in str(metadata)


def test_actual_artifact_timestamp_becomes_public_session_date(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_SHADOW_POLICY_JSON", json.dumps({
        "kind": "profit_signal_shadow_v1", "deployment": "shadow_only",
        "trained_before": "2026-11-05T00:00:00-05:00", "spec": {"name": "ridge30_plan"}}))
    _, metadata = prepare_shadow_artifact(tmp_path)
    assert metadata["model_trained_before"] == "2026-11-05"
    assert metadata["candidate"] == "ridge30_plan"
