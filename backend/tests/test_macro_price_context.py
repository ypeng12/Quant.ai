"""Synthetic calendar/availability tests; no real-history fitting or downloads."""
import copy
import json

import numpy as np
import pandas as pd
import pytest

from app.research.macro_price_context import (
    MACRO_FEATURE_NAMES, REFERENCE_SYMBOLS, make_macro_feature_builder,
)
from app.research.profit_signal_candidates import (
    CANDIDATES, INPUT_SYMBOLS, TRADED_SYMBOLS, ProfitSignalModel,
    profit_signal_features,
)


@pytest.fixture(scope="module")
def history():
    # Business dates are a synthetic test calendar, not claimed exchange data.
    days = pd.bdate_range("2026-08-03", periods=26)
    index = pd.DatetimeIndex([t for d in days for t in pd.date_range(
        f"{d.date()} 09:30", periods=78, freq="5min", tz="America/New_York")])
    frames = {}
    for j, symbol in enumerate(INPUT_SYMBOLS):
        price = 100 + j * 20 + np.repeat(np.arange(len(days)) * .4, 78) + np.tile(np.arange(78) * .01, len(days))
        frames[symbol] = pd.DataFrame(dict(open=price, close=price+.005,
            high=price+.02, low=price-.02, volume=10000+np.arange(len(index)) % 78), index=index)
    market = dict(captured_at="2026-10-28T23:56:16Z", source="synthetic fixture",
        point_in_time_receipt_historical=False, data=dict(request=dict(timeframe="1Day", feed="sip"), bars={}))
    for j, symbol in enumerate(REFERENCE_SYMBOLS):
        market["data"]["bars"][symbol] = [dict(symbol=symbol,
            timestamp=pd.Timestamp(d.date(), tz="America/New_York").isoformat(),
            close=200+j*20+i*.3) for i, d in enumerate(days)]
        market["data"]["bars"][symbol].append(dict(symbol=symbol,
            timestamp="2026-10-28T04:00:00+00:00", close=99999.))
    return frames, market, days


def _one_day(frames, day):
    return {s: f.loc[f.index.date == day] for s, f in frames.items()}


def test_daily_context_is_previous_session_and_gap_uses_today_open(history):
    frames, market, days = history
    builder = make_macro_feature_builder(frames, market)
    day = days[22].date()
    today = _one_day(frames, day)
    factors = builder(today)
    previous_closes = frames["NVDA"].close.groupby(frames["NVDA"].index.date).last()
    first = factors["NVDA"].iloc[0]
    assert first.macro_stock_return_1d == pytest.approx(previous_closes.iloc[21]/previous_closes.iloc[20]-1)
    assert first.macro_stock_return_5d == pytest.approx(previous_closes.iloc[21]/previous_closes.iloc[16]-1)
    assert first.macro_stock_return_20d == pytest.approx(previous_closes.iloc[21]/previous_closes.iloc[1]-1)
    assert first.macro_overnight_gap == pytest.approx(today["NVDA"].open.iloc[0]/previous_closes.iloc[21]-1)
    assert first.macro_SPY_return_5d == pytest.approx((200+21*.3)/(200+16*.3)-1)
    assert first.macro_stock_minus_SPY_5d == pytest.approx(first.macro_stock_return_5d-first.macro_SPY_return_5d)
    assert len(MACRO_FEATURE_NAMES) == 20
    assert len(factors["NVDA"].columns) == 41
    for s in TRADED_SYMBOLS:
        pd.testing.assert_frame_equal(factors[s].iloc[:, :21], profit_signal_features(today)[s])
    json.dumps(builder.audit, allow_nan=False)
    assert builder.audit["historical_pipeline_receipt_verified"] is False
    for a in builder.audit["reference_coverage"].values():
        assert a["excluded_after_evaluation_end"] == ["2026-10-28"]


def test_current_daily_close_and_future_history_do_not_change_context(history):
    frames, market, days = history
    day = days[22].date()
    baseline = make_macro_feature_builder(frames, market)(_one_day(frames, day))
    changed = {s: f.copy() for s, f in frames.items()}
    for f in changed.values():
        f.loc[f.index.date >= day, ["open", "high", "low", "close"]] *= 10
    news = copy.deepcopy(market)
    for rows in news["data"]["bars"].values():
        for row in rows:
            if pd.Timestamp(row["timestamp"]).tz_convert("America/New_York").date() >= day:
                row["close"] *= 10
    # Today's actual prefix is identical; only the global daily archive changed.
    other = make_macro_feature_builder(changed, news)(_one_day(frames, day))
    for s in TRADED_SYMBOLS:
        pd.testing.assert_frame_equal(baseline[s], other[s])
    partial = {s: f.iloc[:10] for s, f in _one_day(frames, day).items()}
    prefix = make_macro_feature_builder(frames, market)(partial)
    for s in TRADED_SYMBOLS:
        pd.testing.assert_frame_equal(baseline[s].iloc[:10], prefix[s])


def test_missing_daily_reference_or_stock_does_not_compress_or_backfill(history):
    frames, market, days = history
    day, missing = days[22].date(), days[21].date()
    modified = copy.deepcopy(market)
    modified["data"]["bars"]["SPY"] = [r for r in modified["data"]["bars"]["SPY"]
        if pd.Timestamp(r["timestamp"]).tz_convert("America/New_York").date() != missing]
    incomplete = {s: f.copy() for s, f in frames.items()}
    removed = incomplete["NVDA"].loc[incomplete["NVDA"].index.date == missing].index[10]
    incomplete["NVDA"] = incomplete["NVDA"].drop(removed)
    builder = make_macro_feature_builder(incomplete, modified)
    factors = builder(_one_day(frames, day))["NVDA"]
    assert factors.macro_SPY_return_1d.isna().all()
    assert factors.macro_SPY_return_20d.isna().all()
    assert factors.macro_stock_return_1d.isna().all()
    assert factors.macro_overnight_gap.isna().all()
    assert np.isfinite(factors.macro_QQQ_return_5d).all()
    assert missing.isoformat() in builder.audit["stock_coverage"]["NVDA"]["incomplete_session_dates"]


def test_feature_builder_is_shared_by_fit_and_forecast_and_default_is_unchanged(history):
    frames, market, days = history
    cutoff = pd.Timestamp(days[24].date(), tz="America/New_York")
    today = _one_day(frames, cutoff.date())
    builder = make_macro_feature_builder(frames, market)
    macro = ProfitSignalModel.fit(frames, cutoff, CANDIDATES["ridge30_plan"], feature_builder=builder)
    assert macro.feature_builder is builder
    assert len(macro.feature_names) == 41
    assert all(np.isfinite(f.to_numpy()).all() for f in macro.forecast_frames(today).values())
    original = ProfitSignalModel.fit(frames, cutoff, CANDIDATES["ridge30_plan"])
    explicit = ProfitSignalModel.fit(frames, cutoff, CANDIDATES["ridge30_plan"], feature_builder=profit_signal_features)
    assert original.models == explicit.models
    assert original.audit == explicit.audit
    np.testing.assert_array_equal(original.covariance, explicit.covariance)
    assert len(original.feature_names) == 21
    for s in TRADED_SYMBOLS:
        pd.testing.assert_frame_equal(original.forecast_frames(today)[s], explicit.forecast_frames(today)[s])


def test_invalid_receipt_duplicate_sessions_and_out_of_scope_decisions_fail(history):
    frames, market, days = history
    duplicated = copy.deepcopy(market)
    duplicated["data"]["bars"]["SPY"].append(duplicated["data"]["bars"]["SPY"][0])
    with pytest.raises(ValueError, match="Duplicate reference"):
        make_macro_feature_builder(frames, duplicated)
    fake_receipt = copy.deepcopy(market)
    fake_receipt["point_in_time_receipt_historical"] = True
    with pytest.raises(ValueError, match="must not claim historical receipt"):
        make_macro_feature_builder(frames, fake_receipt)
    end = days[23].date()
    builder = make_macro_feature_builder(frames, market, evaluation_end=end.isoformat())
    with pytest.raises(ValueError, match="registered macro-context"):
        builder(_one_day(frames, days[24].date()))
