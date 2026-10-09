"""A deliberately small, causal OHLCV research baseline, not a live_runner replay.

Bars must have timezone-aware *opening* timestamps. A signal formed using a
completed bar enters at the next bar's open. Positions are liquidated at the
last regular-session close. Selection and ML fitting use earlier sessions only.
No network, brokerage, production configuration, or model-file writes occur.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

NY = "America/New_York"
OHLCV = ["Open", "High", "Low", "Close", "Volume"]
CANDIDATES = ("flat", "trend_3", "trend_12", "reversal_3", "ml_ridge")
BENCHMARK = "buy_hold_session"
FEATURES = (
    "return_1", "momentum_3", "momentum_12", "session_return",
    "vwap_distance", "range_fraction", "relative_volume", "session_fraction",
)


@dataclass(frozen=True)
class ReplayConfig:
    """Research assumptions, fixed before examining target-session results."""

    slippage_bps: float = 2.0
    commission_bps: float = 0.0
    min_train_sessions: int = 5
    validation_sessions: int = 3
    ridge_alpha: float = 10.0

    def __post_init__(self) -> None:
        if (not np.isfinite(self.slippage_bps) or not np.isfinite(self.commission_bps)
                or min(self.slippage_bps, self.commission_bps) < 0
                or self.slippage_bps + self.commission_bps >= 5000):
            raise ValueError("Costs must be finite, nonnegative and below 5000 bps per side")
        if self.min_train_sessions < 1 or self.validation_sessions < 1:
            raise ValueError("Training and validation session counts must be positive")
        if not np.isfinite(self.ridge_alpha) or self.ridge_alpha <= 0:
            raise ValueError("ridge_alpha must be finite and positive")


def regular_index(day: str) -> pd.DatetimeIndex:
    return pd.date_range(f"{day} 09:30", periods=78, freq="5min", tz=NY)


def prepare_sessions(
    raw: pd.DataFrame, requested_dates: Iterable[str],
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    """Accept only complete, valid 78-bar sessions; report every rejection.

    This intentionally does not guess timezone, bar timestamp convention, session
    dates, missing prices, or shortened exchange sessions. Requested holidays and
    shortened sessions are reported as unavailable/incomplete, never backfilled.
    """
    requested_dates = set(requested_dates)
    if not isinstance(raw.index, pd.DatetimeIndex) or raw.index.tz is None:
        raise ValueError("OHLCV index must be a timezone-aware DatetimeIndex")
    aliases = {str(c).lower(): c for c in raw.columns}
    if any(c.lower() not in aliases for c in OHLCV):
        raise ValueError(f"Required OHLCV columns: {OHLCV}")
    frame = raw[[aliases[c.lower()] for c in OHLCV]].copy()
    frame.columns = OHLCV
    frame.index = frame.index.tz_convert(NY)
    frame = frame.sort_index()
    day_keys = frame.index.strftime("%Y-%m-%d")
    dates = sorted(set(day_keys) | set(requested_dates))
    sessions: dict[str, pd.DataFrame] = {}
    coverage = []
    for day in dates:
        expected = regular_index(day)
        all_rows = frame.loc[day_keys == day]
        bars = all_rows.loc[
            (all_rows.index >= expected[0])
            & (all_rows.index < expected[-1] + pd.Timedelta(minutes=5))
        ]
        missing = expected.difference(bars.index)
        unexpected = bars.index.difference(expected)
        duplicates = int(bars.index.duplicated().sum())
        try:
            numeric = bars.astype(float)
            values = numeric.to_numpy()
            invalid = (
                not np.isfinite(values).all()
                or (numeric[["Open", "High", "Low", "Close"]] <= 0).any().any()
                or (numeric["Volume"] < 0).any()
                or (numeric["High"] < numeric[["Open", "Close", "Low"]].max(axis=1)).any()
                or (numeric["Low"] > numeric[["Open", "Close", "High"]].min(axis=1)).any()
            )
        except (TypeError, ValueError):
            invalid = True
        if len(bars) == 0:
            status = "missing"
        elif duplicates or len(unexpected) or invalid:
            status = "invalid"
        elif len(missing) or len(bars) != 78:
            status = "incomplete"
        elif pd.Timestamp(day).weekday() >= 5:
            status = "non_weekday"
        else:
            status = "complete"
            sessions[day] = numeric
        coverage.append({
            "date": day, "requested": day in requested_dates, "status": status,
            "regular_bars": len(bars), "expected_bars": 78,
            "missing_bars": len(missing), "duplicate_bars": duplicates,
            "unexpected_bars": len(unexpected),
            "ignored_outside_session_bars": len(all_rows) - len(bars),
            "invalid_ohlcv": bool(invalid),
            "missing_timestamps": ";".join(t.isoformat() for t in missing),
        })
    return sessions, coverage


def session_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Every feature at row i depends only on rows 0..i of that session."""
    close = bars["Close"]
    volume = bars["Volume"]
    typical = (bars["High"] + bars["Low"] + close) / 3.0
    vwap = (typical * volume).cumsum() / volume.cumsum().replace(0, np.nan)
    features = pd.DataFrame(index=bars.index)
    features["return_1"] = close.pct_change(fill_method=None)
    features["momentum_3"] = close.pct_change(3, fill_method=None)
    features["momentum_12"] = close.pct_change(12, fill_method=None)
    features["session_return"] = close / float(bars["Open"].iloc[0]) - 1.0
    features["vwap_distance"] = close / vwap - 1.0
    features["range_fraction"] = (bars["High"] - bars["Low"]) / close
    features["relative_volume"] = volume / volume.expanding().mean().replace(0, np.nan) - 1.0
    features["session_fraction"] = (np.arange(len(bars)) + 1) / 78.0
    # Early-session lookbacks and zero-volume VWAP are neutral; no backward fill.
    return features.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def training_rows(bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Targets begin at the next open and end inside the same session.

    A feature on 15:50's bar enters at 15:55 and is valued at 16:00.
    The 15:55 feature has no tradable next bar and is never a training row.
    """
    features = session_features(bars).iloc[:-1]
    opens = bars["Open"].to_numpy(dtype=float)
    exits = np.concatenate((opens[2:], [float(bars["Close"].iloc[-1])]))
    labels = pd.Series(exits / opens[1:] - 1.0, index=features.index, name="target")
    return features, labels


def fit_ridge(rows: list[tuple[pd.DataFrame, pd.Series]], config: ReplayConfig):
    if len(rows) < config.min_train_sessions:
        return None
    model = make_pipeline(StandardScaler(), Ridge(alpha=config.ridge_alpha))
    model.fit(pd.concat([r[0] for r in rows]), pd.concat([r[1] for r in rows]))
    return model


def strategy_positions(bars: pd.DataFrame, strategy: str, model=None) -> np.ndarray:
    """Return exposure for intervals starting at each bar's open.

    The session buy-and-hold benchmark is precommitted at 09:30. All signal
    strategies have zero exposure on the first bar and shift their signal by one.
    """
    if strategy == BENCHMARK:
        return np.ones(len(bars))
    if strategy == "flat":
        return np.zeros(len(bars))
    features = session_features(bars)
    if strategy == "trend_3":
        signal = np.sign(features["momentum_3"].to_numpy())
    elif strategy == "trend_12":
        signal = np.sign(features["momentum_12"].to_numpy())
    elif strategy == "reversal_3":
        signal = -np.sign(features["momentum_3"].to_numpy())
    elif strategy == "ml_ridge":
        if model is None:
            raise ValueError("ML strategy requires a model fitted on earlier sessions")
        signal = np.sign(model.predict(features))
    else:
        raise ValueError(f"Unknown strategy: {strategy}")
    return np.concatenate(([0.0], signal[:-1]))


def simulate_session(
    bars: pd.DataFrame, positions: np.ndarray, config: ReplayConfig,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Idealized, unlevered target-exposure returns with turnover-based costs.

    This is a bar-return model, not an order/share simulator. Exposure is marked
    each interval; costs apply when its target changes and at the final close.
    No spread/borrow/financing/market impact beyond supplied bps is inferred.
    """
    positions = np.asarray(positions, dtype=float)
    if positions.shape != (len(bars),) or not np.isfinite(positions).all():
        raise ValueError("One finite position is required per bar")
    if (np.abs(positions) > 1).any():
        raise ValueError("Research baseline supports exposure between -1 and 1")
    opens = bars["Open"].to_numpy(dtype=float)
    next_prices = np.concatenate((opens[1:], [float(bars["Close"].iloc[-1])]))
    returns = next_prices / opens - 1.0
    equity = gross_equity = peak = 1.0
    drawdown = total_cost = slippage_cost = commission_cost = turnover = 0.0
    previous = 0.0
    trade_count = 0
    events: list[dict[str, Any]] = []
    per_side_cost = (config.slippage_bps + config.commission_bps) / 10000.0

    def charge(position: float, time: pd.Timestamp, price: float, signal_time) -> None:
        nonlocal equity, drawdown, total_cost, slippage_cost, commission_cost
        nonlocal turnover, previous, trade_count
        if equity <= 0 or not np.isfinite(equity):
            raise ValueError("unsupported insolvent path")
        change = abs(position - previous)
        if not change:
            return
        if position != 0 and (previous == 0 or np.sign(position) != np.sign(previous)):
            trade_count += 1
        cost = equity * change * per_side_cost
        slip = equity * change * config.slippage_bps / 10000.0
        commission = equity * change * config.commission_bps / 10000.0
        events.append({
            "fill_time": time.isoformat(),
            "signal_data_cutoff": signal_time.isoformat() if signal_time is not None else None,
            "reference_price": price, "from_position": previous,
            "to_position": position, "turnover": change,
            "cost_fraction_of_day_start_equity": cost,
            "slippage_bps_per_side": config.slippage_bps,
            "commission_bps_per_side": config.commission_bps,
        })
        equity -= cost
        if equity <= 0 or not np.isfinite(equity):
            raise ValueError("unsupported insolvent path")
        total_cost += cost
        slippage_cost += slip
        commission_cost += commission
        turnover += change
        previous = position
        drawdown = min(drawdown, equity / peak - 1.0)

    for i, (position, interval_return) in enumerate(zip(positions, returns)):
        signal_time = bars.index[i - 1] + pd.Timedelta(minutes=5) if i else None
        charge(float(position), bars.index[i], float(opens[i]), signal_time)
        growth = 1.0 + position * interval_return
        # Model-domain error: continuing would create negative transaction costs.
        # This offline exception is unrelated to any live trading decision.
        if growth <= 0 or not np.isfinite(growth):
            raise ValueError("unsupported insolvent path")
        gross_equity *= growth
        equity *= growth
        if equity <= 0 or not np.isfinite(equity):
            raise ValueError("unsupported insolvent path")
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1.0)
    # Closing at the scheduled session end is known in advance, not a new signal.
    charge(0.0, bars.index[-1] + pd.Timedelta(minutes=5), float(bars["Close"].iloc[-1]), None)
    return {
        "net_return": equity - 1.0, "gross_return": gross_equity - 1.0,
        "cost_fraction_of_day_start_equity": total_cost,
        "slippage_cost_fraction": slippage_cost,
        "commission_cost_fraction": commission_cost,
        "max_drawdown": drawdown, "trade_count": trade_count,
        "fill_count": len(events), "turnover": turnover,
        "exposed_bars": int(np.count_nonzero(positions)),
    }, events


def run_ticker(
    ticker: str, raw: pd.DataFrame, requested_dates: Iterable[str],
    config: ReplayConfig | None = None,
    fixed_selections: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Replay each requested date, choosing only from earlier validation days."""
    config = config or ReplayConfig()
    dates = sorted(set(requested_dates))
    for day in dates:
        if pd.Timestamp(day).strftime("%Y-%m-%d") != day:
            raise ValueError(f"Date must be YYYY-MM-DD: {day}")
    sessions, coverage = prepare_sessions(raw, dates)
    by_day = {row["date"]: row for row in coverage}
    days = sorted(sessions)
    model_cache: dict[str, Any] = {}
    training_cache: dict[str, tuple[pd.DataFrame, pd.Series]] = {}
    performance_cache: dict[tuple[str, str], tuple] = {}

    def model_for(day: str):
        if day not in model_cache:
            prior = [d for d in days if d < day]
            for d in prior:
                if d not in training_cache:
                    training_cache[d] = training_rows(sessions[d])
            model_cache[day] = fit_ridge([training_cache[d] for d in prior], config)
        return model_cache[day]

    def evaluate(day: str, strategy: str):
        key = (day, strategy)
        if key not in performance_cache:
            model = model_for(day) if strategy == "ml_ridge" else None
            if strategy == "ml_ridge" and model is None:
                return None
            positions = strategy_positions(sessions[day], strategy, model)
            performance_cache[key] = simulate_session(sessions[day], positions, config)
        return performance_cache[key]

    daily: list[dict[str, Any]] = []
    candidate_daily: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    for day in dates:
        if day not in sessions:
            daily.append({"ticker": ticker, "date": day, "status": by_day[day]["status"],
                          "selected_candidate": None, "net_return": None})
            continue
        earlier = [d for d in days if d < day]
        validation_days = earlier[-config.validation_sessions:]
        scores: dict[str, float] = {}
        enough_validation = len(validation_days) == config.validation_sessions
        if enough_validation:
            for strategy in CANDIDATES:
                results = []
                for validation_day in validation_days:
                    result = evaluate(validation_day, strategy)
                    prior = [d for d in days if d < validation_day]
                    validation.append({
                        "ticker": ticker, "test_date": day, "validation_date": validation_day,
                        "candidate": strategy, "status": "ok" if result else "insufficient_training",
                        "net_return": result[0]["net_return"] if result else None,
                        "model_train_sessions": len(prior) if strategy == "ml_ridge" else 0,
                        "model_train_last_date": prior[-1] if prior and strategy == "ml_ridge" else None,
                    })
                    if result:
                        results.append(result[0]["net_return"])
                if len(results) == len(validation_days):
                    scores[strategy] = float(np.prod(1.0 + np.asarray(results)) - 1.0)
        # Stable, predeclared order makes exact ties choose flat. Test results are
        # not evaluated until after the choice is locked below.
        if fixed_selections is not None:
            if day not in fixed_selections:
                raise ValueError(f"No fixed selection provided for {ticker} {day}")
            selected = fixed_selections[day]
            if selected is not None and selected not in CANDIDATES:
                raise ValueError(f"Invalid fixed candidate: {selected}")
        else:
            selected = max(scores, key=scores.get) if scores else None
        common = {
            "ticker": ticker, "date": day, "selected_candidate": selected,
            "selection_data_cutoff": f"{earlier[-1]}T16:00:00{sessions[earlier[-1]].index[-1].strftime('%z')}" if earlier else None,
            "validation_start_date": validation_days[0] if enough_validation else None,
            "validation_end_date": validation_days[-1] if enough_validation else None,
            "available_prior_sessions": len(earlier),
            "selection_mode": "fixed_external_daily_choices" if fixed_selections is not None else "prior_chronological_validation",
            "selection_score": scores.get(selected) if fixed_selections is None else None,
            "bar_data_start": sessions[day].index[0].isoformat(),
            "bar_data_end": (sessions[day].index[-1] + pd.Timedelta(minutes=5)).isoformat(),
        }
        selected_result = None
        for strategy in (*CANDIDATES, BENCHMARK):
            result = evaluate(day, strategy)
            row = {**common, "candidate": strategy, "is_selected": strategy == selected,
                   "status": "ok" if result else "insufficient_training",
                   "validation_score": scores.get(strategy),
                   "model_train_sessions": len(earlier) if strategy == "ml_ridge" else 0,
                   "model_train_last_date": earlier[-1] if earlier and strategy == "ml_ridge" else None}
            if result:
                row.update(result[0])
                for event in result[1]:
                    trades.append({"ticker": ticker, "date": day, "candidate": strategy,
                                   "is_selected": strategy == selected, **event})
                if strategy == selected:
                    selected_result = result[0]
            candidate_daily.append(row)
        daily.append({**common, "status": "ok" if selected_result is not None else "insufficient_validation",
                      **(selected_result or {"net_return": None}),
                      "ml_model_train_sessions": len(earlier) if selected == "ml_ridge" else 0,
                      "ml_model_train_last_date": earlier[-1] if earlier and selected == "ml_ridge" else None})
    valid = [row for row in daily if row["status"] == "ok"]
    equity = 1.0
    peak = 1.0
    daily_drawdown = 0.0
    for row in valid:
        equity *= 1.0 + row["net_return"]
        peak = max(peak, equity)
        daily_drawdown = min(daily_drawdown, equity / peak - 1.0)
    return {
        "ticker": ticker, "config": asdict(config),
        "summary": {
            "requested_sessions": len(dates), "evaluated_sessions": len(valid),
            "complete_requested_sessions": sum(d in sessions for d in dates),
            "all_requested_sessions_evaluated": len(valid) == len(dates),
            "selected_compounded_return_on_evaluated_sessions": equity - 1.0 if valid else None,
            "selected_close_to_close_max_drawdown": daily_drawdown if valid else None,
            "selected_trade_count": sum(row["trade_count"] for row in valid),
            "positive_sessions": int(sum(row["net_return"] > 0 for row in valid)),
            "negative_sessions": int(sum(row["net_return"] < 0 for row in valid)),
            "flat_sessions": int(sum(row["net_return"] == 0 for row in valid)),
        },
        "daily": daily, "candidate_daily": candidate_daily, "validation": validation,
        "trades": trades, "coverage": [{"ticker": ticker, **r} for r in coverage],
    }
