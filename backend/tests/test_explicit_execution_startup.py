"""Fake-only lifecycle and submission tests; never import main_api or brokers."""
import ast
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from app.broker.decision_journal import append_receipt
from test_research_execution import runner_type, closing_runner


@pytest.fixture
def stopped_runner(runner_type, monkeypatch):
    effects = {"saved_config": [], "connections": [], "threads": [], "sync_workers": []}
    namespace = runner_type.__init__.__globals__
    monkeypatch.setitem(namespace, "WATCHLIST", ["A"])
    monkeypatch.setitem(namespace, "time", time)
    monkeypatch.setitem(namespace, "invalidate_cache", lambda: None)
    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.running = False
            effects["threads"].append(self)
        def start(self):
            self.running = True  # Never execute target or open an event loop.
        def is_alive(self):
            return self.running
    monkeypatch.setitem(namespace, "threading", SimpleNamespace(Thread=FakeThread, RLock=threading.RLock, Lock=threading.Lock))
    monkeypatch.setattr(runner_type, "load_trade_history", lambda self: None)
    monkeypatch.setattr(runner_type, "load_runner_config", lambda self: None)
    monkeypatch.setattr(runner_type, "save_runner_config", lambda self: effects["saved_config"].append(self.is_running))
    monkeypatch.setattr(runner_type, "add_log", lambda self, msg: self.logs.append(msg))
    def connect(self):
        effects["connections"].append(True)
        self.adapter = SimpleNamespace()
        self._broker_connection = {"connected": True, "is_paper": True, "credential_source": "fake_test"}
    monkeypatch.setattr(runner_type, "init_alpaca_adapter", connect)
    monkeypatch.setattr(runner_type, "_start_order_sync_worker", lambda self: effects["sync_workers"].append(True))
    return runner_type(), effects


def test_constructor_and_status_are_stopped_without_workers_or_config_writes(stopped_runner):
    runner, effects = stopped_runner
    assert not runner.is_running
    assert runner.get_status()["quant_policy"]["state"] == "stopped"
    assert effects["threads"] == effects["sync_workers"] == effects["saved_config"] == []
    assert len(effects["connections"]) == 1  # Only fake read-only account connection.


def test_explicit_start_stop_and_stopped_cycle_preserve_user_controls(stopped_runner):
    runner, effects = stopped_runner
    assert runner.start()
    assert runner.is_running and len(effects["threads"]) == 1
    assert not runner.start()  # No duplicate execution worker.
    assert runner.stop() and not runner.is_running
    runner._run_quant_policy_cycle()  # Fake adapter has no broker methods: must not be touched.
    assert runner.get_status()["quant_policy"]["state"] == "stopped"
    assert effects["saved_config"] == [True, False]
    assert not runner.stop()


def test_disconnected_explicit_start_and_toggle_do_not_claim_running(stopped_runner, monkeypatch):
    runner, effects = stopped_runner
    monkeypatch.setattr(runner, "init_alpaca_adapter", lambda: setattr(runner, "_broker_connection", {"connected": False, "reason": "Fake unavailable"}))
    result = runner.toggle()
    assert not result["is_running"] and result["status"] == "not_started"
    assert effects["threads"] == effects["sync_workers"] == []


def test_simultaneous_start_requests_create_only_one_worker(stopped_runner, monkeypatch):
    runner, effects = stopped_runner
    entered, release = threading.Event(), threading.Event()
    original = runner.init_alpaca_adapter
    def slow_fake_connection():
        entered.set()
        assert release.wait(2)
        original()
    monkeypatch.setattr(runner, "init_alpaca_adapter", slow_fake_connection)
    results = []
    first = threading.Thread(target=lambda: results.append(runner.start()))
    second = threading.Thread(target=lambda: results.append(runner.start()))
    first.start()
    assert entered.wait(2)
    second.start()
    release.set()
    first.join(2); second.join(2)
    assert not first.is_alive() and not second.is_alive()
    assert sorted(results) == [False, True]
    assert len(effects["threads"]) == len(effects["sync_workers"]) == 1


def test_API_startup_and_top_level_never_call_execution_start():
    source = Path(__file__).resolve().parents[1] / "main_api.py"
    tree = ast.parse(source.read_text())
    startup = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                       and d.func.attr == "on_event" and d.args
                       and isinstance(d.args[0], ast.Constant) and d.args[0].value == "startup"
                       for d in node.decorator_list)]
    top_level = [node for node in tree.body if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    for node in [*startup, *top_level]:
        assert not any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                       and isinstance(call.func.value, ast.Name) and call.func.value.id == "live_runner"
                       and call.func.attr in {"start", "toggle"} for call in ast.walk(node))


def regular_runner(runner_type, submit):
    from app.quant_policy import PolicySpec
    runner, _ = closing_runner(runner_type, [], [], submit)
    runner.adapter.get_clock = lambda: dict(success=True, is_open=True, timestamp="2026-09-14T10:10:00-04:00", next_close="2026-09-14T16:00:00-04:00")
    runner.adapter.client.get_asset = lambda symbol: SimpleNamespace(shortable=True)
    runner._quant_broker_snapshot = lambda: ([], [], {"equity": 1000., "buying_power": 1000., "shorting_enabled": True})
    model = SimpleNamespace(symbols=("A",), trained_before="2026-09-12", spec=PolicySpec(name="fake_test", feature_set="price_volume"),
                            forecast=lambda frames: SimpleNamespace(mu={"A": .02}, covariance=np.array([[.0001]])))
    runner._quant_model = lambda: model
    runner._quant_model_key, runner._quant_last_bar = ("fake_test", 1), None
    return runner


def test_new_bar_appearing_during_computation_blocks_old_signal_submission(runner_type):
    submitted = []
    runner = regular_runner(runner_type, lambda *args, **kwargs: submitted.append(True))
    clocks = iter(["2026-09-14T10:10:00-04:00", "2026-09-14T10:15:01-04:00"])
    runner.adapter.get_clock = lambda: dict(success=True, is_open=True, timestamp=next(clocks), next_close="2026-09-14T16:00:00-04:00")
    runner._run_quant_policy_cycle()
    assert not submitted
    assert runner._quant_status["state"] == "stale_decision_recheck"


def test_private_receipts_exclude_account_fields_and_write_before_submission(runner_type, tmp_path):
    seen = []
    directory = tmp_path / "receipts"
    def submit(*args, **kwargs):
        rows = [json.loads(line) for path in directory.glob("*.jsonl") for line in path.read_text().splitlines()]
        assert [r["kind"] for r in rows] == ["decision", "order_intent"]
        seen.extend(rows)
        return {"success": True, "status": "accepted", "order_id": "fake-broker-order"}
    runner = regular_runner(runner_type, submit)
    runner._decision_audit_directory = directory
    runner._run_quant_policy_cycle()
    rows = [json.loads(line) for path in directory.glob("*.jsonl") for line in path.read_text().splitlines()]
    assert [r["kind"] for r in rows] == ["decision", "order_intent", "order_result"]
    assert len({r["decision_id"] for r in rows}) == 1
    assert all(r["historical_gap_backfilled"] is False for r in rows)
    assert rows[0]["cost_verified"] is False
    assert rows[-1]["status"] == "accepted" and runner.trade_history == []
    append_receipt(directory, {"kind": "decision", "decision_id": "fake", "account_number": "private", "api_key": "secret"})
    content = "".join(path.read_text() for path in directory.glob("*.jsonl"))
    assert "private" not in content and "secret" not in content and "fake-broker-order" not in content


def test_unwritable_decision_receipt_blocks_new_risk(runner_type, tmp_path):
    submitted = []
    runner = regular_runner(runner_type, lambda *args, **kwargs: submitted.append(True))
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupied")
    runner._decision_audit_directory = blocked
    runner._run_quant_policy_cycle()
    assert not submitted
    assert runner._quant_status["state"] == "decision_audit_unavailable"
    assert runner._quant_last_bar is None  # Next cycle may retry after storage recovers.


def test_audit_storage_failure_does_not_block_existing_position_reduction(runner_type, tmp_path, monkeypatch):
    submitted = []
    runner = regular_runner(runner_type, lambda *args, **kwargs: submitted.append(args) or {"success": True, "status": "accepted"})
    runner._quant_broker_snapshot = lambda: ([], [{"ticker": "A", "shares": 2, "current_price": 100}],
                                            {"equity": 1000., "buying_power": 1000., "shorting_enabled": True})
    monkeypatch.setitem(runner_type._run_quant_policy_cycle.__globals__, "load_watchlist", lambda: [])
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupied")
    runner._decision_audit_directory = blocked
    runner._run_quant_policy_cycle()
    assert submitted == [("A", 2.0, "sell")]
    assert runner.trade_history == []  # An accepted reduction is not a fabricated fill.


def test_scheduled_flatten_has_its_own_receipt_not_previous_forecast(runner_type, tmp_path):
    runner, _ = closing_runner(runner_type, [{"ticker": "A", "shares": 2, "current_price": 100}], [],
                               lambda *args, **kwargs: {"success": True, "status": "accepted"})
    runner._quant_decision_id = "prior-forecast-receipt"
    runner._decision_audit_directory = tmp_path / "receipts"
    runner._run_quant_policy_cycle()
    rows = [json.loads(line) for path in runner._decision_audit_directory.glob("*.jsonl")
            for line in path.read_text().splitlines()]
    assert [row["kind"] for row in rows] == ["order_intent", "order_result"]
    assert rows[0]["intent_reason"] == "scheduled_flatten"
    assert rows[0]["decision_id"] != "prior-forecast-receipt"
    assert rows[1]["decision_id"] == rows[0]["decision_id"]
