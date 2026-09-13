"""Causal, inspectable OHLCV research policy shared by live and replay.

This module has no broker, network, or service imports. Its inputs are *closed*
five-minute bars with opening timestamps. Bar geometry/volume are OHLCV proxies,
not measured order flow, order-book imbalance, or calibrated win probabilities.
Capital limits, forecast horizon, regularization, risk preference, and assumed
one-way trading costs are explicit experiment inputs, not hidden signal gates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, minimize
from sklearn.covariance import LedoitWolf
from sklearn.linear_model import Ridge


NY = "America/New_York"
SCHEMA_VERSION = 1
BAR_MINUTES = 5
PRICE_FEATURES = (
    "return_1", "return_3", "return_12", "session_return", "range_fraction",
    "body_fraction", "upper_wick_fraction", "lower_wick_fraction",
    "close_location", "realized_volatility_12",
)
FEATURE_SETS = {
    "price": PRICE_FEATURES,
    "price_volume": PRICE_FEATURES + ("vwap_distance", "bar_relative_volume"),
    # A research-only panel extension.  These quantities compare one completed
    # bar with the other symbols' *same completed bar*; they are not a market
    # beta estimate or an assertion that this four-name basket is a universe.
    "price_volume_peer": PRICE_FEATURES + (
        "vwap_distance", "bar_relative_volume", "peer_return_1",
        "peer_residual_return_1", "peer_return_3", "peer_residual_return_3",
    ),
}


@dataclass(frozen=True)
class PolicySpec:
    name: str
    feature_set: str = "price_volume"
    horizon_bars: int = 3
    ridge_alpha: float = 10.0
    risk_aversion: float = 25.0
    cost_bps: float = 2.0
    gross_limit: float = 0.95
    symbol_limit: float = 0.7

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Policy name must be nonempty")
        if self.feature_set not in FEATURE_SETS:
            raise ValueError(f"Unknown feature set: {self.feature_set}")
        if isinstance(self.horizon_bars, bool) or self.horizon_bars not in (1, 3, 6):
            raise ValueError("Supported researched forecast horizons are 1, 3, 6 five-minute bars")
        for key in ("ridge_alpha", "risk_aversion", "cost_bps", "gross_limit", "symbol_limit"):
            value = getattr(self, key)
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be finite and nonnegative")
        if self.ridge_alpha == 0:
            raise ValueError("ridge_alpha must be positive")


def normalize_bars(raw: pd.DataFrame) -> pd.DataFrame:
    """Validate prices and timestamp semantics; never guess a missing timezone."""
    if not isinstance(raw.index, pd.DatetimeIndex) or raw.index.tz is None:
        raise ValueError("Bars require a timezone-aware DatetimeIndex of opening timestamps")
    aliases = {str(column).lower(): column for column in raw.columns}
    names = ("open", "high", "low", "close", "volume")
    if any(name not in aliases for name in names):
        raise ValueError("Bars require open, high, low, close, volume columns")
    bars = raw[[aliases[name] for name in names]].copy()
    bars.columns = names
    bars.index = bars.index.tz_convert(NY)
    bars = bars.sort_index().between_time("09:30", "15:55").astype(float)
    if bars.index.has_duplicates:
        raise ValueError("Duplicate bar timestamps")
    if ((bars.index.minute % BAR_MINUTES != 0) | (bars.index.second != 0)
            | (bars.index.microsecond != 0) | (bars.index.nanosecond != 0)).any():
        raise ValueError("Expected five-minute opening timestamps")
    if not np.isfinite(bars.to_numpy()).all():
        raise ValueError("OHLCV must be finite")
    if ((bars[["open", "high", "low", "close"]] <= 0).any().any()
            or (bars.volume < 0).any()
            or (bars.high < bars[["open", "close", "low"]].max(axis=1)).any()
            or (bars.low > bars[["open", "close", "high"]].min(axis=1)).any()):
        raise ValueError("Invalid OHLCV prices or volume")
    return bars


def feature_frame(raw: pd.DataFrame, feature_set: str = "price_volume") -> pd.DataFrame:
    """Every row uses only that session's observed prefix, without backfilling.

    RVOL is a bar-volume proxy against preceding bars in the same session. It is
    not a fitted time-of-day seasonal volume estimate. Unavailable lookbacks
    remain NaN and use the model's training-only feature means at inference.
    """
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"Unknown feature set: {feature_set}")
    if feature_set == "price_volume_peer":
        raise ValueError("price_volume_peer requires the complete aligned symbol panel")
    bars = normalize_bars(raw)
    result = []
    for _, frame in bars.groupby(bars.index.date, sort=True):
        if frame.index[0].strftime("%H:%M") != "09:30":
            raise ValueError("Session features require the observed prefix beginning at 09:30")
        close, opening = frame.close, frame.open
        features = pd.DataFrame(index=frame.index)
        for length in (1, 3, 12):
            # Missing intervals must not silently become a shorter/different lookback.
            returns = close.pct_change(length, fill_method=None)
            gap = frame.index.to_series().diff(length).eq(pd.Timedelta(minutes=BAR_MINUTES * length))
            features[f"return_{length}"] = returns.where(gap)
        features["session_return"] = close / opening.iloc[0] - 1.0
        features["range_fraction"] = (frame.high - frame.low) / opening
        features["body_fraction"] = (close - opening) / opening
        features["upper_wick_fraction"] = (frame.high - frame[["open", "close"]].max(axis=1)) / opening
        features["lower_wick_fraction"] = (frame[["open", "close"]].min(axis=1) - frame.low) / opening
        features["close_location"] = (close - frame.low) / (frame.high - frame.low).replace(0, np.nan) - 0.5
        features["realized_volatility_12"] = features.return_1.rolling(12, min_periods=2).std(ddof=0)
        if feature_set == "price_volume":
            typical = (frame.high + frame.low + close) / 3.0
            vwap = (typical * frame.volume).cumsum() / frame.volume.cumsum().replace(0, np.nan)
            features["vwap_distance"] = close / vwap - 1.0
            prior_mean_volume = frame.volume.expanding().mean().shift(1).replace(0, np.nan)
            features["bar_relative_volume"] = frame.volume / prior_mean_volume - 1.0
        result.append(features.loc[:, list(FEATURE_SETS[feature_set])])
    if not result:
        return pd.DataFrame(index=bars.index, columns=FEATURE_SETS[feature_set], dtype=float)
    return pd.concat(result).replace([np.inf, -np.inf], np.nan)


def panel_feature_frames(raw_by_symbol: Mapping[str, pd.DataFrame], feature_set: str = "price_volume") -> dict[str, pd.DataFrame]:
    """Build one causal feature frame per symbol, including peer returns when requested.

    The peer extension uses a leave-one-out average of returns observed at the
    same bar close.  It never uses a future bar, and it refuses partial peer
    panels rather than estimating a missing symbol from the target stock.
    """
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"Unknown feature set: {feature_set}")
    if not raw_by_symbol:
        raise ValueError("At least one symbol is required")
    if feature_set != "price_volume_peer":
        return {symbol: feature_frame(raw, feature_set) for symbol, raw in raw_by_symbol.items()}
    if len(raw_by_symbol) < 2:
        raise ValueError("price_volume_peer requires at least two symbols")

    symbols = tuple(sorted(raw_by_symbol))
    bars_by_symbol = {symbol: normalize_bars(raw_by_symbol[symbol]) for symbol in symbols}
    base = {symbol: feature_frame(bars_by_symbol[symbol], "price_volume") for symbol in symbols}
    closes = pd.concat({symbol: bars_by_symbol[symbol].close for symbol in symbols}, axis=1)
    dates = closes.index.date
    returns_1 = closes.groupby(dates).pct_change(fill_method=None)
    returns_3 = closes.groupby(dates).pct_change(3, fill_method=None)
    frames = {}
    for symbol in symbols:
        peers_1 = returns_1.drop(columns=symbol)
        peers_3 = returns_3.drop(columns=symbol)
        complete_1 = peers_1.notna().all(axis=1)
        complete_3 = peers_3.notna().all(axis=1)
        frame = base[symbol].copy()
        frame["peer_return_1"] = peers_1.mean(axis=1).where(complete_1)
        frame["peer_residual_return_1"] = (returns_1[symbol] - frame["peer_return_1"]).where(complete_1)
        frame["peer_return_3"] = peers_3.mean(axis=1).where(complete_3)
        frame["peer_residual_return_3"] = (returns_3[symbol] - frame["peer_return_3"]).where(complete_3)
        frames[symbol] = frame.loc[:, FEATURE_SETS[feature_set]].replace([np.inf, -np.inf], np.nan)
    return frames


def labeled_frame(raw: pd.DataFrame, spec: PolicySpec, *, features: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.Series]:
    """Next-open to horizon-bar close gross labels, fully observed and intraday.

    A feature at 10:00 enters at 10:05. h=3 exits at the close of 10:15,
    i.e. 10:20. Targets with missing intermediate bars or whose endpoint is
    after the operational 15:55 flatten time are excluded. No overnight labels.
    """
    bars = normalize_bars(raw)
    if features is None:
        features = feature_frame(bars, spec.feature_set)
    elif not features.index.equals(bars.index) or tuple(features.columns) != FEATURE_SETS[spec.feature_set]:
        raise ValueError("Supplied feature frame must exactly match the validated bar index and schema")
    labels = pd.Series(np.nan, index=bars.index, name="forward_gross_return")
    h = spec.horizon_bars
    for _, frame in bars.groupby(bars.index.date, sort=True):
        target = frame.close.shift(-h) / frame.open.shift(-1) - 1.0
        times = frame.index.to_series()
        # Requiring all consecutive bars prevents position-count shifts across gaps.
        consecutive = times.diff().eq(pd.Timedelta(minutes=BAR_MINUTES))
        valid = pd.Series(True, index=frame.index)
        for step in range(1, h + 1):
            valid &= consecutive.shift(-step, fill_value=False)
        maturity = times.shift(-h) + pd.Timedelta(minutes=BAR_MINUTES)
        flatten = pd.Timestamp(f"{frame.index[0].date()} 15:55", tz=NY)
        labels.loc[frame.index] = target.where(valid & maturity.le(flatten))
    return features, labels


@dataclass(frozen=True)
class Forecast:
    mu: dict[str, float]
    covariance: np.ndarray
    symbols: tuple[str, ...]
    effective_horizon_bars: float


def horizon_fraction(signal_time, spec: PolicySpec) -> float:
    """Remaining executable horizon / fitted horizon before 15:55 liquidation.

    signal_time denotes the closed bar's OPEN timestamp, so entry is five
    minutes later. Linear scaling of expected return and covariance is an
    explicit stationary-return-rate approximation near the close.
    """
    timestamp = pd.Timestamp(signal_time)
    if timestamp.tzinfo is None:
        raise ValueError("Signal timestamp must be timezone-aware")
    timestamp = timestamp.tz_convert(NY)
    flatten = timestamp.normalize() + pd.Timedelta(hours=15, minutes=55)
    entry = timestamp + pd.Timedelta(minutes=BAR_MINUTES)
    remaining = max(0.0, (flatten - entry).total_seconds() / (BAR_MINUTES * 60))
    return min(spec.horizon_bars, remaining) / spec.horizon_bars


class PolicyModel:
    """Separate per-symbol Ridge fits and a shared prior-data covariance matrix."""

    @classmethod
    def fit(cls, bars_by_symbol: Mapping[str, pd.DataFrame], train_before, spec: PolicySpec):
        cutoff = pd.Timestamp(train_before).date()
        if not bars_by_symbol:
            raise ValueError("At least one training symbol is required")
        model = cls()
        model.spec = spec
        model.symbols = tuple(sorted(bars_by_symbol))
        model.trained_before = cutoff.isoformat()
        model.train_before = model.trained_before
        model.feature_names = FEATURE_SETS[spec.feature_set]
        model.estimators = {}
        prior_returns = {}
        trained_sessions = set()
        model.training_rows = {}
        model.excluded_training_sessions = {}
        complete_bars = {}
        for symbol in model.symbols:
            bars = normalize_bars(bars_by_symbol[symbol])
            bars = bars.loc[bars.index.date < cutoff]
            complete = []
            excluded = []
            for day, session in bars.groupby(bars.index.date, sort=True):
                expected = pd.date_range(f"{day} 09:30", periods=78, freq="5min", tz=NY)
                if session.index.equals(expected) and pd.Timestamp(day).weekday() < 5:
                    complete.append(session)
                else:
                    excluded.append(str(day))
            model.excluded_training_sessions[symbol] = excluded
            complete_bars[symbol] = pd.concat(complete) if complete else bars.iloc[:0]
        feature_by_symbol = panel_feature_frames(complete_bars, spec.feature_set)
        for symbol in model.symbols:
            bars = complete_bars[symbol]
            features, labels = labeled_frame(bars, spec, features=feature_by_symbol[symbol])
            valid = labels.notna()
            if valid.sum() < 2:
                raise ValueError(f"Insufficient mature prior-session labels for {symbol}")
            x = features.loc[valid].to_numpy(dtype=float)
            # An entirely unavailable feature is neutral; no future-data imputation.
            count = np.isfinite(x).sum(axis=0)
            mean = np.divide(np.nansum(x, axis=0), count, out=np.zeros(x.shape[1]), where=count > 0)
            x = np.where(np.isfinite(x), x, mean)
            scale = x.std(axis=0, ddof=0)
            scale = np.where(scale > 0, scale, 1.0)
            ridge = Ridge(alpha=spec.ridge_alpha, solver="svd").fit((x - mean) / scale, labels.loc[valid])
            model.estimators[symbol] = {
                "mean": mean.tolist(), "scale": scale.tolist(),
                "coef": ridge.coef_.tolist(), "intercept": float(ridge.intercept_),
            }
            model.training_rows[symbol] = int(valid.sum())
            trained_sessions.update(str(day) for day in bars.index[valid].date)
            # Five-minute *observed* close returns, reset across sessions, times h.
            returns = bars.close.groupby(bars.index.date).pct_change(fill_method=None)
            consecutive = bars.index.to_series().diff().eq(pd.Timedelta(minutes=BAR_MINUTES))
            prior_returns[symbol] = returns.where(consecutive)
        observed = pd.DataFrame(prior_returns).dropna()
        if len(observed) < 2:
            raise ValueError("Insufficient aligned prior-session returns for covariance")
        model.covariance = LedoitWolf().fit(observed.to_numpy()).covariance_ * spec.horizon_bars
        model.trained_last_session = max(trained_sessions)
        model.training_sessions = sorted(trained_sessions)
        return model

    def _forecast_features(self, symbol: str, features: pd.DataFrame) -> pd.Series:
        if symbol not in self.estimators:
            raise ValueError(f"No fitted model for {symbol}")
        if tuple(features.columns) != self.feature_names:
            raise ValueError("Forecast feature schema differs from fitted model")
        params = self.estimators[symbol]
        mean, scale, coef = (np.asarray(params[key]) for key in ("mean", "scale", "coef"))
        values = features.to_numpy(dtype=float)
        values = np.where(np.isfinite(values), values, mean)
        forecast = ((values - mean) / scale) @ coef + params["intercept"]
        fractions = np.asarray([horizon_fraction(timestamp, self.spec) for timestamp in features.index])
        forecast *= fractions
        return pd.Series(forecast, index=features.index, name="expected_gross_return")

    def forecast_frame(self, symbol: str, bars: pd.DataFrame) -> pd.Series:
        """Forecast a single-symbol feature set when no panel features are used."""
        if self.spec.feature_set == "price_volume_peer":
            raise ValueError("price_volume_peer forecasts require all fitted symbols")
        return self._forecast_features(symbol, feature_frame(bars, self.spec.feature_set))

    def forecast_frames(self, history_by_symbol: Mapping[str, pd.DataFrame]) -> dict[str, pd.Series]:
        """Return causal forecasts for each fitted symbol from a synchronized panel."""
        if set(history_by_symbol) != set(self.symbols):
            missing = sorted(set(self.symbols).difference(history_by_symbol))
            unexpected = sorted(set(history_by_symbol).difference(self.symbols))
            raise ValueError(f"Forecast universe differs from fitted symbols; missing={missing}, unexpected={unexpected}")
        frames = panel_feature_frames(history_by_symbol, self.spec.feature_set)
        return {symbol: self._forecast_features(symbol, frames[symbol]) for symbol in self.symbols}

    def covariance_at(self, signal_time) -> np.ndarray:
        return self.covariance * horizon_fraction(signal_time, self.spec)

    def forecast(self, history_by_symbol: Mapping[str, pd.DataFrame]) -> Forecast:
        mu = {}
        timestamps = []
        predictions_by_symbol = self.forecast_frames(history_by_symbol)
        for symbol in self.symbols:
            predictions = predictions_by_symbol[symbol]
            if predictions.empty:
                raise ValueError(f"No regular-session forecast bars for {symbol}")
            mu[symbol] = float(predictions.iloc[-1])
            timestamps.append(predictions.index[-1])
        if len(set(timestamps)) != 1:
            raise ValueError("Joint forecast requires aligned latest bar timestamps")
        fraction = horizon_fraction(timestamps[0], self.spec)
        return Forecast(mu=mu, covariance=self.covariance_at(timestamps[0]), symbols=self.symbols,
                        effective_horizon_bars=self.spec.horizon_bars * fraction)

    def target(self, history_by_symbol, current_weights, shortable=None) -> dict[str, float]:
        forecast = self.forecast(history_by_symbol)
        if forecast.effective_horizon_bars == 0:
            return dict.fromkeys(self.symbols, 0.0)
        return target_weights(forecast.mu, forecast.covariance, current_weights,
                              self.spec, shortable=shortable, symbols=self.symbols)

    def save(self, path) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION, "bar_minutes": BAR_MINUTES,
            "timestamp_convention": "timezone_aware_bar_open", "timezone": NY,
            "prediction_kind": "signed_gross_return_next_open_to_horizon_close",
            "close_horizon_assumption": "linear_return_and_covariance_scaling_to_1555",
            "feature_names": list(self.feature_names), "spec": asdict(self.spec),
            "symbols": list(self.symbols), "trained_before": self.trained_before,
            "trained_last_session": self.trained_last_session,
            "training_sessions": self.training_sessions, "training_rows": self.training_rows,
            "excluded_training_sessions": self.excluded_training_sessions,
            "estimators": self.estimators, "covariance": self.covariance.tolist(),
        }
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(destination)

    @classmethod
    def load(cls, path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if (payload.get("schema_version") != SCHEMA_VERSION or payload.get("bar_minutes") != BAR_MINUTES
                or payload.get("timestamp_convention") != "timezone_aware_bar_open"
                or payload.get("timezone") != NY
                or payload.get("close_horizon_assumption") != "linear_return_and_covariance_scaling_to_1555"
                or payload.get("prediction_kind") != "signed_gross_return_next_open_to_horizon_close"):
            raise ValueError("Incompatible policy artifact schema or timestamp semantics")
        model = cls()
        model.spec = PolicySpec(**payload["spec"])
        model.feature_names = FEATURE_SETS[model.spec.feature_set]
        if payload.get("feature_names") != list(model.feature_names):
            raise ValueError("Artifact feature schema differs from the shared policy")
        model.symbols = tuple(payload["symbols"])
        if not model.symbols or len(set(model.symbols)) != len(model.symbols):
            raise ValueError("Artifact symbols must be nonempty and unique")
        model.trained_before = date.fromisoformat(payload["trained_before"]).isoformat()
        model.train_before = model.trained_before
        model.trained_last_session = date.fromisoformat(payload["trained_last_session"]).isoformat()
        model.training_sessions = payload["training_sessions"]
        if (not model.training_sessions or max(model.training_sessions) != model.trained_last_session
                or any(date.fromisoformat(day).isoformat() >= model.trained_before for day in model.training_sessions)):
            raise ValueError("Artifact training sessions violate training cutoff")
        model.training_rows = payload["training_rows"]
        model.excluded_training_sessions = payload.get("excluded_training_sessions", {})
        model.estimators = payload["estimators"]
        if set(model.estimators) != set(model.symbols):
            raise ValueError("Artifact estimator symbols differ")
        for symbol in model.symbols:
            params = model.estimators[symbol]
            for key in ("mean", "scale", "coef"):
                array = np.asarray(params[key], dtype=float)
                if array.shape != (len(model.feature_names),) or not np.isfinite(array).all():
                    raise ValueError(f"Invalid {key} for {symbol}")
            if (np.asarray(params["scale"]) <= 0).any() or not np.isfinite(params["intercept"]):
                raise ValueError(f"Invalid scaler or intercept for {symbol}")
        model.covariance = _validated_covariance(payload["covariance"], len(model.symbols))
        return model


def _validated_covariance(covariance, n: int) -> np.ndarray:
    covariance = np.asarray(covariance, dtype=float)
    if covariance.shape != (n, n) or not np.isfinite(covariance).all():
        raise ValueError("Covariance must be a finite square matrix aligned to symbols")
    if not np.allclose(covariance, covariance.T, rtol=1e-10, atol=1e-14):
        raise ValueError("Covariance must be symmetric")
    covariance = (covariance + covariance.T) / 2
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    tolerance = np.finfo(float).eps * max(1.0, np.linalg.norm(covariance)) * n * 10
    if eigenvalues.min() < -tolerance:
        raise ValueError("Covariance must be positive semidefinite")
    return (eigenvectors * np.maximum(eigenvalues, 0)) @ eigenvectors.T


def target_weights(mu: Mapping[str, float], covariance, current_weights: Mapping[str, float],
                   spec: PolicySpec, shortable: Mapping[str, bool] | None = None,
                   symbols=None) -> dict[str, float]:
    """Maximize mu*w - gamma/2*w'Cov*w - cost*|w-current| jointly.

    Convex transaction-cost epigraph constraints preserve actual current weights.
    Costs are one-way fractions of traded portfolio notional; mu and covariance
    refer to the configured horizon. Replanning each bar is a rolling-horizon
    approximation, not a promise of holding for exactly h bars or future profit.
    """
    symbols = tuple(sorted(mu)) if symbols is None else tuple(symbols)
    if not symbols:
        return {}
    if len(set(symbols)) != len(symbols) or set(symbols) != set(mu):
        raise ValueError("Expected-return symbols must align exactly")
    if any(value != 0 for symbol, value in current_weights.items() if symbol not in symbols):
        raise ValueError("Current exposure outside the optimized universe must be budgeted separately")
    n = len(symbols)
    expected = np.asarray([mu[symbol] for symbol in symbols], dtype=float)
    current = np.asarray([current_weights.get(symbol, 0.0) for symbol in symbols], dtype=float)
    cov = _validated_covariance(covariance, n)
    if not np.isfinite(expected).all() or not np.isfinite(current).all():
        raise ValueError("Expected returns and current weights must be finite")
    if spec.gross_limit == 0 or spec.symbol_limit == 0:
        return dict.fromkeys(symbols, 0.0)
    lower_w = np.asarray([-spec.symbol_limit if shortable is None or shortable.get(symbol, False)
                          else 0.0 for symbol in symbols])
    initial = np.clip(current, lower_w, spec.symbol_limit)
    if np.abs(initial).sum() > spec.gross_limit:
        initial *= spec.gross_limit / np.abs(initial).sum()
    x0 = np.concatenate((initial, np.abs(initial - current), np.abs(initial)))
    identity, zeros = np.eye(n), np.zeros((n, n))
    # Variables [weights, absolute turnover, absolute gross weights].
    matrix = np.vstack((
        np.hstack((-identity, identity, zeros)),
        np.hstack((identity, identity, zeros)),
        np.hstack((-identity, zeros, identity)),
        np.hstack((identity, zeros, identity)),
        np.concatenate((np.zeros(2 * n), -np.ones(n)))[None, :],
    ))
    lower = np.concatenate((-current, current, np.zeros(2 * n), [-spec.gross_limit]))
    cost = spec.cost_bps / 10000.0
    objective_scale = max(np.abs(expected).max(), spec.risk_aversion * np.abs(cov).max(), cost,
                          np.finfo(float).eps)

    def objective(x):
        w = x[:n]
        return (-expected @ w + 0.5 * spec.risk_aversion * w @ cov @ w + cost * x[n:2*n].sum()) / objective_scale

    def gradient(x):
        return np.concatenate((-expected + spec.risk_aversion * cov @ x[:n],
                               np.full(n, cost), np.zeros(n))) / objective_scale

    bounds = Bounds(np.concatenate((lower_w, np.zeros(2 * n))),
                    np.concatenate((np.full(n, spec.symbol_limit), np.full(2 * n, np.inf))))
    constraints = [LinearConstraint(matrix, lower, np.full(len(lower), np.inf))]
    result = minimize(objective, x0, jac=gradient, method="SLSQP", bounds=bounds,
                      constraints=constraints, options={"maxiter": 300, "ftol": 1e-11})
    if not result.success:
        # Active turnover/gross constraints can make SLSQP's first linear system
        # singular. A second feasible start solves the SAME convex objective;
        # this is not a replacement signal or assumed fill.
        alternative = np.concatenate((np.zeros(n), np.abs(current), np.zeros(n)))
        result = minimize(objective, alternative, jac=gradient, method="SLSQP", bounds=bounds,
                          constraints=constraints, options={"maxiter": 300, "ftol": 1e-11})
    if not result.success:
        raise RuntimeError(f"Portfolio optimization failed: {result.message}")
    weights = np.clip(result.x[:n], lower_w, spec.symbol_limit)
    weights[np.abs(weights) < 1e-10] = 0.0  # Floating-point solver residue, not an entry threshold.
    gross = np.abs(weights).sum()
    if gross > spec.gross_limit:
        weights *= spec.gross_limit / gross
    return dict(zip(symbols, map(float, weights)))


def integer_targets(weights: Mapping[str, float], prices: Mapping[str, float], equity: float,
                    spec: PolicySpec | None = None) -> dict[str, int]:
    """Convert joint exposures to whole shares by rounding toward zero.

    Rounding never creates a minimum one-share purchase or reuses each symbol's
    whole-equity budget. Broker buying power/reservations and fill reconciliation
    remain execution responsibilities. Short proceeds do not increase this equity.
    """
    if not np.isfinite(equity) or equity < 0:
        raise ValueError("Equity must be finite and nonnegative")
    symbols = tuple(weights)
    values = np.asarray([weights[symbol] for symbol in symbols], dtype=float)
    market_prices = np.asarray([prices[symbol] for symbol in symbols], dtype=float)
    if not np.isfinite(values).all() or not np.isfinite(market_prices).all() or (market_prices <= 0).any():
        raise ValueError("Finite target weights and positive prices required")
    if spec is not None:
        values = np.clip(values, -spec.symbol_limit, spec.symbol_limit)
        gross = np.abs(values).sum()
        if gross > spec.gross_limit:
            values *= spec.gross_limit / gross
    raw_shares = values * equity / market_prices
    # A reconstructed holding can be 99.99999999999999 instead of 100 solely
    # from floating-point division. Advance ONE representable value, not a
    # tradable-share threshold, before rounding toward zero.
    shares = (np.sign(raw_shares) * np.floor(np.nextafter(np.abs(raw_shares), np.inf))).astype(np.int64)
    return dict(zip(symbols, map(int, shares)))
