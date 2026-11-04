"""Read-only target adapter for the fixed profit-signal research candidates.

No broker, account configuration, collection, or runner imports are permitted.
``live_target`` matches the runner's numerical interface but is shadow-only:
holding clocks are replay observations, not authenticated broker fill clocks.
No candidate is selected by profit, and no default execution policy is changed.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping
from copy import deepcopy
from dataclasses import asdict
import json
from numbers import Real
from pathlib import Path

import numpy as np
import pandas as pd

from ..quant_policy import FEATURE_SETS, NY, _validated_covariance, integer_targets, normalize_bars
from .direction_policy import planned_target
from .holding_policy import curve_from_cumulative
from .profit_signal_candidates import (
    CANDIDATES, REFRESH_CANDIDATES, INPUT_SYMBOLS, TRADED_SYMBOLS, MIN_TRAINING_SESSIONS,
    ProfitSignalModel, SignalHoldingState, profit_signal_features,
)

VERSION = "profit_signal_shadow_v1"
EXPECTED_FEATURES = tuple(FEATURE_SETS["price_volume_peer"]) + (
    "path_efficiency", "running_range_location", "trend_x_efficiency",
    "vwap_x_range_state", "peer_residual_x_volume")


def aware(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None or pd.isna(stamp):
        raise ValueError("Explicit aware shadow clock required")
    return stamp.tz_convert(NY)


def finite_scalar(value, label):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite real scalar")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite real scalar") from exc
    if not np.isfinite(result):
        raise ValueError(f"{label} must be a finite real scalar")
    return result


class ProfitSignalShadowModel:
    """Expose the same fitted forecasts and costed allocator without execution.

    Begin flat or supply an existing replay holding state. A restart with a
    non-flat position cannot silently restart an unknown holding-expiry clock.
    A fresh daily model is required, matching the historical replay contract.
    """

    input_symbols = INPUT_SYMBOLS
    symbols = TRADED_SYMBOLS
    deployment = "shadow_only"

    def __init__(self, model, *, holding_state=None):
        self.model = model
        self.spec = model.candidate
        self.trained_before = aware(model.trained_before).date().isoformat()
        self._validate_model()
        self.state = deepcopy(holding_state) if holding_state is not None else SignalHoldingState()
        self.last_decision = self.state.last_stamp

    def _validate_model(self):
        registered = {**CANDIDATES, **REFRESH_CANDIDATES}.get(self.spec.name)
        if registered is None or self.spec != registered:
            raise ValueError("Only an unchanged registered research candidate is supported")
        if self.model.feature_builder is not profit_signal_features or tuple(self.model.feature_names) != EXPECTED_FEATURES:
            raise ValueError("The registered 21-feature profit-signal model is required")
        cutoff = aware(self.model.trained_before)
        if cutoff != cutoff.normalize():
            raise ValueError("Daily training cutoff must be start of session date")
        if tuple(self.model.symbols) != TRADED_SYMBOLS or set(self.model.models) != set(TRADED_SYMBOLS):
            raise ValueError("Declared traded universe changed")
        n_features = len(EXPECTED_FEATURES)
        for models in self.model.models.values():
            if set(models) != set(self.spec.horizons):
                raise ValueError("Registered model horizons changed")
            for fitted in models.values():
                arrays = [np.asarray(fitted[k], dtype=float) for k in ["mean", "scale", "coefficient"]]
                if (any(a.shape != (n_features,) or not np.isfinite(a).all() for a in arrays)
                        or (arrays[1] <= 0).any() or not np.isfinite(fitted["intercept"])):
                    raise ValueError("Invalid finite model coefficients or training scaler")
        _validated_covariance(self.model.covariance, self.spec.max_hold_bars * len(TRADED_SYMBOLS))
        audit = self.model.audit
        if (audit.get("candidate") != asdict(self.spec)
                or audit.get("features") != list(EXPECTED_FEATURES)
                or audit.get("horizons") != list(self.spec.horizons)
                or audit.get("input_symbols") != list(INPUT_SYMBOLS)
                or audit.get("traded_symbols") != list(TRADED_SYMBOLS)
                or aware(audit["trained_before"]) != cutoff):
            raise ValueError("Training audit and model declaration disagree")
        days = audit["training_sessions"]
        if len(days) < MIN_TRAINING_SESSIONS or days != sorted(set(days)):
            raise ValueError("At least ten ordered prior training sessions required")
        if any(pd.Timestamp(day, tz=NY) >= cutoff for day in days):
            raise ValueError("Training sessions must precede prediction date")
        fits = audit["training_fits"]
        if len(fits) != len(TRADED_SYMBOLS) * len(self.spec.horizons) or {(f["symbol"], f["horizon_bars"]) for f in fits} != {
                (s, h) for s in TRADED_SYMBOLS for h in self.spec.horizons}:
            raise ValueError("Training audit does not cover all forecasts")
        if any(aware(f["last_label_end"]) >= cutoff or f["rows"] <= 0 for f in fits):
            raise ValueError("Training labels must mature before the prediction date")

    @classmethod
    def fit(cls, frames, before, candidate="ridge30_plan"):
        definitions = {**CANDIDATES, **REFRESH_CANDIDATES}
        if candidate not in definitions:
            raise ValueError("Unknown fixed candidate")
        return cls(ProfitSignalModel.fit(frames, before, definitions[candidate]))

    def _completed_prefix(self, frames, now):
        if set(frames) != set(INPUT_SYMBOLS):
            raise ValueError("All four reference inputs are required; MSTR is not traded")
        if self.trained_before != now.date().isoformat():
            raise ValueError("A model fitted for this session date is required")
        stamp = now.floor("5min") - pd.Timedelta(minutes=5)
        completed = {}
        for symbol, raw in frames.items():
            if not isinstance(raw.index, pd.DatetimeIndex) or raw.index.tz is None:
                raise ValueError("Aware bar-open timestamps required")
            index = raw.index.tz_convert(NY)
            # Filter unavailable rows before validating their prices. A future
            # poisoned bar must not affect a completed-prefix calculation.
            keep = (index.date == now.date()) & (index + pd.Timedelta(minutes=5) <= now)
            frame = normalize_bars(raw.loc[keep])
            if frame.empty or frame.index[-1] != stamp:
                raise ValueError("Fresh synchronized completed bars required")
            completed[symbol] = frame
        return completed, stamp

    def live_target(self, frames, current, *, allowed, shortable, as_of, liquidation_at=None):
        """Return weights and diagnostics only; never submit an order.

        With the registered full universe, permissions and normal close this
        directly uses ProfitSignalModel.allocate, exactly as the replay does.
        Tighter permissions/early closes re-optimize its same forecast/cost/risk
        objective; post-hoc clipping is not used to approximate a constrained fit.
        """
        now = aware(as_of)
        if isinstance(allowed, (str, bytes, Mapping)) or not isinstance(allowed, Collection):
            raise ValueError("Allowed symbols must be an explicit symbol collection")
        if any(not isinstance(s, str) or s not in TRADED_SYMBOLS for s in allowed):
            raise ValueError("Permissions contain an undeclared traded symbol")
        allowed = set(allowed)
        if not isinstance(shortable, Mapping):
            raise ValueError("Short permissions must be a mapping")
        if not set(shortable) <= set(TRADED_SYMBOLS):
            raise ValueError("Permissions contain an undeclared traded symbol")
        if any(type(v) is not bool for v in shortable.values()):
            raise ValueError("Explicit Boolean short permissions required")
        if not isinstance(current, Mapping) or set(current) != set(TRADED_SYMBOLS):
            raise ValueError("Current weights must explicitly cover exactly the three traded symbols")
        current = {s: finite_scalar(current[s], "Current weight") for s in TRADED_SYMBOLS}
        completed, stamp = self._completed_prefix(frames, now)
        if self.last_decision is not None and stamp <= self.last_decision:
            raise ValueError("Shadow requires a new completed bar, not a repeated or earlier decision")
        if (self.last_decision is not None and stamp - self.last_decision > pd.Timedelta(minutes=5)
                and any(abs(float(v)) > 1e-12 for v in current.values())):
            raise ValueError("Non-flat shadow decision gap requires continuous replay holding history")
        if self.state.last_stamp is None and any(abs(float(v)) > 1e-12 for v in current.values()):
            raise ValueError("Start flat or provide replay holding state; broker fill clocks are unknown")
        normal_close = stamp.normalize() + pd.Timedelta(hours=15, minutes=55)
        close = normal_close if liquidation_at is None else aware(liquidation_at)
        if (close.date() != now.date() or close != close.floor("5min")
                or close > normal_close or close < stamp.normalize() + pd.Timedelta(hours=9, minutes=30)):
            raise ValueError("Same-session five-minute liquidation boundary required")
        forecasts = self.model.forecast_frames(completed)
        snapshot = self.model.forecast_snapshot(forecasts, stamp)
        state = deepcopy(self.state)
        weights, diagnostics = self.model.allocate(stamp, current, snapshot, state=state, cost_bps=self.spec.cost_bps)
        remaining = max(0, int((close - snapshot.available_at) / pd.Timedelta(minutes=5)))
        steps = min(diagnostics["effective_horizon_bars"], remaining)
        short_flags = {s: shortable.get(s, False) and not self.spec.long_only for s in TRADED_SYMBOLS}
        restricted = (allowed != set(TRADED_SYMBOLS)
                      or any(not short_flags[s] for s in TRADED_SYMBOLS) and not self.spec.long_only
                      or close != normal_close)
        if steps == 0:
            weights = dict.fromkeys(TRADED_SYMBOLS, 0.0)
            # The core may have planned through its regular 15:55 close. Those
            # plans are not executable after an earlier exchange boundary.
            for key in ("solver", "planned_steps", "planned_weights", "forecast_curve_bps",
                        "estimated_plan_turnover_cost", "estimated_terminal_cost", "forecast_portfolio_return",
                        "forecast_variance", "forecast_error_risk_enabled", "forecast_error_variance", "total_risk_variance"):
                diagnostics.pop(key, None)
            diagnostics.update(reason="scheduled_session_close", effective_horizon_bars=0,
                planned_steps=0, planned_weights=[], forecast_curve_bps=[],
                estimated_plan_turnover_cost=sum(abs(float(v)) for v in current.values()) * self.spec.cost_bps / 10000,
                estimated_terminal_cost=0., forecast_portfolio_return=0., forecast_variance=0.,
                forecast_error_risk_enabled=False, forecast_error_variance=0., total_risk_variance=0.)
        elif restricted:
            cumulative = np.array([[snapshot.returns[s][h] for s in TRADED_SYMBOLS] for h in self.spec.horizons])
            curve = curve_from_cumulative(cumulative, self.spec.horizons, steps)
            n = len(TRADED_SYMBOLS)
            covariance = self.model.covariance[:steps*n, :steps*n]
            if not self.spec.planning:
                curve = (np.prod(1 + curve, axis=0) - 1)[None, :]
                aggregate = np.tile(np.eye(n), (1, steps))
                covariance = aggregate @ covariance @ aggregate.T
            eligible = {s: s in allowed and s not in diagnostics["expired_symbols"] for s in TRADED_SYMBOLS}
            weights, plan = planned_target(curve, covariance, current, TRADED_SYMBOLS, eligible,
                                           self.spec, shortable=short_flags)
            diagnostics.update(plan, effective_horizon_bars=steps, reason="optimized_costed_target")
        diagnostics.update(
            model=self.spec.name, adapter=VERSION, deployment="shadow_only", execution_enabled=False,
            feature_family="price_volume_peer_with_causal_state", active_features=len(EXPECTED_FEATURES),
            cumulative_forecast_bps={s: {str(h*5): value*10000 for h, value in values.items()}
                                     for s, values in snapshot.returns.items()},
            cost_assumption_bps=self.spec.cost_bps, cost_verified=False, l1_contributes=False,
            permissions_reoptimized=restricted, allowed_symbols=sorted(allowed), shortable=short_flags,
            liquidation_at=close.isoformat(),
            forecast_horizon_end=min(snapshot.available_at + pd.Timedelta(minutes=steps*5), close).isoformat(),
            reference_prices={s: float(completed[s].close.iloc[-1]) for s in TRADED_SYMBOLS},
            observed_at=now.isoformat(), model_trained_before=self.trained_before,
            holding_clock_evidence="replay_observed_holdings_only_not_broker_fill_history",
            limitations=["All four original profit candidates lost in the inspected historical comparison.",
                         "Target parity is engineering evidence, not a profitability or execution validation.",
                         "Model audit checks declared consistency, not independent authenticity of training inputs.",
                         "Production use requires authenticated fill timestamps, persistent clocks and daily model refresh."])
        self.state, self.last_decision = state, stamp
        return weights, diagnostics

    def shadow_targets(self, frames, current, equity, **kwargs):
        """Return whole-share intentions from the same completed-bar mark as replay."""
        equity = finite_scalar(equity, "Shadow equity")
        if equity <= 0:
            raise ValueError("Positive finite shadow equity required")
        previous_state, previous_decision = self.state, self.last_decision
        try:
            weights, diagnostics = self.live_target(frames, current, **kwargs)
            with np.errstate(over="ignore", invalid="ignore"):
                raw_shares = np.array([abs(weights[s]) * equity / diagnostics["reference_prices"][s]
                                       for s in TRADED_SYMBOLS])
            # integer_targets uses int64 and advances one ULP before rounding.
            # Reject overflow before conversion instead of returning wrapped shares.
            if (not np.isfinite(raw_shares).all()
                    or (np.nextafter(raw_shares, np.inf) >= float(np.iinfo(np.int64).max)).any()):
                raise ValueError("Shadow share quantities exceed the supported integer range")
            shares = integer_targets(weights, diagnostics["reference_prices"], equity, spec=self.spec)
        except Exception:
            self.state, self.last_decision = previous_state, previous_decision
            raise
        return {"kind": VERSION, "execution_enabled": False, "target_weights": weights,
                "target_shares": shares, "diagnostics": diagnostics}

    def save(self, path):
        """Save finite numerical model state as JSON; never pickle executable objects."""
        self._validate_model()
        payload = {"kind": VERSION, "deployment": "shadow_only", "performance_verified": False,
            "spec": asdict(self.spec), "trained_before": aware(self.model.trained_before).isoformat(),
            "symbols": list(TRADED_SYMBOLS), "input_symbols": list(INPUT_SYMBOLS),
            "feature_names": list(self.model.feature_names), "models": self.model.models,
            "covariance": self.model.covariance.tolist(), "audit": self.model.audit}
        # An artifact is a fitted model, not a claim to preserve live inventory.
        with Path(path).open("x") as handle:
            json.dump(payload, handle, allow_nan=False)
            handle.write("\n")

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Shadow model exceeds the bounded JSON size")
        a = json.loads(path.read_text())
        if (a.get("kind") != VERSION or a.get("deployment") != "shadow_only"
                or a.get("performance_verified") is not False
                or a.get("symbols") != list(TRADED_SYMBOLS) or a.get("input_symbols") != list(INPUT_SYMBOLS)):
            raise ValueError("Unsupported or execution-promoted shadow artifact")
        candidate = {**CANDIDATES, **REFRESH_CANDIDATES}.get(a["spec"]["name"])
        if candidate is None or a["spec"] != asdict(candidate):
            raise ValueError("Artifact changed registered candidate settings")
        model = ProfitSignalModel()
        model.candidate, model.symbols = candidate, TRADED_SYMBOLS
        model.trained_before = aware(a["trained_before"])
        model.feature_builder, model.feature_names = profit_signal_features, tuple(a["feature_names"])
        model.models = {s: {int(h): fitted for h, fitted in models.items()} for s, models in a["models"].items()}
        model.covariance, model.audit = np.asarray(a["covariance"], dtype=float), a["audit"]
        return cls(model)
