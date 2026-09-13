"""Causal L1 extensions and quote labels, preserving the feed and clock contract."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .real_l1_alpha import REAL_L1_FEATURES, _require_real_events, _ofi, build_real_l1_features

VERSION = "paper_l1_alpha_v1"
PAPER_L1_FEATURES = REAL_L1_FEATURES + ("l1_ofi_raw", "l1_mean_half_depth", "l1_ofi_depth",
                                      "l1_ofi_x_spread", "l1_ofi_x_session_sin", "l1_ofi_x_session_cos")


def observed_events(events, *, as_of=None):
    """Historical exchange clock, or recorded arrival clock for WebSocket events.

    Late out-of-order exchange events are excluded from the arrival-clock
    experiment, counted explicitly, and never deleted from raw capture files.
    Historical downloads cannot measure information delivery latency.
    """
    _require_real_events(events)
    out = events.sort_index(kind="stable").copy()
    sources = out.source.unique()
    if len(sources)!=1 or "feed" not in out or out.feed.isna().any():
        raise ValueError("One explicit source and feed per experiment required")
    dropped = 0
    if sources[0]=="alpaca_stock_websocket":
        if "received_at" not in out: raise ValueError("WebSocket events require recorded received_at")
        arrival = pd.to_datetime(out.received_at,utc=True,errors="coerce",format="mixed")
        if arrival.isna().any(): raise ValueError("Invalid received_at")
        out["exchange_timestamp"] = out.index
        out.index = pd.DatetimeIndex(arrival).tz_convert("America/New_York")
        out = out.sort_index(kind="stable")
        order = pd.DatetimeIndex(out.exchange_timestamp).asi8
        fresh = order>=np.maximum.accumulate(order)
        dropped = int((~fresh).sum());out = out.loc[fresh]
        clock = "recorded_arrival"
    else: clock = "historical_exchange_latency_unverified"
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        if cutoff.tzinfo is None: raise ValueError("as_of must be timezone-aware")
        out = out.loc[out.index<cutoff]
    out.attrs.update(clock=clock,late_events_excluded=dropped,feature_version=VERSION)
    return out


def quote_states(events, *, as_of=None, max_gap="30s"):
    observed = observed_events(events,as_of=as_of)
    q = _require_real_events(observed).copy()
    depth = q.bid_size+q.ask_size
    # Locked and empty books do not define the two-sided state models.
    valid = depth.gt(0)&q.ask_price.gt(q.bid_price)
    day = pd.Series(q.index.tz_convert("America/New_York").date,index=q.index)
    gap = q.index.to_series().diff()
    split = day.ne(day.shift()) | gap.gt(pd.Timedelta(max_gap)) | ~valid | ~valid.shift(fill_value=False)
    q["segment"] = split.cumsum().to_numpy()
    q["mid"] = (q.bid_price+q.ask_price)/2
    q["spread"] = q.ask_price-q.bid_price
    q["depth"] = depth
    q["qi"] = (q.bid_size-q.ask_size)/depth.replace(0,np.nan)
    q["weighted_mid"] = (q.ask_price*q.bid_size+q.bid_price*q.ask_size)/depth.replace(0,np.nan)
    q["ofi"] = _ofi(q).mask(split,0)
    q = q.loc[valid]
    q.attrs.update(observed.attrs,max_gap=max_gap,feed=str(observed.feed.iloc[0]),symbol=str(observed.symbol.iloc[0]))
    return q


def enhanced_l1_features(events, frequency="5min", *, as_of=None, max_gap="30s"):
    observed = observed_events(events,as_of=as_of)
    base = build_real_l1_features(observed,frequency,as_of=as_of)
    q = quote_states(events,as_of=as_of,max_gap=max_gap)
    res = q.resample(frequency)
    base["l1_ofi_raw"] = res["ofi"].sum(min_count=1)
    # Paper depth convention: mean of (bid size + ask size) / 2, in quote units.
    base["l1_mean_half_depth"] = res["depth"].mean()/2
    base["l1_ofi_depth"] = base.l1_ofi_raw/base.l1_mean_half_depth.replace(0,np.nan)
    base["l1_ofi_x_spread"] = base.l1_ofi_depth*base.l1_spread_bps
    minutes = base.index.tz_convert("America/New_York").hour*60+base.index.tz_convert("America/New_York").minute-570
    base["l1_ofi_x_session_sin"] = base.l1_ofi_depth*np.sin(2*np.pi*minutes/390)
    base["l1_ofi_x_session_cos"] = base.l1_ofi_depth*np.cos(2*np.pi*minutes/390)
    base.attrs.update(q.attrs,timestamp_convention="bucket_open_available_at_end",depth_unit="provider_quote_size_unit")
    return base.replace([np.inf,-np.inf],np.nan)


def next_move_labels(q):
    """QI target: next different mid, with maturity time; never cross a gap/day."""
    direction = np.full(len(q),np.nan)
    maturity = [pd.NaT]*len(q)
    for positions in q.groupby("segment",sort=False).indices.values():
        mids = q.mid.iloc[positions].to_numpy()
        changes = np.flatnonzero(np.diff(mids)!=0)+1
        start = 0
        for end in changes:
            indices = positions[start:end]
            direction[indices] = float(mids[end]>mids[start])
            for i in indices: maturity[i] = q.index[positions[end]]
            start = end
    return pd.DataFrame({"target":direction,"label_end":pd.to_datetime(maturity,utc=True)},index=q.index)


def forward_mid_labels(q, horizon="5s", tolerance="1s"):
    """Future mark at first quote at/after t+h, bounded by tolerance and segment.

    Mid returns are prediction targets, not executable returns or trading PnL.
    """
    h,tol = pd.Timedelta(horizon),pd.Timedelta(tolerance)
    if h<=pd.Timedelta(0) or tol<pd.Timedelta(0): raise ValueError("Invalid horizon/tolerance")
    target=np.full(len(q),np.nan);end=[pd.NaT]*len(q)
    for pos in q.groupby("segment",sort=False).indices.values():
        times=q.index[pos];at=times.searchsorted(times+h,side="left")
        for i,j in enumerate(at):
            if j<len(pos) and times[j]<=times[i]+h+tol:
                target[pos[i]]=q.mid.iloc[pos[j]]/q.mid.iloc[pos[i]]-1
                end[pos[i]]=times[j]
    return pd.DataFrame({"target":target,"label_end":pd.to_datetime(end,utc=True)},index=q.index)
