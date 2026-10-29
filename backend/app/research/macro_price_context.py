"""Retrospective prior-session price context for a fixed intraday experiment.

No services, credentials, network calls, model fitting or winner selection.
Captured daily bars are available to this experiment now; their earlier session
dates do NOT establish historical pipeline receipt. Daily context never reads
the decision day's close. Missing captured sessions are never forward-filled.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd

from ..quant_policy import NY, normalize_bars
from .profit_signal_candidates import INPUT_SYMBOLS, TRADED_SYMBOLS, profit_signal_features

VERSION = "macro_price_context_v1"
REFERENCE_SYMBOLS = ("SPY", "QQQ", "SOXX")
HORIZONS = (1, 5, 20)
TREND_REFERENCE = {"NVDA": "SOXX", "SNDK": "SOXX", "TSLA": "QQQ"}
MACRO_FEATURE_NAMES = (
    *(f"macro_stock_return_{h}d" for h in HORIZONS),
    "macro_overnight_gap",
    *(f"macro_{ref}_return_{h}d" for ref in REFERENCE_SYMBOLS for h in HORIZONS),
    *(f"macro_stock_minus_{ref}_5d" for ref in REFERENCE_SYMBOLS),
    "macro_trend_x_return_3", "macro_relative5_x_return_3",
    "macro_trend_x_vwap_distance", "macro_gap_x_return_3",
)


def _iso_date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("An ISO session date is required")
    return date.fromisoformat(value)


def _daily_references(raw, evaluation_end):
    captured = pd.Timestamp(raw["captured_at"])
    if captured.tzinfo is None:
        raise ValueError("Capture receipt must be timezone-aware")
    if raw.get("point_in_time_receipt_historical") is not False:
        raise ValueError("Retrospective capture must not claim historical receipt")
    payload = raw["data"]
    request = payload.get("request", {})
    if request.get("timeframe") != "1Day" or set(payload["bars"]) != set(REFERENCE_SYMBOLS):
        raise ValueError("Daily SPY/QQQ/SOXX capture required")
    series, audit = {}, {}
    for symbol in REFERENCE_SYMBOLS:
        values, excluded, seen = {}, [], set()
        records = payload["bars"][symbol]
        for row in records:
            stamp = pd.Timestamp(row["timestamp"])
            if stamp.tzinfo is None or row.get("symbol") != symbol:
                raise ValueError("Aware daily timestamps and matching symbols required")
            day = stamp.tz_convert(NY).date()
            if day in seen:
                raise ValueError("Duplicate reference session; revisions require explicit resolution")
            seen.add(day)
            if day > evaluation_end:
                excluded.append(day.isoformat())
                continue
            closing = float(row["close"])
            if not np.isfinite(closing) or closing <= 0:
                raise ValueError("Positive finite daily close required")
            values[day] = closing
        if not values:
            raise ValueError("No reference sessions inside the declared research boundary")
        series[symbol] = pd.Series(values, dtype=float).sort_index()
        prior_final = [d for d in values if d < evaluation_end]
        audit[symbol] = dict(raw_rows=len(records), retained_rows=len(values),
            first_retained_session=min(values).isoformat(), last_retained_session=max(values).isoformat(),
            excluded_after_evaluation_end=excluded,
            last_session_usable_for_final_decision=max(prior_final).isoformat() if prior_final else None)
    metadata = dict(captured_at=captured.isoformat(),
        source=raw.get("source", "unspecified captured daily source"),
        feed=request.get("feed"), historical_pipeline_receipt_verified=False,
        pipeline_received_at=captured.isoformat(),
        raw_capture_sha256=hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        adjustment=request.get("adjustment", "not_declared_in_capture_request"),
        reference_coverage=audit)
    return series, metadata


def _complete_stock_closes(frames, evaluation_end):
    if set(frames) != set(INPUT_SYMBOLS):
        raise ValueError("Exactly the existing four-stock panel is required")
    closes, audit = {}, {}
    until = pd.Timestamp(evaluation_end, tz=NY) + pd.Timedelta(days=1)
    for symbol in INPUT_SYMBOLS:
        frame = frames[symbol]
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            raise ValueError("Aware stock bar-opening timestamps required")
        bounded = frame.loc[frame.index < until]
        bars = normalize_bars(bounded)
        values, excluded = {}, []
        for day, group in bars.groupby(bars.index.date):
            expected = pd.date_range(f"{day} 09:30", periods=78, freq="5min", tz=NY)
            if group.index.equals(expected) and pd.Timestamp(day).weekday() < 5:
                values[day] = float(group.close.iloc[-1])
            else:
                excluded.append(day.isoformat())
        if not values:
            raise ValueError("Complete prior stock sessions are required")
        closes[symbol] = pd.Series(values, dtype=float).sort_index()
        audit[symbol] = dict(complete_sessions=len(values),
            first_session=min(values).isoformat(), last_session=max(values).isoformat(),
            incomplete_session_dates=excluded, excluded_rows_after_evaluation_end=len(frame)-len(bounded))
    return closes, audit


class MacroFeatureBuilder:
    """Callable saved with the model so fit and prediction use one feature path."""

    def __init__(self, all_stock_frames, raw_market_daily, *, evaluation_end="2026-10-27"):
        self.evaluation_end = _iso_date(evaluation_end)
        market, metadata = _daily_references(raw_market_daily, self.evaluation_end)
        stocks, stock_audit = _complete_stock_closes(all_stock_frames, self.evaluation_end)
        # Union prevents a missing row in one reference/stock from compressing
        # its lookback. This captured-session calendar is not an exchange master.
        self.calendar = sorted(set().union(*(set(s.index) for s in (*market.values(), *stocks.values()))))
        self.closes = {s: values.reindex(self.calendar) for s, values in {**market, **stocks}.items()}
        self.end_returns = {}
        for symbol, values in self.closes.items():
            self.end_returns[symbol] = {}
            for h in HORIZONS:
                complete = values.rolling(h + 1, min_periods=h + 1).count().eq(h + 1)
                self.end_returns[symbol][h] = (values / values.shift(h) - 1).where(complete)
        return_coverage = {}
        for symbol, horizons in self.end_returns.items():
            return_coverage[symbol] = {}
            for h, values in horizons.items():
                valid = values.dropna()
                return_coverage[symbol][str(h)] = dict(finite_session_end_values=len(valid),
                    first_session_end=valid.index[0].isoformat() if len(valid) else None,
                    last_session_end=valid.index[-1].isoformat() if len(valid) else None)
        self.audit = dict(version=VERSION, evaluation_end=evaluation_end,
            feature_names=list(MACRO_FEATURE_NAMES), additional_features=len(MACRO_FEATURE_NAMES),
            calendar_basis="union_of_captured_reference_and_complete_stock_session_dates_not_exchange_master",
            calendar_sessions=len(self.calendar), stock_coverage=stock_audit,
            daily_return_coverage=return_coverage, **metadata,
            daily_cutoff="session_date_strictly_before_each_decision_date",
            missing_data="NaN; no backfill or compressed incomplete windows",
            return_kind="close_price_returns_excluding_cash_dividends",
            deployment="retrospective_research_only",
            limitations=["Captured now; historical receipt and original price revisions are not verified.",
                         "Reference daily closes and stock intraday closes have different source contracts.",
                         "An incomplete or missing captured session leaves its dependent features unavailable."])

    def _context(self, symbol, decision_day):
        # Last captured calendar session strictly BEFORE this day's decision.
        # A missing close on that session stays NaN instead of using an older one.
        position = int(np.searchsorted(self.calendar, decision_day, side="left")) - 1
        if position < 0:
            return np.nan, {name: np.nan for name in MACRO_FEATURE_NAMES[:16]}
        prior = self.calendar[position]
        own = {h: float(self.end_returns[symbol][h].loc[prior]) for h in HORIZONS}
        refs = {s: {h: float(self.end_returns[s][h].loc[prior]) for h in HORIZONS}
                for s in REFERENCE_SYMBOLS}
        context = {f"macro_stock_return_{h}d": own[h] for h in HORIZONS}
        context.update({f"macro_{s}_return_{h}d": refs[s][h] for s in REFERENCE_SYMBOLS for h in HORIZONS})
        context.update({f"macro_stock_minus_{s}_5d": own[5] - refs[s][5] for s in REFERENCE_SYMBOLS})
        return float(self.closes[symbol].loc[prior]), context

    def __call__(self, frames):
        base = profit_signal_features(frames)
        bars = {s: normalize_bars(frames[s]) for s in TRADED_SYMBOLS}
        result = {}
        for symbol, features in base.items():
            f = features.copy()
            extra = pd.DataFrame(np.nan, index=f.index, columns=MACRO_FEATURE_NAMES)
            for day, group in bars[symbol].groupby(bars[symbol].index.date):
                if day > self.evaluation_end:
                    raise ValueError("Decision exceeds the registered macro-context research boundary")
                previous_close, context = self._context(symbol, day)
                for column, value in context.items():
                    extra.loc[group.index, column] = value
                extra.loc[group.index, "macro_overnight_gap"] = float(group.open.iloc[0]) / previous_close - 1
            ref = TREND_REFERENCE[symbol]
            extra["macro_trend_x_return_3"] = extra[f"macro_{ref}_return_20d"] * f.return_3
            extra["macro_relative5_x_return_3"] = extra[f"macro_stock_minus_{ref}_5d"] * f.return_3
            extra["macro_trend_x_vwap_distance"] = extra[f"macro_{ref}_return_20d"] * f.vwap_distance
            extra["macro_gap_x_return_3"] = extra.macro_overnight_gap * f.return_3
            result[symbol] = f.join(extra).replace([np.inf, -np.inf], np.nan)
        return result


def make_macro_feature_builder(all_stock_frames, raw_market_daily, *, evaluation_end="2026-10-27"):
    return MacroFeatureBuilder(all_stock_frames, raw_market_daily, evaluation_end=evaluation_end)
