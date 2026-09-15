"""Causal L1 extensions and quote labels, preserving the feed and clock contract."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .real_l1_alpha import REAL_L1_FEATURES, _require_real_events, _ofi, build_real_l1_features

VERSION = "paper_l1_alpha_v2"
PAPER_L1_FEATURES = REAL_L1_FEATURES + ("l1_ofi_raw", "l1_mean_half_depth", "l1_ofi_depth",
                                      "l1_ofi_x_spread", "l1_ofi_x_session_sin", "l1_ofi_x_session_cos")
_CAPTURE_BOUNDARIES = ("capture_session_id", "connection_id")


def _capture_boundary_columns(events):
    return [name for name in _CAPTURE_BOUNDARIES if name in events and events[name].notna().any()]


def observed_events(events, *, as_of=None):
    """Historical exchange clock or recorded WebSocket arrival clock.

    Late exchange events are excluded from the arrival-clock experiment and
    counted, without deleting raw capture. Historical latency is unverified.
    """
    _require_real_events(events)
    cutoff = None if as_of is None else pd.Timestamp(as_of)
    if cutoff is not None and (pd.isna(cutoff) or cutoff.tzinfo is None):
        raise ValueError("as_of must be timezone-aware")
    out = events.sort_index(kind="stable").copy()
    out.index = out.index.tz_convert("America/New_York")
    sources = out.source.unique()
    if len(sources)!=1 or "feed" not in out or out.feed.isna().any() or not out.feed.isin(("iex", "sip")).all():
        raise ValueError("One explicit source and feed per experiment required")
    dropped = 0
    if sources[0] == "alpaca_stock_websocket":
        if "received_at" not in out:
            raise ValueError("WebSocket events require recorded received_at")
        arrival = pd.to_datetime(out.received_at, utc=True, errors="coerce", format="mixed")
        if arrival.isna().any():
            raise ValueError("Invalid received_at")
        out["exchange_timestamp"] = out.index
        out.index = pd.DatetimeIndex(arrival).tz_convert("America/New_York")
        out = out.sort_index(kind="stable")
        if cutoff is not None:
            out = out.loc[out.index < cutoff]
        fresh = np.ones(len(out), dtype=bool)
        sequence = ["event_type", *_capture_boundary_columns(out)]
        for positions in out.groupby(sequence, sort=False, dropna=False).indices.values():
            order = pd.DatetimeIndex(out.exchange_timestamp.iloc[positions]).asi8
            fresh[positions] = order >= np.maximum.accumulate(order)
        dropped = int((~fresh).sum())
        out = out.loc[fresh]
        clock = "recorded_arrival"
    else:
        clock = "historical_exchange_latency_unverified"
    if cutoff is not None:
        out = out.loc[out.index < cutoff]
    out.attrs.update(clock=clock, late_events_excluded=dropped, feature_version=VERSION)
    return out


def quote_states(events, *, as_of=None, max_gap="30s"):
    if pd.Timedelta(max_gap) <= pd.Timedelta(0):
        raise ValueError("max_gap must be positive")
    observed = observed_events(events, as_of=as_of)
    q = _require_real_events(observed).copy()
    depth = q.bid_size + q.ask_size
    valid = depth.gt(0) & q.ask_price.gt(q.bid_price)
    day = pd.Series(q.index.tz_convert("America/New_York").date, index=q.index)
    gap = q.index.to_series().diff()
    split = day.ne(day.shift()) | gap.gt(pd.Timedelta(max_gap)) | ~valid | ~valid.shift(fill_value=False)
    for name in _capture_boundary_columns(q):
        identity = q[name].astype(object).where(q[name].notna(), "__unrecorded__")
        split |= identity.ne(identity.shift())
    q["segment"] = split.cumsum().to_numpy()
    q["mid"] = (q.bid_price + q.ask_price) / 2
    q["spread"] = q.ask_price - q.bid_price
    q["depth"] = depth
    q["qi"] = (q.bid_size - q.ask_size) / depth.replace(0, np.nan)
    q["weighted_mid"] = (q.ask_price*q.bid_size + q.bid_price*q.ask_size) / depth.replace(0, np.nan)
    q["ofi"] = _ofi(q).mask(split, 0)
    q = q.loc[valid]
    if q.empty:
        raise ValueError("No observed nonlocked two-sided quotes")
    units = q.quote_size_unit.dropna().unique() if "quote_size_unit" in q else []
    if len(units) > 1:
        raise ValueError("Mixed quote size units")
    q.attrs.update(observed.attrs, max_gap=max_gap, feed=str(observed.feed.iloc[0]),
                   symbol=str(observed.symbol.iloc[0]), source=str(observed.source.iloc[0]),
                   quote_size_unit=str(units[0]) if len(units) else "provider_unit_unverified")
    return q


def enhanced_l1_features(events, frequency="5min", *, as_of=None, max_gap="30s"):
    observed = observed_events(events, as_of=as_of)
    base = build_real_l1_features(observed, frequency, as_of=as_of)
    q = quote_states(events, as_of=as_of, max_gap=max_gap)
    res = q.resample(frequency)
    base["l1_ofi_raw"] = res["ofi"].sum(min_count=1)
    base["l1_ofi_normalized"] = base.l1_ofi_raw / res["depth"].median().replace(0, np.nan)
    trades = observed.loc[observed.event_type.eq("trade")]
    if not trades.empty:
        quote_events = observed.loc[observed.event_type.eq("quote")]
        keys = _capture_boundary_columns(observed)
        left = trades[["price", "size", *keys]].reset_index(names="timestamp")
        right = quote_events[["bid_price", "ask_price", *keys]].reset_index(names="quote_timestamp")
        for key in keys:
            left[key] = left[key].astype("string").fillna("__unrecorded__")
            right[key] = right[key].astype("string").fillna("__unrecorded__")
        matched = pd.merge_asof(left, right, left_on="timestamp", right_on="quote_timestamp",
                                by=keys or None, direction="backward", allow_exact_matches=False,
                                tolerance=pd.Timedelta(max_gap)).set_index("timestamp")
        same_day = matched.index.date == matched.quote_timestamp.dt.tz_convert("America/New_York").dt.date
        sign = np.where(matched.price >= matched.ask_price, 1., np.where(matched.price <= matched.bid_price, -1., np.nan))
        sign = np.where(same_day & matched.ask_price.gt(matched.bid_price), sign, np.nan)
        signed = pd.Series(sign * matched["size"].to_numpy(), index=matched.index)
        volume = matched["size"].where(np.isfinite(sign)).resample(frequency).sum(min_count=1)
        base["l1_signed_trade_imbalance"] = signed.resample(frequency).sum(min_count=1) / volume
    base["l1_mean_half_depth"] = res["depth"].mean() / 2
    base["l1_ofi_depth"] = base.l1_ofi_raw / base.l1_mean_half_depth.replace(0, np.nan)
    base["l1_ofi_x_spread"] = base.l1_ofi_depth * base.l1_spread_bps
    minutes = base.index.tz_convert("America/New_York").hour*60 + base.index.tz_convert("America/New_York").minute - 570
    base["l1_ofi_x_session_sin"] = base.l1_ofi_depth * np.sin(2*np.pi*minutes/390)
    base["l1_ofi_x_session_cos"] = base.l1_ofi_depth * np.cos(2*np.pi*minutes/390)
    base.attrs.update(q.attrs, timestamp_convention="bucket_open_available_at_end", depth_unit="provider_quote_size_unit")
    return base.replace([np.inf, -np.inf], np.nan)


def next_move_labels(q):
    """Next different mid and maturity timestamp, without crossing segments."""
    direction = np.full(len(q), np.nan)
    maturity = np.full(len(q), pd.NaT.value, dtype=np.int64)
    for positions in q.groupby("segment", sort=False).indices.values():
        mids = q.mid.iloc[positions].to_numpy()
        changes = np.flatnonzero(np.diff(mids) != 0) + 1
        if not len(changes):
            continue
        starts = np.r_[0, changes[:-1]]
        lengths = changes - starts
        labelled = positions[:changes[-1]]
        direction[labelled] = np.repeat((mids[changes] > mids[starts]).astype(float), lengths)
        maturity[labelled] = np.repeat(q.index[positions[changes]].asi8, lengths)
    ambiguous = maturity <= q.index.asi8
    direction[ambiguous] = np.nan
    maturity[ambiguous] = pd.NaT.value
    return pd.DataFrame({"target": direction, "label_end": pd.to_datetime(maturity, utc=True)}, index=q.index)


def forward_mid_labels(q, horizon="5s", tolerance="1s"):
    """Future mid at first quote at/after t+h, within tolerance and segment."""
    h, tol = pd.Timedelta(horizon), pd.Timedelta(tolerance)
    if h <= pd.Timedelta(0) or tol < pd.Timedelta(0):
        raise ValueError("Invalid horizon/tolerance")
    target = np.full(len(q), np.nan)
    end = np.full(len(q), pd.NaT.value, dtype=np.int64)
    for pos in q.groupby("segment", sort=False).indices.values():
        times = q.index[pos]
        at = times.searchsorted(times + h, side="left")
        eligible = np.flatnonzero(at < len(pos))
        eligible = eligible[times[at[eligible]] <= times[eligible] + h + tol]
        future, present = pos[at[eligible]], pos[eligible]
        target[present] = q.mid.iloc[future].to_numpy() / q.mid.iloc[present].to_numpy() - 1
        end[present] = q.index[future].asi8
    return pd.DataFrame({"target": target, "label_end": pd.to_datetime(end, utc=True)}, index=q.index)
