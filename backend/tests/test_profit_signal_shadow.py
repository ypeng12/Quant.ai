"""Numerical engineering fixtures, never evidence of historical profitability.

The model is fitted with the actual Ridge feature/scaler/covariance pipeline;
the comparison uses the actual costed optimizer and next-open share ledger.
"""
import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.quant_policy import integer_targets
from app.research.policy_replay import ExecutionConfig, ShareLedger, replay_day
from app.research.profit_signal_candidates import SignalHoldingState, TRADED_SYMBOLS
from app.research.profit_signal_shadow import ProfitSignalShadowModel
from test_profit_signal_candidates import bars, fitted  # Shared deterministic fitted fixtures.


def today(bars):
    return {s: f.loc[f.index.date == pd.Timestamp("2026-08-17").date()].copy() for s, f in bars.items()}


def request(**overrides):
    values = dict(allowed=set(TRADED_SYMBOLS), shortable=dict.fromkeys(TRADED_SYMBOLS, True),
                  as_of=pd.Timestamp("2026-08-17 10:05", tz="America/New_York"))
    values.update(overrides)
    return values


def flat():
    return dict.fromkeys(TRADED_SYMBOLS, 0.)


def test_full_session_matches_original_replay_weights_shares_fills_and_costs(bars, fitted):
    day = today(bars)
    forecasts = fitted.forecast_frames(day)
    state = SignalHoldingState()
    shadow = ProfitSignalShadowModel(fitted)
    index = day["NVDA"].index
    baseline_targets, shadow_targets = [], []

    def original(i, current):
        packet = fitted.forecast_snapshot(forecasts, index[i])
        weights, _ = fitted.allocate(index[i], current, packet, state=state)
        baseline_targets.append(weights)
        return weights

    def adapted(i, current):
        # All future rows are intentionally present: adapter must discard them.
        weights, info = shadow.live_target(day, current, **request(as_of=index[i] + pd.Timedelta(minutes=5)))
        shadow_targets.append(weights)
        assert info["execution_enabled"] is False
        assert info["permissions_reoptimized"] is False
        assert info["active_features"] == 21
        return weights

    config = ExecutionConfig(starting_equity=50_000, slippage_bps=5)
    ledgers = [ShareLedger(list(TRADED_SYMBOLS), config) for _ in range(2)]
    ledger_bars = {s: day[s].rename(columns=str.title) for s in TRADED_SYMBOLS}
    size = lambda weights, prices, equity: integer_targets(weights, prices, equity, spec=fitted.candidate)
    results = [replay_day(ledger, ledger_bars, "2026-08-17", function, size)
               for ledger, function in zip(ledgers, (original, adapted))]
    assert len(baseline_targets) == len(shadow_targets) == 76
    np.testing.assert_allclose([list(w.values()) for w in baseline_targets],
                               [list(w.values()) for w in shadow_targets], atol=1e-10)
    assert ledgers[0].fills == ledgers[1].fills
    assert ledgers[0].marks == ledgers[1].marks
    assert results[0] == results[1]
    assert results[0]["fill_count"] > 0  # Avoid a vacuous all-flat comparison.
    assert results[0]["costs"] > 0


def test_future_prices_are_discarded_before_validation_or_feature_calculation(bars, fitted):
    day = today(bars)
    poison = {s: f.copy() for s, f in day.items()}
    as_of = request()["as_of"]
    for f in poison.values():
        f.loc[f.index + pd.Timedelta(minutes=5) > as_of, :] = np.nan
    expected = ProfitSignalShadowModel(fitted).shadow_targets(day, flat(), 50_000, **request())
    actual = ProfitSignalShadowModel(fitted).shadow_targets(poison, flat(), 50_000, **request())
    assert actual == expected


def test_json_round_trip_preserves_forecasts_targets_and_rejects_overwrite(tmp_path, bars, fitted):
    path = tmp_path / "model.json"
    ProfitSignalShadowModel(fitted).save(path)
    restored = ProfitSignalShadowModel.load(path)
    assert restored.trained_before == "2026-08-17"
    assert restored.spec == fitted.candidate
    np.testing.assert_array_equal(restored.model.covariance, fitted.covariance)
    assert restored.model.models == fitted.models
    expected = ProfitSignalShadowModel(fitted).shadow_targets(today(bars), flat(), 50_000, **request())
    assert restored.shadow_targets(today(bars), flat(), 50_000, **request()) == expected
    with pytest.raises(FileExistsError):
        restored.save(path)


@pytest.mark.parametrize("tamper,match", [
    (lambda a: a.update(performance_verified=True), "execution-promoted"),
    (lambda a: a["spec"].update(risk_aversion=1), "candidate settings"),
    (lambda a: a["audit"]["training_fits"][0].update(last_label_end="2026-08-17T09:35:00-04:00"), "mature"),
    (lambda a: a["models"]["NVDA"]["1"]["scale"].__setitem__(0, 0), "scaler"),
    (lambda a: a["covariance"][0].__setitem__(0, -1), "semidefinite"),
])
def test_artifact_rejects_promotion_unregistered_parameters_and_leaking_or_invalid_fit(tmp_path, fitted, tamper, match):
    path = tmp_path / "model.json"
    ProfitSignalShadowModel(fitted).save(path)
    artifact = json.loads(path.read_text())
    tamper(artifact)
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError, match=match):
        ProfitSignalShadowModel.load(path)


def test_missing_stale_naive_and_unknown_inventory_fail_without_advancing_state(bars, fitted):
    day = today(bars)
    model = ProfitSignalShadowModel(fitted)
    invalid = {s: f.copy() for s, f in day.items() if s != "MSTR"}
    with pytest.raises(ValueError, match="four reference"):
        model.live_target(invalid, flat(), **request())
    invalid = {s: f.copy() for s, f in day.items()}
    invalid["MSTR"] = invalid["MSTR"].drop(pd.Timestamp("2026-08-17 10:00", tz="America/New_York"))
    with pytest.raises(ValueError, match="Fresh synchronized"):
        model.live_target(invalid, flat(), **request())
    with pytest.raises(ValueError, match="aware"):
        model.live_target(day, flat(), **request(as_of="2026-08-17 10:05"))
    with pytest.raises(ValueError, match="session date"):
        model.live_target(day, flat(), **request(as_of="2026-08-18T10:05:00-04:00"))
    with pytest.raises(ValueError, match="Start flat"):
        model.live_target(day, dict(NVDA=.2, SNDK=0., TSLA=0.), **request())
    assert model.last_decision is None
    assert model.state.last_stamp is None
    model.live_target(day, flat(), **request())
    with pytest.raises(ValueError, match="new completed bar"):
        model.live_target(day, flat(), **request())


def test_constraints_reoptimize_and_early_close_truncates_or_flattens(bars, fitted):
    day = today(bars)
    weights, info = ProfitSignalShadowModel(fitted).live_target(day, flat(), **request(
        allowed={"NVDA"}, shortable={"NVDA": False}))
    assert weights["NVDA"] >= -1e-8
    assert abs(weights["SNDK"]) < 1e-8 and abs(weights["TSLA"]) < 1e-8
    assert info["permissions_reoptimized"] is True
    assert info["allowed_symbols"] == ["NVDA"]
    close = "2026-08-17T12:55:00-04:00"
    _, early = ProfitSignalShadowModel(fitted).live_target(day, flat(), **request(
        as_of="2026-08-17T12:50:00-04:00", liquidation_at=close))
    assert early["effective_horizon_bars"] == 1
    assert early["forecast_horizon_end"] == close
    zero, closed = ProfitSignalShadowModel(fitted).live_target(day, flat(), **request(
        as_of=close, liquidation_at=close))
    assert zero == flat()
    assert closed["reason"] == "scheduled_session_close"
    assert closed["planned_steps"] == 0
    assert closed["planned_weights"] == closed["forecast_curve_bps"] == []
    assert closed["forecast_portfolio_return"] == closed["forecast_variance"] == 0
    assert closed["estimated_plan_turnover_cost"] == closed["estimated_terminal_cost"] == 0
    inventory = dict(NVDA=.2, SNDK=0., TSLA=0.)
    state = SignalHoldingState()
    state.observe(inventory, pd.Timestamp("2026-08-17T12:45:00-04:00"), fitted.candidate)
    held = ProfitSignalShadowModel(fitted, holding_state=state)
    zero, liquidation = held.live_target(day, inventory, **request(as_of=close, liquidation_at=close))
    assert zero == flat()
    assert liquidation["planned_weights"] == []
    assert liquidation["estimated_plan_turnover_cost"] == pytest.approx(.2 * 5 / 10000)
    assert liquidation["total_risk_variance"] == 0


def test_gap_cannot_silently_reset_unknown_nonflat_holding_clock(bars, fitted):
    day = today(bars)
    model = ProfitSignalShadowModel(fitted)
    model.live_target(day, flat(), **request())
    previous = model.last_decision
    late = request(as_of="2026-08-17T10:40:00-04:00")
    with pytest.raises(ValueError, match="continuous replay holding history"):
        model.live_target(day, dict(NVDA=.2, SNDK=0., TSLA=0.), **late)
    assert model.last_decision == previous
    assert model.state.entries == {}
    # Known flat inventory can resume without inventing any entry timestamp.
    model.live_target(day, flat(), **late)
    assert model.last_decision == pd.Timestamp(late["as_of"]) - pd.Timedelta(minutes=5)


def test_invalid_permissions_and_holdings_fail_before_forecast_without_mutating_state(bars, fitted, monkeypatch):
    model, day = ProfitSignalShadowModel(fitted), today(bars)
    model.live_target(day, flat(), **request())
    previous_state, previous_decision = model.state, model.last_decision

    def unexpected_forecast(*args, **kwargs):
        pytest.fail("Invalid permissions or inventory reached forecast calculation")

    monkeypatch.setattr(model.model, "forecast_frames", unexpected_forecast)
    invalid_requests = [
        dict(allowed={"NVDA": False}), dict(allowed=None), dict(allowed="NVDA"),
        dict(allowed=["NVDA", "MSTR"]), dict(shortable=["NVDA"]), dict(shortable=None),
        dict(shortable={"NVDA": 1}), dict(shortable={"NVDA": np.bool_(True)}),
        dict(shortable={"MSTR": True}),
    ]
    for overrides in invalid_requests:
        with pytest.raises(ValueError):
            model.live_target(day, flat(), **request(as_of="2026-08-17T10:10:00-04:00", **overrides))
        assert model.state is previous_state and model.last_decision == previous_decision
    invalid_holdings = [[], None, {"NVDA": 0.}, {**flat(), "MSTR": 0.}]
    invalid_holdings += [{**flat(), "NVDA": value} for value in
                        [float("nan"), float("inf"), -float("inf"), True, np.bool_(False),
                         "0", np.array(0.), np.array([0.]), 10**500]]
    for inventory in invalid_holdings:
        with pytest.raises(ValueError):
            model.live_target(day, inventory, **request(as_of="2026-08-17T10:10:00-04:00"))
        assert model.state is previous_state and model.last_decision == previous_decision


def test_share_sizing_rejects_invalid_equity_and_overflow_and_rolls_back_failures(bars, fitted, monkeypatch):
    import app.research.profit_signal_shadow as module
    model, day = ProfitSignalShadowModel(fitted), today(bars)
    original_state = model.state
    for equity in [True, np.bool_(True), np.array(50000.), np.array([50000.]), "50000", 1j,
                   float("nan"), float("inf"), -float("inf"), 0, -10, 10**500]:
        with pytest.raises(ValueError):
            model.shadow_targets(day, flat(), equity, **request())
        assert model.state is original_state and model.last_decision is None

    original_target = model.live_target

    def nonzero_sizing_fixture(*args, **kwargs):
        _, diagnostics = original_target(*args, **kwargs)
        # Explicit numerical boundary fixture, not a performance observation.
        return dict(NVDA=.7, SNDK=0., TSLA=0.), diagnostics

    monkeypatch.setattr(model, "live_target", nonzero_sizing_fixture)
    with pytest.raises(ValueError, match="integer range"):
        model.shadow_targets(day, flat(), 1e308, **request())
    assert model.state is original_state and model.last_decision is None

    original_sizer = module.integer_targets

    def failed_sizer(*args, **kwargs):
        raise RuntimeError("Sizing failure fixture")

    monkeypatch.setattr(module, "integer_targets", failed_sizer)
    with pytest.raises(RuntimeError, match="Sizing failure fixture"):
        model.shadow_targets(day, flat(), 50_000, **request())
    assert model.state is original_state and model.last_decision is None
    monkeypatch.setattr(module, "integer_targets", original_sizer)
    valid = model.shadow_targets(day, flat(), np.float64(50_000), **request())
    assert valid["target_shares"]["NVDA"] > 0
    assert model.last_decision is not None


@pytest.mark.parametrize("candidate", ["ridge30_single", "ridge60_plan", "ridge30_plan_long_only",
                                      "ridge30_plan_refresh_price"])
def test_other_fixed_candidates_match_direct_fitted_allocator(candidate, bars):
    model = ProfitSignalShadowModel.fit(bars, "2026-08-17", candidate)
    day, now = today(bars), request()["as_of"]
    stamp = now - pd.Timedelta(minutes=5)
    forecast = model.model.forecast_snapshot(model.model.forecast_frames(day), stamp)
    expected, info = model.model.allocate(stamp, flat(), forecast, state=SignalHoldingState())
    actual, adapted = model.live_target(day, flat(), **request())
    assert actual == pytest.approx(expected, abs=1e-10)
    assert adapted["effective_horizon_bars"] == info["effective_horizon_bars"]
    assert adapted["holding_clock_mode"] == model.spec.holding_clock_mode


def test_module_has_no_execution_or_network_imports():
    import app.research.profit_signal_shadow as shadow
    tree = ast.parse(Path(shadow.__file__).read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not any(any(term in name for term in ("broker", "main_api", "config", "requests", "http", "alpaca"))
                   for name in imports)
