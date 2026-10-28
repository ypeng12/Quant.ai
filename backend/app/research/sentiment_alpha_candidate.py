"""One fixed, offline price candidate for the A/C/B research comparison.

C uses the existing twelve price/volume features and a 30-minute Ridge return
forecast. A single no-intercept scale, constrained to [0, 1], is learned from
five *later*, fully prior calibration sessions. The base estimator is NOT refit
on those calibration sessions. This is a shrinkage experiment, not a claim that
longer horizons or lower turnover necessarily improve returns.

There are no broker, service, network, or configuration imports. Text features
are deliberately outside this module: a B caller must supply a same-horizon,
point-in-time return adjustment, not a sentiment score or two-week forecast.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from ..quant_policy import (
    NY, PolicyModel, PolicySpec, horizon_fraction, labeled_frame,
    normalize_bars, target_weights,
)


VERSION = "prior_calibrated_h6_v1"
CALIBRATION_SESSIONS = 5
MIN_BASE_SESSIONS = 10
FIXED_SPEC = PolicySpec(
    name=VERSION, feature_set="price_volume", horizon_bars=6,
    ridge_alpha=10.0, risk_aversion=50.0, cost_bps=2.0,
    gross_limit=0.95, symbol_limit=0.70,
)


@dataclass(frozen=True)
class TextReturnAdjustment:
    """Audited B input: return units for the full six-bar target, not sentiment.

    `available_at` is the latest of text arrival, extraction completion and
    prediction completion. The caller owns those timestamp/model records and
    must not replace them with an article's publication timestamp.
    """

    returns: Mapping[str, float]
    available_at: str
    horizon_bars: int


def prior_scale(predicted, observed) -> float:
    """Least-squares shrinkage with no learned intercept or sign reversal.

    Zero/negative calibration association gives zero, not a fabricated reverse
    alpha. Calibration bars overlap; the fitted scale is not a significance
    estimate, win probability, or evidence of independent observations.
    """
    x, y = np.asarray(predicted, dtype=float), np.asarray(observed, dtype=float)
    if x.ndim != 1 or x.shape != y.shape or not len(x):
        raise ValueError("Aligned nonempty calibration vectors required")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Finite calibration vectors required")
    denominator = float(x @ x)
    if denominator <= np.finfo(float).tiny:
        return 0.0
    return float(np.clip(float(x @ y) / denominator, 0.0, 1.0))


def _cutoff(before) -> pd.Timestamp:
    stamp = pd.Timestamp(before)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(NY)
    else:
        stamp = stamp.tz_convert(NY)
    if stamp != stamp.normalize():
        raise ValueError("Start-of-day training cutoff required")
    return stamp


class PriceCandidate:
    """Fixed price-only C; callers retain control of replay and execution costs."""

    @classmethod
    def fit(cls, frames: Mapping[str, pd.DataFrame], before,
            traded_symbols=None) -> "PriceCandidate":
        cutoff = _cutoff(before)
        if not frames:
            raise ValueError("Historical price inputs required")
        symbols = tuple(sorted(frames))
        traded = symbols if traded_symbols is None else tuple(traded_symbols)
        if not traded or len(set(traded)) != len(traded) or not set(traded) <= set(symbols):
            raise ValueError("Unique traded symbols must be present in inputs")
        bars = {s: normalize_bars(frame) for s, frame in frames.items()}
        # Evaluate completeness on earlier days only. A future incomplete day or
        # its prices must never affect this day's fit or calibration selection.
        complete = {}
        for s, frame in bars.items():
            prior = frame.loc[frame.index < cutoff]
            complete[s] = {}
            for day, session in prior.groupby(prior.index.date, sort=True):
                expected = pd.date_range(f"{day} 09:30", periods=78, freq="5min", tz=NY)
                if pd.Timestamp(day).weekday() < 5 and session.index.equals(expected):
                    complete[s][str(day)] = session
        days = sorted(set.intersection(*(set(value) for value in complete.values())))
        if len(days) < MIN_BASE_SESSIONS + CALIBRATION_SESSIONS:
            raise ValueError("At least ten complete base sessions and five calibration sessions required")
        calibration_days = days[-CALIBRATION_SESSIONS:]
        base_days = days[:-CALIBRATION_SESSIONS]
        base_frames = {s: pd.concat([complete[s][d] for d in base_days]) for s in symbols}
        base = PolicyModel.fit(base_frames, calibration_days[0], FIXED_SPEC)
        calibration_frames = {
            s: pd.concat([complete[s][d] for d in calibration_days]) for s in symbols
        }
        predictions = base.forecast_frames(calibration_frames)
        predicted, observed, row_counts, label_ends = [], [], {}, []
        for s in traded:
            _, labels = labeled_frame(calibration_frames[s], FIXED_SPEC)
            valid = labels.notna() & predictions[s].notna()
            row_counts[s] = int(valid.sum())
            if not row_counts[s]:
                raise ValueError(f"No mature calibration labels for {s}")
            predicted.extend(predictions[s].loc[valid].to_numpy())
            observed.extend(labels.loc[valid].to_numpy())
            # Shared label: t+1 open to t+h close. Its closing time is t+h+1.
            label_ends.extend(calibration_frames[s].index[valid] +
                              pd.Timedelta(minutes=5 * (FIXED_SPEC.horizon_bars + 1)))
        if max(label_ends) >= cutoff:
            raise ValueError("Calibration label is unavailable at the training cutoff")
        model = cls()
        model.base, model.spec = base, FIXED_SPEC
        model.symbols, model.traded_symbols = symbols, traded
        model.scale = prior_scale(predicted, observed)
        model.trained_before = cutoff.date().isoformat()
        model.trained_last_session = calibration_days[-1]
        model._indices = [symbols.index(s) for s in traded]
        model.audit = {
            "version": VERSION,
            "spec": asdict(FIXED_SPEC),
            "input_symbols": list(symbols),
            "traded_symbols": list(traded),
            "trained_before": model.trained_before,
            "base_trained_before": base.trained_before,
            "base_last_training_session": base.trained_last_session,
            "base_training_sessions": base.training_sessions,
            "base_training_rows": base.training_rows,
            "calibration_days": calibration_days,
            "calibration_rows": row_counts,
            "last_calibration_label_end": max(label_ends).isoformat(),
            "scale": model.scale,
            "scale_method": "pooled_no_intercept_least_squares_clipped_zero_one",
            "calibration_target_horizon_bars": FIXED_SPEC.horizon_bars,
            "calibration_target": "next_open_to_horizon_bar_close_return",
            "base_refit_on_calibration": False,
            "overlapping_calibration_labels": True,
            "parameter_search_performed": False,
            "cost_verified": False,
            "selected_for_live": False,
        }
        return model

    def forecast_frames(self, frames: Mapping[str, pd.DataFrame]) -> dict[str, pd.Series]:
        for frame in frames.values():
            if frame.empty or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
                raise ValueError("Nonempty timezone-aware forecast bars required")
            if frame.index.tz_convert(NY).min().date().isoformat() < self.trained_before:
                raise ValueError("Prediction period overlaps training or calibration")
        forecasts = self.base.forecast_frames(frames)
        return {s: forecasts[s] * self.scale for s in self.traded_symbols}

    def covariance_at(self, stamp) -> np.ndarray:
        covariance = self.base.covariance_at(stamp)
        return covariance[np.ix_(self._indices, self._indices)]

    def weights(self, stamp, current: Mapping[str, float],
                mu: Mapping[str, float], *, shortable=None,
                text_adjustment: TextReturnAdjustment | None = None) -> dict[str, float]:
        """Allocate a calibrated, same-horizon expected-return vector.

        `mu` already includes the shared near-close horizon fraction. Optional
        text returns express the FULL six-bar target, and receive the same
        near-close scaling here. This does not translate sentiment to returns.
        """
        if set(mu) != set(self.traded_symbols):
            raise ValueError("Expected returns must match traded symbols")
        if pd.Timestamp(stamp).tzinfo is None:
            raise ValueError("Timezone-aware decision timestamp required")
        if pd.Timestamp(stamp).tz_convert(NY).date().isoformat() < self.trained_before:
            raise ValueError("Decision predates training or calibration completion")
        fraction = horizon_fraction(stamp, self.spec)
        combined = dict(mu)
        if text_adjustment is not None:
            if (type(text_adjustment.horizon_bars) is not int or
                    text_adjustment.horizon_bars != self.spec.horizon_bars):
                raise ValueError("Text return horizon must equal the six-bar price target")
            if set(text_adjustment.returns) != set(self.traded_symbols):
                raise ValueError("Text return symbols must match traded symbols")
            available = pd.Timestamp(text_adjustment.available_at)
            if (available.tzinfo is None or
                    available > pd.Timestamp(stamp) + pd.Timedelta(minutes=5)):
                raise ValueError("Text prediction must be available by the decision bar close")
            if not np.isfinite(list(text_adjustment.returns.values())).all():
                raise ValueError("Finite text expected returns required")
            combined = {s: float(mu[s]) + fraction * float(text_adjustment.returns[s])
                        for s in self.traded_symbols}
        if fraction == 0:
            return dict.fromkeys(self.traded_symbols, 0.0)
        return target_weights(combined, self.covariance_at(stamp), current, self.spec,
                              symbols=self.traded_symbols, shortable=shortable)
