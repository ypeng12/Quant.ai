"""Fake-only proof that the optional comparison cannot alter execution."""
from copy import deepcopy
import os
import sys
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest

from app.research.holding_policy import HoldingSpec
from test_explicit_execution_startup import regular_runner, stopped_runner
from test_research_execution import closing_runner, runner_type


@pytest.fixture
def shadow_probe(monkeypatch):
    """Replace only the optional observer and artifact setup, never a broker."""
    monkeypatch.delenv("QUANT_SHADOW_POLICY_PATH", raising=False)
    monkeypatch.delenv("QUANT_SHADOW_POLICY_JSON", raising=False)
    probe = SimpleNamespace(mode="success", constructions=[], calls=[], events=[])
    artifact = ModuleType("app.broker.profit_shadow_artifact")
    artifact.prepare_shadow_artifact = lambda backend: (
        os.environ.get("QUANT_SHADOW_POLICY_PATH"), {})
    observer = ModuleType("app.broker.profit_shadow_observer")

    class FakeObserver:
        def __init__(self, path, journal_directory=None):
            probe.constructions.append((path, journal_directory))
            probe.events.append("construct")
            if probe.mode == "constructor_error":
                raise OSError("Private model path /private/test-only/model.json")

        def observe(self, frames, current, equity, allowed, shortable, now,
                    liquidation_at, baseline):
            probe.events.append("observe")
            probe.calls.append(deepcopy({
                "frames": frames, "current": current, "equity": equity,
                "allowed": allowed, "shortable": shortable, "now": now,
                "liquidation_at": liquidation_at, "baseline": baseline,
            }))
            if probe.mode == "observe_error":
                raise RuntimeError("Private model path /private/test-only/model.json")
            if probe.mode == "mutate":
                for frame in frames.values():
                    frame.iloc[:, :] = -999
                current["A"] = -999
                shortable["A"] = False
                baseline["target_shares"]["A"] = -999
                baseline["target_weights"]["A"] = -999
            # A return value must never enter the active policy's target chain.
            return {"target_shares": {"A": -999}, "target_weights": {"A": -999}}

        def status(self):
            if probe.mode == "status_error":
                raise RuntimeError("Private model path /private/test-only/model.json")
            return {"configured": True, "execution_enabled": False,
                    "state": "ready", "comparison_count": len(probe.calls)}

    observer.ProfitShadowObserver = FakeObserver
    monkeypatch.setitem(sys.modules, artifact.__name__, artifact)
    monkeypatch.setitem(sys.modules, observer.__name__, observer)
    return probe


def active_runner(runner_type, probe, *, target=.4, cap=.7):
    submitted, receipts, inputs = [], [], []

    def submit(*args, **kwargs):
        probe.events.append("order")
        submitted.append((args, kwargs))
        return {"success": True, "status": "accepted", "order_id": "fake-order"}

    runner = regular_runner(runner_type, submit)
    runner.is_running = True
    runner.strategy_params["max_single_position_equity_pct"] = cap

    def live_target(frames, current, **kwargs):
        inputs.append({"frames": frames, "current": current, **kwargs})
        return {"A": target}, {"cumulative_forecast_bps": {"A": {"5": 10.}},
                               "l1_contributes": False, "active_features": 58}

    spec = HoldingSpec(horizons=(1,), planning=False)
    runner._quant_model = lambda: SimpleNamespace(
        symbols=("A",), input_symbols=("A", "SPY"),
        trained_before="2026-09-12", spec=spec, live_target=live_target)
    runner._quant_model_sha256 = "a" * 64
    runner._record_execution_receipt = lambda payload: receipts.append(deepcopy(payload)) or True
    return runner, submitted, receipts, inputs


def execution_snapshot(runner, orders, receipts):
    return deepcopy({"targets": runner._quant_targets, "orders": orders,
                     "receipts": receipts, "status": runner._quant_status,
                     "submissions": runner._quant_submissions,
                     "opportunities": runner.intraday_opportunities,
                     "directions": runner.ticker_directions,
                     "trades": runner.trade_history})


@pytest.mark.parametrize("mode", ["success", "observe_error", "constructor_error", "mutate"])
def test_optional_observer_preserves_exact_original_execution(
        runner_type, monkeypatch, shadow_probe, mode):
    original, original_orders, original_receipts, _ = active_runner(runner_type, shadow_probe)
    original._run_quant_policy_cycle()
    expected = execution_snapshot(original, original_orders, original_receipts)
    assert original_orders and original._quant_targets == {"A": 4}
    assert shadow_probe.constructions == shadow_probe.calls == []

    monkeypatch.setenv("QUANT_SHADOW_POLICY_PATH", "/private/test-only/model.json")
    shadow_probe.mode = mode
    shadow_probe.events.clear()
    compared, compared_orders, compared_receipts, _ = active_runner(runner_type, shadow_probe)
    compared._run_quant_policy_cycle()

    assert execution_snapshot(compared, compared_orders, compared_receipts) == expected
    assert compared.trade_history == []  # Accepted submission is not a broker fill.
    assert len(shadow_probe.constructions) == 1
    assert shadow_probe.events[0] == "order"
    assert shadow_probe.events[1] == "construct"
    assert len(shadow_probe.calls) == (0 if mode == "constructor_error" else 1)
    public = compared._profit_signal_shadow_status()
    assert public["execution_enabled"] is False
    assert "/private/" not in str(public)
    if mode.endswith("error"):
        assert public["state"] == "unavailable"


def test_observer_receives_final_capped_baseline_and_independent_inputs(
        runner_type, monkeypatch, shadow_probe):
    monkeypatch.setenv("QUANT_SHADOW_POLICY_PATH", "/private/test-only/model.json")
    shadow_probe.mode = "mutate"
    runner, orders, receipts, inputs = active_runner(runner_type, shadow_probe, target=.9, cap=.3)
    runner._run_quant_policy_cycle()
    assert orders and runner._quant_targets == {"A": 3}
    assert len(shadow_probe.calls) == len(inputs) == 1
    observed = shadow_probe.calls[0]
    baseline = observed["baseline"]
    decision = next(row for row in receipts if row["kind"] == "decision")
    assert baseline == {
        "target_weights": {"A": .3}, "target_shares": {"A": 3},
        "model": decision["model_name"], "model_sha256": "a" * 64,
        "decision_id": decision["decision_id"], "bar_time": decision["bar_open_at"],
    }
    assert set(observed["frames"]) == {"A", "SPY"}
    assert observed["current"] == {"A": 0.}
    assert observed["equity"] == 1000.
    assert observed["allowed"] == ("A",) and observed["shortable"] == {"A": True}
    assert observed["now"] == pd.Timestamp("2026-09-14T10:10:00-04:00")
    assert observed["liquidation_at"] == pd.Timestamp("2026-09-14T15:55:00-04:00")
    # The deliberately mutating observer cannot change model-owned inputs or
    # the active strategy's target dictionaries after its order is submitted.
    original = inputs[0]
    assert original["current"] == {"A": 0.}
    assert original["shortable"] == {"A": True}
    for symbol, frame in original["frames"].items():
        pd.testing.assert_frame_equal(frame, observed["frames"][symbol])
    assert runner.intraday_opportunities["A"]["target_weight"] == .3
    assert runner._quant_status["target_shares"] == {"A": 3}


def test_repeated_completed_bar_does_not_repeat_forecast_observation_or_order(
        runner_type, monkeypatch, shadow_probe):
    monkeypatch.setenv("QUANT_SHADOW_POLICY_PATH", "/private/test-only/model.json")
    runner, orders, _, inputs = active_runner(runner_type, shadow_probe)
    runner._run_quant_policy_cycle()
    runner._run_quant_policy_cycle()
    assert len(inputs) == len(shadow_probe.calls) == len(orders) == 1
    assert shadow_probe.events == ["order", "construct", "observe"]


def test_scheduled_flatten_does_not_construct_or_run_observer(
        runner_type, monkeypatch, shadow_probe):
    monkeypatch.setenv("QUANT_SHADOW_POLICY_PATH", "/private/test-only/model.json")
    orders = []
    runner, _ = closing_runner(
        runner_type, [{"ticker": "A", "shares": 2, "current_price": 100}], [],
        lambda *args, **kwargs: orders.append(args) or {"success": True, "status": "accepted"})
    runner.is_running = True
    runner._run_quant_policy_cycle()
    assert orders == [("A", 2, "sell")]
    assert runner._quant_targets == {"A": 0}
    assert runner._quant_status["state"] == "session_close"
    assert shadow_probe.constructions == shadow_probe.calls == []


def test_stopped_construction_status_and_cycle_do_not_start_observer(
        request, monkeypatch, shadow_probe):
    monkeypatch.setenv("QUANT_SHADOW_POLICY_PATH", "/private/test-only/model.json")
    # Resolve after setting configuration, so construction is covered as well.
    runner, effects = request.getfixturevalue("stopped_runner")
    runner._run_quant_policy_cycle()  # Fake adapter has no broker order/read methods.
    status = runner.get_status()
    assert status["is_running"] is False
    assert status["quant_policy"]["state"] == "stopped"
    assert status["profit_signal_shadow"]["configured"] is True
    assert status["profit_signal_shadow"]["execution_enabled"] is False
    assert shadow_probe.constructions == shadow_probe.calls == []
    assert effects["threads"] == effects["sync_workers"] == effects["saved_config"] == []


def test_status_failure_isolated_and_private_error_not_exposed(
        request, monkeypatch, shadow_probe):
    monkeypatch.setenv("QUANT_SHADOW_POLICY_PATH", "/private/test-only/model.json")
    runner, _ = request.getfixturevalue("stopped_runner")
    observer = sys.modules["app.broker.profit_shadow_observer"].ProfitShadowObserver
    runner._profit_shadow_observer = observer("/private/test-only/model.json")
    shadow_probe.mode = "status_error"
    status = runner.get_status()
    assert status["is_running"] is False
    assert status["quant_policy"]["state"] == "stopped"
    assert status["profit_signal_shadow"]["execution_enabled"] is False
    assert status["profit_signal_shadow"]["state"] == "unavailable"
    assert status["profit_signal_shadow"]["error_type"] == "RuntimeError"
    assert "/private/" not in str(status)


def test_original_stale_signal_early_return_does_not_observe(
        runner_type, monkeypatch, shadow_probe):
    monkeypatch.setenv("QUANT_SHADOW_POLICY_PATH", "/private/test-only/model.json")
    runner, orders, _, _ = active_runner(runner_type, shadow_probe)
    clocks = iter(["2026-09-14T10:10:00-04:00", "2026-09-14T10:15:01-04:00"])
    runner.adapter.get_clock = lambda: {
        "success": True, "is_open": True, "timestamp": next(clocks),
        "next_close": "2026-09-14T16:00:00-04:00",
    }
    runner._run_quant_policy_cycle()
    assert orders == []
    assert runner._quant_status["state"] == "stale_decision_recheck"
    assert shadow_probe.constructions == shadow_probe.calls == []


def test_observer_recovers_after_transient_construction_failure(
        runner_type, monkeypatch, shadow_probe):
    monkeypatch.setenv("QUANT_SHADOW_POLICY_PATH", "/private/test-only/model.json")
    runner, _, _, _ = active_runner(runner_type, shadow_probe)
    shadow_probe.mode = "constructor_error"
    runner._run_quant_policy_cycle()
    assert runner._profit_signal_shadow_status()["state"] == "unavailable"
    shadow_probe.mode = "success"
    # A subsequent eligible observation can recover without changing execution.
    runner._quant_last_bar = None
    runner._run_quant_policy_cycle()
    assert runner._profit_signal_shadow_status()["state"] == "ready"
    assert runner._profit_shadow_setup_error is None
