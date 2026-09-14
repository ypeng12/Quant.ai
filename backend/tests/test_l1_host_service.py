"""Host lifecycle diagnostics must not mistake stale files for a collector."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def manager():
    path = Path(__file__).resolve().parents[2] / "scripts/manage_l1_capture.py"
    spec = importlib.util.spec_from_file_location("l1_host_service", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config(manager, tmp_path, **kwargs):
    return manager.service_config("/usr/bin/python3", tmp_path / "runtime",
                                  tmp_path / "events", tmp_path / ".env",
                                  ["SNDK", "TSLA"], "iex", tmp_path / "logs", **kwargs)


def test_collection_uses_standard_scheduling_without_default_sleep_assertion(manager, tmp_path):
    value = config(manager, tmp_path)
    assert value["ProcessType"] == "Standard"
    assert value["LowPriorityIO"] is False
    assert value["LowPriorityBackgroundIO"] is False
    assert value["ProgramArguments"][0] == "/usr/bin/python3"
    assert "caffeinate" not in repr(value)
    assert value["KeepAlive"] is True
    assert value["ExitTimeOut"] == 30  # Allow SDK shutdown and the bounded writer drain.
    assert value.get("AbandonProcessGroup", False) is False


def test_optional_sleep_assertion_is_ac_only_and_tied_to_collector(manager, tmp_path):
    direct = config(manager, tmp_path)
    protected = config(manager, tmp_path, prevent_sleep_ac=True)
    assert protected["ProgramArguments"] == ["/usr/bin/caffeinate", "-s", *direct["ProgramArguments"]]
    assert "-d" not in protected["ProgramArguments"]
    assert "-i" not in protected["ProgramArguments"]
    assert protected["EnvironmentVariables"] == {"PYTHONUNBUFFERED": "1"}


def test_direct_collector_identity_is_verified(manager, tmp_path):
    script = str(tmp_path / "scripts/capture_alpaca_l1.py")
    rows = {101: {"pid": 101, "ppid": 1, "args": ["python3", "-u", script]}}
    assert manager.collector_process_relation(101, {"pid": 101}, tmp_path,
                                              inspect_process=rows.get) == "direct"


def test_caffeinate_child_is_verified_separately_from_launchd_pid(manager, tmp_path):
    script = str(tmp_path / "scripts/capture_alpaca_l1.py")
    rows = {
        101: {"pid": 101, "ppid": 1, "args": ["/usr/bin/caffeinate", "-s", "python3", script]},
        102: {"pid": 102, "ppid": 101, "args": ["python3", script]},
    }
    assert manager.collector_process_relation(101, {"pid": 102}, tmp_path,
                                              inspect_process=rows.get) == "caffeinate_child"


@pytest.mark.parametrize("pid,rows", [
    (101, {}),  # exited collector, stale status
    (101, {101: {"pid": 101, "ppid": 1, "args": ["python3", "unrelated.py"]}}),
    (None, {}),
    (-1, {}),
    (True, {}),
])
def test_stale_or_invalid_status_cannot_claim_running(manager, tmp_path, pid, rows):
    assert manager.collector_process_relation(101, {"pid": pid}, tmp_path,
                                              inspect_process=rows.get) == "unverified"


def test_an_unrelated_capture_is_not_the_supervised_collector(manager, tmp_path):
    script = str(tmp_path / "scripts/capture_alpaca_l1.py")
    rows = {
        101: {"pid": 101, "ppid": 1, "args": ["/usr/bin/caffeinate", "-s", "python3", script]},
        102: {"pid": 102, "ppid": 999, "args": ["python3", script]},
    }
    assert manager.collector_process_relation(101, {"pid": 102}, tmp_path,
                                              inspect_process=rows.get) == "unverified"


def test_receive_age_retains_negative_clock_offset_and_missing_state(manager):
    future = datetime.now(timezone.utc) + timedelta(seconds=60)
    assert manager.received_age_seconds({"last_received_at": future.isoformat()}) < 0
    assert manager.received_age_seconds(None) is None
    assert manager.received_age_seconds({"last_received_at": "bad"}) is None
    assert manager.received_age_seconds({"last_received_at": "2026-09-14T10:00:00"}) is None
