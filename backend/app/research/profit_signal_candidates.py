"""Four fixed, offline price candidates with executable labels and finite signals.

Inputs are the existing NVDA/SNDK/TSLA/MSTR panel; only the first three trade.
There are no broker/config imports, global signal shrinkage, outcome-based
selection or live actions. Models fit only mature prior-session observations.
Cost scenarios are one-way traded-notional bps. Both allocators explicitly pay
for changes AND a hypothetical terminal exit; only the first target is executed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Mapping

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf
from sklearn.linear_model import Ridge

from ..quant_policy import NY, normalize_bars, panel_feature_frames
from .direction_policy import planned_target
from .holding_policy import curve_from_cumulative

VERSION = "profit_signal_candidates_v1"
INPUT_SYMBOLS = ("NVDA", "SNDK", "TSLA", "MSTR")
TRADED_SYMBOLS = ("NVDA", "SNDK", "TSLA")
MIN_TRAINING_SESSIONS = 10
LOOKBACK_SESSIONS = 60


@dataclass(frozen=True)
class ProfitSignalCandidate:
    name: str
    max_hold_bars: int = 6
    planning: bool = True
    long_only: bool = False
    ridge_alpha: float = 10.0
    risk_aversion: float = 50.0
    cost_bps: float = 5.0
    gross_limit: float = 0.95
    symbol_limit: float = 0.70

    def __post_init__(self):
        if not self.name or self.max_hold_bars not in (6, 12):
            raise ValueError("Named 30- or 60-minute candidate required")
        if type(self.planning) is not bool or type(self.long_only) is not bool:
            raise ValueError("Boolean policy switches required")
        values = (self.ridge_alpha, self.risk_aversion, self.cost_bps,
                  self.gross_limit, self.symbol_limit)
        if (not np.isfinite(values).all() or self.ridge_alpha <= 0
                or self.risk_aversion <= 0 or self.cost_bps < 0
                or not 0 < self.symbol_limit <= self.gross_limit <= 1):
            raise ValueError("Invalid fixed model/risk/cost settings")

    @property
    def horizons(self):
        return (1, 6) if self.max_hold_bars == 6 else (1, 6, 12)


CANDIDATES = {c.name: c for c in (
    ProfitSignalCandidate("ridge30_single", planning=False),
    ProfitSignalCandidate("ridge30_plan"),
    ProfitSignalCandidate("ridge60_plan", max_hold_bars=12),
    ProfitSignalCandidate("ridge30_plan_long_only", long_only=True),
)}


def candidate_registry():
    return dict(version=VERSION, candidates=[dict(asdict(c), horizons=list(c.horizons))
                for c in CANDIDATES.values()], input_symbols=list(INPUT_SYMBOLS),
                traded_symbols=list(TRADED_SYMBOLS), lookback_sessions=LOOKBACK_SESSIONS,
                minimum_training_sessions=MIN_TRAINING_SESSIONS,
                target="next_open_to_horizon_plus_one_open_gross_return",
                cost_units="one_way_traded_notional_bps; changes_and_terminal_exit",
                starting_equity_recommended=50_000,
                result_based_parameter_search=False, deployment="research_only")


def _aware(stamp):
    value = pd.Timestamp(stamp)
    if value.tzinfo is None:
        raise ValueError("Timezone-aware timestamp required")
    return value.tz_convert(NY)


def _panel(frames):
    if set(frames) != set(INPUT_SYMBOLS):
        raise ValueError("Exactly NVDA/SNDK/TSLA/MSTR inputs required")
    bars = {s: normalize_bars(frames[s]) for s in INPUT_SYMBOLS}
    index = bars[INPUT_SYMBOLS[0]].index
    if not len(index) or any(not b.index.equals(index) for b in bars.values()):
        raise ValueError("Nonempty synchronized input panel required")
    for day, group in bars[INPUT_SYMBOLS[0]].groupby(index.date):
        expected = pd.date_range(f"{day} 09:30", periods=len(group), freq="5min", tz=NY)
        if not group.index.equals(expected):
            raise ValueError("Consecutive session prefixes beginning at 09:30 required")
    return bars


def profit_signal_features(frames):
    """Twelve original features, four peer features and five causal state terms.

    The four-stock peer is a basket proxy, not SPY or an industry index. Session
    extrema/path use only the observed prefix. No end-of-day regime is supplied.
    """
    bars = _panel(frames)
    panel = panel_feature_frames(bars, "price_volume_peer")
    result = {}
    for symbol in TRADED_SYMBOLS:
        b, f = bars[symbol], panel[symbol].copy()
        day = b.index.date
        first = b.open.groupby(day).transform("first")
        change = b.close.groupby(day).diff().fillna(b.close - b.open)
        distance = change.abs().groupby(day).cumsum().replace(0, np.nan)
        efficiency = ((b.close - first) / distance).clip(-1, 1)
        high, low = b.high.groupby(day).cummax(), b.low.groupby(day).cummin()
        f["path_efficiency"] = efficiency
        f["running_range_location"] = (b.close - low) / (high - low).replace(0, np.nan) - .5
        f["trend_x_efficiency"] = f.return_3 * efficiency.abs()
        f["vwap_x_range_state"] = f.vwap_distance * (1 - efficiency.abs())
        f["peer_residual_x_volume"] = f.peer_residual_return_1 * f.bar_relative_volume
        result[symbol] = f.replace([np.inf, -np.inf], np.nan)
    return result


def executable_open_labels(frame, horizon):
    """Bar-t decision enters at t+1 open and exits at t+h+1 open, by 15:55."""
    if type(horizon) is not int or horizon < 1 or horizon > 12:
        raise ValueError("Horizon must be 1 to 12 bars")
    b = normalize_bars(frame)
    y = pd.Series(np.nan, index=b.index, name="forward_gross_return")
    end = pd.Series(pd.NaT, index=b.index, dtype=b.index.dtype, name="label_end")
    for day, g in b.groupby(b.index.date):
        times = pd.Series(g.index, index=g.index)
        ends = times.shift(-(horizon + 1))
        valid = (ends - times).eq(pd.Timedelta(minutes=5 * (horizon + 1)))
        valid &= ends.le(pd.Timestamp(f"{day} 15:55", tz=NY))
        y.loc[g.index] = (g.open.shift(-(horizon + 1)) / g.open.shift(-1) - 1).where(valid)
        end.loc[g.index] = ends.where(valid)
    return y, end


@dataclass
class SignalHoldingState:
    """Per-policy/cost/session state synchronized from observed holdings.

    Creating an intent does not start a clock. A newly observed signed holding
    starts at that bar's open (the replay's fill convention). Same-sign resizing
    never renews it. A reversal starts a new signal; a flat observation clears it.
    Real broker use would require actual fill timestamps; this is replay-only.
    """
    entries: dict = field(default_factory=dict)
    signs: dict = field(default_factory=dict)
    last_stamp: pd.Timestamp | None = None
    candidate_name: str | None = None

    def observe(self, current, stamp, candidate):
        stamp = _aware(stamp)
        if self.candidate_name not in (None, candidate.name):
            raise ValueError("Holding state cannot be shared between candidates")
        if self.last_stamp is not None and stamp < self.last_stamp:
            raise ValueError("Holding observations must be chronological")
        if (self.last_stamp is not None and stamp.date() != self.last_stamp.date()
                and any(abs(float(v)) > 1e-12 for v in current.values())):
            raise ValueError("A new session must start flat")
        self.candidate_name, self.last_stamp = candidate.name, stamp
        for symbol in TRADED_SYMBOLS:
            weight = float(current.get(symbol, 0.0))
            sign = int(np.sign(weight)) if abs(weight) > 1e-12 else 0
            if not sign:
                self.entries.pop(symbol, None)
                self.signs.pop(symbol, None)
            elif sign != self.signs.get(symbol):
                self.entries[symbol], self.signs[symbol] = stamp, sign
        return {s: t + pd.Timedelta(minutes=5 * candidate.max_hold_bars)
                for s, t in self.entries.items()}


class ProfitSignalModel:
    """Fixed Ridge per stock/horizon; daily rolling prior training, no selection."""

    @classmethod
    def fit(cls, frames, before, candidate=CANDIDATES["ridge30_plan"]):
        # A runner's ISO session date means New York start-of-day explicitly.
        # Arbitrary naive timestamps are still rejected rather than guessed.
        cutoff = (pd.Timestamp(before, tz=NY) if isinstance(before, str)
                  and len(before) == 10 and pd.Timestamp(before).strftime("%Y-%m-%d") == before
                  else _aware(before))
        if cutoff != cutoff.normalize():
            raise ValueError("Start-of-day training cutoff required")
        if set(frames) != set(INPUT_SYMBOLS):
            raise ValueError("Exactly four declared inputs required")
        # Do not validate or inspect any future prices when selecting training.
        prior = {s: normalize_bars(f.loc[f.index < cutoff]) for s, f in frames.items()}
        complete = {}
        for s, b in prior.items():
            complete[s] = {}
            for day, g in b.groupby(b.index.date):
                expected = pd.date_range(f"{day} 09:30", periods=78, freq="5min", tz=NY)
                if g.index.equals(expected) and pd.Timestamp(day).weekday() < 5:
                    complete[s][str(day)] = g
        days = sorted(set.intersection(*(set(v) for v in complete.values())))[-LOOKBACK_SESSIONS:]
        if len(days) < MIN_TRAINING_SESSIONS:
            raise ValueError("At least ten common complete prior sessions required")
        bars = {s: pd.concat([complete[s][d] for d in days]) for s in INPUT_SYMBOLS}
        features = profit_signal_features(bars)
        model = cls()
        model.candidate, model.symbols, model.trained_before = candidate, TRADED_SYMBOLS, cutoff
        model.feature_names = tuple(features[TRADED_SYMBOLS[0]].columns)
        model.models, fits = {}, []
        for s in TRADED_SYMBOLS:
            model.models[s] = {}
            for h in candidate.horizons:
                target, end = executable_open_labels(bars[s], h)
                valid = target.notna() & end.lt(cutoff)
                x = features[s].loc[valid].to_numpy(dtype=float)
                count = np.isfinite(x).sum(axis=0)
                mean = np.divide(np.nansum(x, axis=0), count, out=np.zeros(x.shape[1]), where=count > 0)
                values = np.where(np.isfinite(x), x, mean)
                scale = values.std(axis=0)
                scale[scale == 0] = 1
                fitted = Ridge(alpha=candidate.ridge_alpha, solver="svd").fit((values - mean) / scale, target.loc[valid])
                model.models[s][h] = dict(mean=mean.tolist(), scale=scale.tolist(),
                    coefficient=fitted.coef_.tolist(), intercept=float(fitted.intercept_))
                fits.append(dict(symbol=s, horizon_bars=h, rows=int(valid.sum()),
                                 last_label_end=end.loc[valid].max().isoformat()))
        # Sequential open-to-open return blocks, in step-major/symbol-minor order.
        one = pd.DataFrame({s: executable_open_labels(bars[s], 1)[0] for s in TRADED_SYMBOLS})
        blocks = []
        for _, group in one.groupby(one.index.date):
            blocks.append(pd.concat([group.shift(-j) for j in range(candidate.max_hold_bars)], axis=1).dropna().to_numpy())
        values = np.concatenate(blocks)
        if len(values) < 2:
            raise ValueError("Insufficient prior complete return paths")
        model.covariance = LedoitWolf().fit(values).covariance_
        model.audit = dict(version=VERSION, candidate=asdict(candidate),
            horizons=list(candidate.horizons), trained_before=cutoff.isoformat(),
            training_sessions=days, training_fits=fits, features=list(model.feature_names),
            covariance_rows=len(values), target="next_open_to_horizon_plus_one_open_gross_return",
            input_symbols=list(INPUT_SYMBOLS), traded_symbols=list(TRADED_SYMBOLS),
            global_forecast_scale=None, deployment="research_only", outcome_selection=False)
        return model

    def forecast_frames(self, frames):
        bars = _panel(frames)
        if min(bars[INPUT_SYMBOLS[0]].index) < self.trained_before:
            raise ValueError("Prediction period overlaps training")
        features = profit_signal_features(bars)
        forecasts = {}
        for s in TRADED_SYMBOLS:
            f = features[s]
            if tuple(f.columns) != self.feature_names:
                raise ValueError("Feature contract changed")
            raw = f.to_numpy(dtype=float)
            result = {}
            for h, a in self.models[s].items():
                x = np.where(np.isfinite(raw), raw, a["mean"])
                result[h] = ((x - a["mean"]) / a["scale"]) @ np.asarray(a["coefficient"]) + a["intercept"]
            forecasts[s] = pd.DataFrame(result, index=f.index)
        return forecasts

    def allocate(self, stamp, current: Mapping[str, float], forecasts, *,
                 state: SignalHoldingState, cost_bps=5.0):
        """Use a completed bar; return a target for its next open plus diagnostics.

        An existing signal expires at entry+h. The shared hypothetical plan is
        truncated at the earliest active expiry; only the expiring stock is
        forced flat. Others retain their own clocks and may continue holding.
        This avoids assigning value to holding an old signal past its deadline.
        """
        stamp = _aware(stamp)
        if stamp < self.trained_before:
            raise ValueError("Decision predates fitted model")
        if stamp.minute % 5 or stamp.second or stamp.microsecond or stamp.nanosecond:
            raise ValueError("Five-minute bar-open timestamp required")
        if not np.isfinite(list(current.values())).all() or any(v != 0 for s, v in current.items() if s not in TRADED_SYMBOLS):
            raise ValueError("Finite holdings in the declared traded universe required")
        if set(forecasts) != set(TRADED_SYMBOLS) or any(set(forecasts[s]) != set(self.candidate.horizons) for s in TRADED_SYMBOLS):
            raise ValueError("Forecast symbols/horizons must match the model")
        cumulative = np.array([[forecasts[s][h] for s in TRADED_SYMBOLS] for h in self.candidate.horizons], dtype=float)
        if not np.isfinite(cumulative).all():
            raise ValueError("Finite return forecasts required")
        spec = replace(self.candidate, cost_bps=cost_bps)
        deadlines = state.observe(current, stamp, spec)
        entry = stamp + pd.Timedelta(minutes=5)
        close = stamp.normalize() + pd.Timedelta(hours=15, minutes=55)
        expiring = {s for s, deadline in deadlines.items() if entry >= deadline}
        info = dict(candidate=spec.name, decision_at=entry.isoformat(),
            signal_expires_at={s: t.isoformat() for s, t in deadlines.items()},
            expired_symbols=sorted(expiring), one_way_cost_bps=cost_bps,
            round_trip_cost_bps=2 * cost_bps, long_only=spec.long_only,
            expiry_clock="first_observed_fill_bar_open; same_sign_resizes_do_not_renew",
            expiry_requires_observed_flat_before_new_entry=True,
            raw_forecasts_bps={s: {str(h): float(forecasts[s][h]) * 10000 for h in spec.horizons} for s in TRADED_SYMBOLS})
        steps = min(spec.max_hold_bars, int((close - entry) / pd.Timedelta(minutes=5)))
        if steps <= 0:
            return dict.fromkeys(TRADED_SYMBOLS, 0.0), dict(info, reason="scheduled_session_close", effective_horizon_bars=0)
        for s, deadline in deadlines.items():
            if s not in expiring:
                steps = min(steps, int((deadline - entry) / pd.Timedelta(minutes=5)))
        curve = curve_from_cumulative(cumulative, spec.horizons, steps)
        n = len(TRADED_SYMBOLS)
        covariance = self.covariance[:steps * n, :steps * n]
        if not spec.planning:
            # Same horizon, costs and covariance; one constant target followed
            # by exit, versus the paired planner's intermediate future targets.
            curve = (np.prod(1 + curve, axis=0) - 1)[None, :]
            aggregate = np.tile(np.eye(n), (1, steps))
            covariance = aggregate @ covariance @ aggregate.T
        eligible = {s: s not in expiring for s in TRADED_SYMBOLS}
        weights, plan = planned_target(curve, covariance, current, TRADED_SYMBOLS,
            eligible, spec, shortable=dict.fromkeys(TRADED_SYMBOLS, not spec.long_only))
        info.update(plan, effective_horizon_bars=steps, planning=spec.planning,
                    reason="optimized_costed_target")
        return weights, info
