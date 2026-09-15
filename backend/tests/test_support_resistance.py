import numpy as np
import pandas as pd
import pytest

from app.alpha.support_resistance import FEATURE_COLUMNS, support_resistance_features


def _day(day="2026-09-14", periods=78):
    index = pd.date_range(day+" 09:30", periods=periods, freq="5min", tz="America/New_York")
    rng = np.random.default_rng(17)
    c = 100 + np.cumsum(rng.normal(0, 0.4, periods))
    return pd.DataFrame(dict(open=c-.1, high=c+.5, low=c-.5, close=c, volume=1000.), index=index)


def test_prefix_equivalence_and_future_mutation():
    bars = pd.concat([_day(), _day("2026-09-15", 20)])
    full = support_resistance_features(bars)
    for n in (1, 2, 3, 5, 12, 79, 86, 98):
        pd.testing.assert_frame_equal(full.iloc[:n], support_resistance_features(bars.iloc[:n]))
    changed = bars.copy()
    changed.iloc[86:] *= 10
    pd.testing.assert_frame_equal(full.iloc[:86], support_resistance_features(changed).iloc[:86])


def test_opening_range_available_only_after_third_bar_completes():
    bars = _day(periods=8)
    f = support_resistance_features(bars)
    assert f.sr_opening_high_distance_bps.iloc[:2].isna().all()
    assert f.sr_opening_high_distance_bps.iloc[2] == pytest.approx((bars.close.iloc[2]/bars.high.iloc[:3].max()-1)*1e4)
    assert bars.index[2]+pd.Timedelta(minutes=5) == pd.Timestamp("2026-09-14 09:45", tz="America/New_York")
    missing = support_resistance_features(bars.drop(bars.index[1]))
    assert missing.sr_opening_high_distance_bps.isna().all()


def test_pivot_requires_two_right_bars_and_same_prior_level_for_crossing():
    bars = _day(periods=8)
    bars.loc[:, "high"] = [101, 102, 110, 104, 103, 112, 113, 114]
    bars.loc[:, "low"] = [98, 97, 90, 96, 97, 98, 99, 100]
    bars.loc[:, "close"] = [100, 101, 105, 102, 101, 111, 112, 113]
    bars.loc[:, "open"] = bars.close
    f = support_resistance_features(bars)
    assert f.sr_pivot_high_distance_bps.iloc[:4].isna().all()
    assert f.sr_pivot_low_distance_bps.iloc[:4].isna().all()
    assert f.sr_pivot_high_distance_bps.iloc[4] == pytest.approx((101/110-1)*1e4)
    assert f.sr_pivot_low_distance_bps.iloc[4] == pytest.approx((101/90-1)*1e4)
    assert f.sr_resistance_cross_up.iloc[5] == 1
    assert f.sr_last_upbreak_low_distance_bps.iloc[6] == pytest.approx((99/110-1)*1e4)
    assert f.sr_upbreak_age_bars.iloc[6] == 1


def test_newly_confirmed_level_cannot_create_same_bar_cross():
    bars = _day(periods=8)
    # Opening high 120 is not crossed; the lower pivot 108 is confirmed on bar 6.
    bars.loc[:, "high"] = [120, 102, 103, 104, 108, 106, 107, 110]
    bars.loc[:, "low"] = 90
    bars.loc[:, "open"] = bars.loc[:, "close"] = [100, 100, 100, 100, 103, 102, 106, 109]
    f = support_resistance_features(bars)
    assert f.sr_resistance_cross_up.iloc[6] == 0
    assert f.sr_resistance_cross_up.iloc[7] == 1
    assert f.sr_last_upbreak_close_distance_bps.iloc[7] == pytest.approx((109/108-1)*1e4)


def test_previous_trading_day_respects_session_and_missing_dates():
    friday, monday = _day("2026-09-11"), _day("2026-09-14", 8)
    f = support_resistance_features(pd.concat([friday, monday]))
    assert f.loc[monday.index[0], "sr_previous_high_distance_bps"] == pytest.approx((monday.close.iloc[0]/friday.high.max()-1)*1e4)
    assert f.loc[monday.index[0], "sr_pivot_high_distance_bps"] != f.loc[monday.index[0], "sr_pivot_high_distance_bps"]
    missing_friday = support_resistance_features(pd.concat([_day("2026-09-10"), monday]))
    assert missing_friday.loc[monday.index, "sr_previous_high_distance_bps"].isna().all()
    incomplete_friday = support_resistance_features(pd.concat([friday.iloc[:-1], monday]))
    assert incomplete_friday.loc[monday.index, "sr_previous_high_distance_bps"].isna().all()
    assert incomplete_friday.loc[monday.index, "sr_previous_close_distance_bps"].isna().all()


def test_missing_rows_are_not_zero_filled_and_break_cumulative_measurements():
    bars = _day(periods=12)
    bars.loc[bars.index[5], :] = np.nan
    f = support_resistance_features(bars)
    assert f.iloc[5].isna().all()
    assert f.sr_vwap_distance_bps.iloc[5:].isna().all()
    assert f.sr_running_range_position.iloc[5:].isna().all()
    assert f.sr_opening_high_distance_bps.iloc[6:].notna().all()
    assert len(f.columns) == 19 and tuple(f.columns) == FEATURE_COLUMNS


def test_early_close_previous_session_and_timezone_preservation():
    # Friday after US Thanksgiving closes at 13:00 ET (42 five-minute bars).
    prior, following = _day("2025-11-28", 42), _day("2025-12-01", 5)
    b = pd.concat([prior, following]).tz_convert("UTC")
    f = support_resistance_features(b)
    assert f.index.equals(b.index)
    assert f.iloc[42].sr_previous_high_distance_bps == pytest.approx((following.close.iloc[0]/prior.high.max()-1)*1e4)


def test_invalid_timestamp_contract_fails_explicitly():
    with pytest.raises(ValueError, match="Timezone-aware"):
        support_resistance_features(_day().tz_localize(None))
    with pytest.raises(ValueError, match="sorted and unique"):
        support_resistance_features(_day().iloc[::-1])


def test_holding_support_context_preserves_context_and_live_prefix_contract():
    from app.research.holding_policy import (
        DEFAULT_SYMBOLS, REFERENCES, HoldingSpec, holding_features,
    )

    # Three complete historical sessions provide prior-day and seasonal history;
    # the fourth is a live prefix whose later bars must never affect its features.
    history = pd.concat([_day("2026-09-10"), _day("2026-09-11"),
                         _day("2026-09-14"), _day("2026-09-15", 20)])
    frames = {symbol: history * (1 + i / 10)
              for i, symbol in enumerate((*DEFAULT_SYMBOLS, *REFERENCES))}
    support_spec = HoldingSpec(family="support_context", seasonal_sessions=2)
    context = holding_features(frames, spec=HoldingSpec(family="context", seasonal_sessions=2))
    full = holding_features(frames, spec=support_spec)
    for symbol in DEFAULT_SYMBOLS:
        assert list(full[symbol].columns) == [*context[symbol].columns, *FEATURE_COLUMNS]
        pd.testing.assert_frame_equal(full[symbol][context[symbol].columns], context[symbol])

    # At 09:40 only 09:30/09:35 bars have closed. The opening range is unavailable.
    for n in (3 * 78 + 2, 3 * 78 + 12):
        prefix = {symbol: frame.iloc[:n] for symbol, frame in frames.items()}
        live_features = holding_features(prefix, spec=support_spec)
        for symbol in DEFAULT_SYMBOLS:
            pd.testing.assert_frame_equal(live_features[symbol], full[symbol].iloc[:n])
            if n == 3 * 78 + 2:
                assert np.isnan(live_features[symbol].iloc[-1].sr_opening_high_distance_bps)

    cutoff = 3 * 78 + 12
    mutated = {symbol: frame.copy() for symbol, frame in frames.items()}
    for frame in mutated.values():
        frame.iloc[cutoff:] *= 20
    recomputed = holding_features(mutated, spec=support_spec)
    for symbol in DEFAULT_SYMBOLS:
        pd.testing.assert_frame_equal(full[symbol].iloc[:cutoff], recomputed[symbol].iloc[:cutoff])
