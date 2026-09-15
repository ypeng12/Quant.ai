"""Causal five-minute support/resistance *descriptors*, not trading rules.

Input timestamps are timezone-aware bar OPEN times. A row is usable only after
that five-minute bar closes. In particular, the 09:40 row's opening-range values
become available at 09:45; callers must exclude an unfinished current bar.

Levels are derived from the preceding XNYS session, the first 15 minutes, and
strict pivots with two bars on each side. A pivot at 10:00 is confirmed only on
the 10:10 row (available 10:15). Crossing/rejection always uses levels known on
the PREVIOUS row, never a pivot newly confirmed by the current row. No ticker,
date, trade-size, directional veto, or transaction-frequency rules are included.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import exchange_calendars as xcals

VERSION = "support_resistance_v1"
FEATURE_DESCRIPTIONS = {
    "sr_previous_high_distance_bps": "Close / preceding full session high minus one, in bps.",
    "sr_previous_low_distance_bps": "Close / preceding full session low minus one, in bps.",
    "sr_previous_close_distance_bps": "Close / preceding session final bar close minus one, in bps.",
    "sr_opening_high_distance_bps": "Close distance to first 15-minute high; available after 09:45 ET.",
    "sr_opening_low_distance_bps": "Close distance to first 15-minute low; available after 09:45 ET.",
    "sr_pivot_high_distance_bps": "Close distance to last confirmed intraday 2-left/2-right strict high pivot.",
    "sr_pivot_low_distance_bps": "Close distance to last confirmed intraday 2-left/2-right strict low pivot.",
    "sr_vwap_distance_bps": "Close distance to cumulative typical-price volume-weighted OHLCV proxy, not tick VWAP.",
    "sr_running_range_position": "Close within observed session low/high; missing if range is zero or incomplete.",
    "sr_resistance_cross_up": "Close crosses nearest previously known resistance above/equal previous close (0/1).",
    "sr_support_cross_down": "Close crosses nearest previously known support below/equal previous close (0/1).",
    "sr_resistance_rejection_bps": "High overshoot of prior resistance if close returned below it; otherwise zero.",
    "sr_support_rebound_bps": "Low undershoot of prior support if close returned above it; otherwise zero.",
    "sr_last_upbreak_close_distance_bps": "Close distance to the latest resistance crossed by a close this session.",
    "sr_last_upbreak_low_distance_bps": "Current low distance to that retained resistance; describes potential retest.",
    "sr_last_downbreak_close_distance_bps": "Close distance to latest support crossed downward by a close this session.",
    "sr_last_downbreak_high_distance_bps": "Current high distance to that retained support; describes potential retest.",
    "sr_upbreak_age_bars": "Elapsed five-minute grid slots since latest confirmed upward close crossing.",
    "sr_downbreak_age_bars": "Elapsed five-minute grid slots since latest confirmed downward close crossing.",
}
FEATURE_COLUMNS = tuple(FEATURE_DESCRIPTIONS)


def _distance(value: float, level: float) -> float:
    if not np.isfinite(value) or not np.isfinite(level) or level <= 0:
        return np.nan
    return (value / level - 1.0) * 10_000.0


def support_resistance_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Return 19 same-index numeric features without imputation or future data.

    The preceding *calendar trading session* must be present, rather than merely
    the preceding observed date. Prior high/low need every scheduled five-minute
    high/low (including early closes); a missing final close stays missing.
    Opening range requires all three opening bars. Missing slots are explicit in
    pivot windows, running extrema and VWAP. Non-session rows remain NaN. Missing
    current OHLCV makes that output row NaN. A zero imbalance/return is never used
    to stand in for unavailable evidence. Intraday states reset each session.
    """
    required = ["open", "high", "low", "close", "volume"]
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Timezone-aware bar-open DatetimeIndex required")
    if not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        raise ValueError("Bar-open timestamps must be sorted and unique")
    if not set(required).issubset(frame.columns):
        raise ValueError("open/high/low/close/volume columns required")
    result = pd.DataFrame(np.nan, index=frame.index, columns=FEATURE_COLUMNS)
    result.attrs.update(feature_version=VERSION, feature_descriptions=FEATURE_DESCRIPTIONS.copy(),
                        timestamp_convention="bar_open_available_at_end", frequency="5min",
                        vwap_kind="OHLCV typical-price proxy; not true trade VWAP")
    if frame.empty:
        return result
    bars = frame[required].apply(pd.to_numeric, errors="coerce").copy()
    bars.index = bars.index.tz_convert("America/New_York")
    for column in required[:4]:
        bars[column] = bars[column].where(bars[column] > 0)
    bars["volume"] = bars.volume.where(bars.volume >= 0)
    bars = bars.replace([np.inf, -np.inf], np.nan)
    calendar = xcals.get_calendar("XNYS", start=bars.index[0].date()-pd.Timedelta(days=15),
                                  end=bars.index[-1].date()+pd.Timedelta(days=1))
    output = result.copy()
    output.index = bars.index
    step = pd.Timedelta(minutes=5)

    for day, observed in bars.groupby(bars.index.date):
        session = pd.Timestamp(day)
        if not calendar.is_session(session):
            continue
        start = calendar.session_open(session).tz_convert("America/New_York")
        end = calendar.session_close(session).tz_convert("America/New_York")
        regular = observed.loc[(observed.index >= start) & (observed.index < end)]
        if regular.empty:
            continue
        if any((regular.index.asi8 - start.value) % step.value):
            raise ValueError("Regular-session rows must align with the five-minute grid")
        grid = pd.date_range(start, regular.index[-1], freq=step)
        b = regular.reindex(grid)
        previous = calendar.previous_session(session)
        prior_grid = pd.date_range(calendar.session_open(previous), calendar.session_close(previous)-step, freq=step)
        prior = bars.reindex(prior_grid)
        previous_high = prior.high.max() if prior.high.notna().all() else np.nan
        previous_low = prior.low.min() if prior.low.notna().all() else np.nan
        previous_close = prior.close.iloc[-1]
        opening_high = opening_low = pivot_high = pivot_low = np.nan
        broken_up = broken_down = np.nan
        up_at = down_at = None
        previous_close_in_day = np.nan
        running_high = running_low = np.nan
        cumulative_pv = cumulative_volume = 0.0
        range_valid = vwap_valid = True
        values = b.to_numpy(dtype=float)
        rows = []

        for i, (o, h, l, c, v) in enumerate(values):
            row = dict.fromkeys(FEATURE_COLUMNS, np.nan)
            current_valid = bool(np.isfinite([o, h, l, c, v]).all())
            # Candidates are snapshotted before current opening-range/pivot updates.
            if current_valid and np.isfinite(previous_close_in_day):
                resistances = [x for x in (previous_high, opening_high, pivot_high)
                               if np.isfinite(x) and x >= previous_close_in_day]
                supports = [x for x in (previous_low, opening_low, pivot_low)
                            if np.isfinite(x) and x <= previous_close_in_day]
                if resistances:
                    resistance = min(resistances)
                    crossed = c > resistance
                    row["sr_resistance_cross_up"] = float(crossed)
                    row["sr_resistance_rejection_bps"] = max(_distance(h, resistance), 0.0) if c < resistance else 0.0
                    if crossed:
                        broken_up, up_at = resistance, i
                if supports:
                    support = max(supports)
                    crossed = c < support
                    row["sr_support_cross_down"] = float(crossed)
                    row["sr_support_rebound_bps"] = max(-_distance(l, support), 0.0) if c > support else 0.0
                    if crossed:
                        broken_down, down_at = support, i

            if i == 2 and np.isfinite(values[:3, 1:3]).all():
                opening_high = float(values[:3, 1].max())
                opening_low = float(values[:3, 2].min())
            if i >= 4:
                highs, lows = values[i-4:i+1, 1], values[i-4:i+1, 2]
                if np.isfinite(highs).all() and highs[2] > np.max(highs[[0, 1, 3, 4]]):
                    pivot_high = highs[2]
                if np.isfinite(lows).all() and lows[2] < np.min(lows[[0, 1, 3, 4]]):
                    pivot_low = lows[2]

            range_valid = range_valid and bool(np.isfinite([h, l]).all())
            if range_valid:
                running_high = h if i == 0 else max(running_high, h)
                running_low = l if i == 0 else min(running_low, l)
            vwap_valid = vwap_valid and bool(np.isfinite([h, l, c, v]).all())
            if vwap_valid:
                cumulative_pv += (h+l+c) / 3 * v
                cumulative_volume += v
            vwap = cumulative_pv/cumulative_volume if vwap_valid and cumulative_volume > 0 else np.nan
            for name, level in (("previous_high", previous_high), ("previous_low", previous_low),
                                ("previous_close", previous_close), ("opening_high", opening_high),
                                ("opening_low", opening_low), ("pivot_high", pivot_high),
                                ("pivot_low", pivot_low), ("vwap", vwap)):
                row[f"sr_{name}_distance_bps"] = _distance(c, level)
            if range_valid and running_high > running_low:
                row["sr_running_range_position"] = (c-running_low)/(running_high-running_low)
            row.update(sr_last_upbreak_close_distance_bps=_distance(c, broken_up),
                       sr_last_upbreak_low_distance_bps=_distance(l, broken_up),
                       sr_last_downbreak_close_distance_bps=_distance(c, broken_down),
                       sr_last_downbreak_high_distance_bps=_distance(h, broken_down),
                       sr_upbreak_age_bars=i-up_at if up_at is not None else np.nan,
                       sr_downbreak_age_bars=i-down_at if down_at is not None else np.nan)
            rows.append(row if current_valid else dict.fromkeys(FEATURE_COLUMNS, np.nan))
            previous_close_in_day = c if current_valid else np.nan
        output.loc[regular.index] = pd.DataFrame(rows, index=grid).loc[regular.index, FEATURE_COLUMNS].to_numpy()
    output.index = frame.index
    return output
