"""Features from recorded, genuine top-of-book quotes and trade prints.

The output is a research input, not an automatic signal.  It refuses OHLCV
proxies because a model trained on an invented book cannot establish a LOB edge.
"""

from __future__ import annotations


import numpy as np
import pandas as pd


REAL_L1_FEATURES = (
    "l1_spread_bps", "l1_quote_imbalance", "l1_microprice_bps",
    "l1_ofi_normalized", "l1_signed_trade_imbalance", "l1_quote_updates",
)


def _require_real_events(events: pd.DataFrame) -> pd.DataFrame:
    required = {"event_type", "source", "symbol", "market_depth"}
    if not required.issubset(events.columns) or not isinstance(events.index, pd.DatetimeIndex):
        raise ValueError("Real L1 events require source-labelled quote/trade timestamps")
    if events.empty:
        raise ValueError("No captured real L1 events")
    if not events["source"].isin(["alpaca_stock_websocket", "alpaca_stock_historical"]).all():
        raise ValueError("L1 features reject non-websocket or proxy events")
    if events.index.tz is None or events.index.hasnans:
        raise ValueError("Timezone-aware nonmissing event timestamps required")
    if events.symbol.nunique() != 1 or ("feed" in events and events.feed.nunique(dropna=False) != 1):
        raise ValueError("L1 features require one symbol and one feed")
    quotes = events.loc[events.event_type == "quote"].copy()
    if quotes.empty or quotes.market_depth.ne("L1").any():
        raise ValueError("Real L1 quote events are required")
    fields = ["bid_price", "bid_size", "ask_price", "ask_size"]
    if not set(fields).issubset(quotes.columns):
        raise ValueError("L1 quote fields are incomplete")
    quotes[fields] = quotes[fields].astype(float)
    if not np.isfinite(quotes[fields].to_numpy()).all():
        raise ValueError("Invalid nonfinite L1 quote fields")
    if ((quotes.bid_price <= 0) | (quotes.ask_price <= 0) | (quotes.bid_size < 0)
            | (quotes.ask_size < 0) | (quotes.bid_price > quotes.ask_price)).any():
        raise ValueError("Invalid L1 quote fields")
    return quotes.sort_index(kind="stable")


def _ofi(quotes: pd.DataFrame) -> pd.Series:
    """Cont, Kukanov & Stoikov top-of-book OFI from actual quote updates."""
    bid_px, ask_px = quotes.bid_price, quotes.ask_price
    bid_sz, ask_sz = quotes.bid_size, quotes.ask_size
    previous_bid, previous_ask = bid_sz.shift(), ask_sz.shift()
    bid = bid_sz.where(bid_px.ge(bid_px.shift()), 0) - previous_bid.where(bid_px.le(bid_px.shift()), 0)
    ask = ask_sz.where(ask_px.le(ask_px.shift()), 0) - previous_ask.where(ask_px.ge(ask_px.shift()), 0)
    result = bid - ask
    # Overnight events are unrelated quote sequences.
    new_day = quotes.index.to_series().dt.tz_convert("America/New_York").dt.date.ne(
        quotes.index.to_series().dt.tz_convert("America/New_York").dt.date.shift())
    return result.mask(new_day, 0.0).fillna(0.0)


def build_real_l1_features(events: pd.DataFrame, frequency: str = "5min", *, as_of=None, quote_tolerance: str = "30s") -> pd.DataFrame:
    """Aggregate causal L1 features; each bucket uses events up to its end."""
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        if cutoff.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        events = events.loc[events.index < cutoff]
    quotes = _require_real_events(events)
    depth = (quotes.bid_size + quotes.ask_size).replace(0, np.nan)
    quotes["l1_spread_bps"] = (quotes.ask_price - quotes.bid_price) / ((quotes.ask_price + quotes.bid_price) * .5) * 10_000
    quotes["l1_quote_imbalance"] = (quotes.bid_size - quotes.ask_size) / depth
    micro = (quotes.ask_size * quotes.bid_price + quotes.bid_size * quotes.ask_price) / depth
    mid = (quotes.ask_price + quotes.bid_price) * .5
    quotes["l1_microprice_bps"] = (micro - mid) / mid * 10_000
    quotes["_ofi"] = _ofi(quotes)
    quotes["_depth"] = depth

    result = pd.DataFrame(index=quotes.resample(frequency).last().index)
    result["l1_spread_bps"] = quotes.l1_spread_bps.resample(frequency).median()
    result["l1_quote_imbalance"] = quotes.l1_quote_imbalance.resample(frequency).last()
    result["l1_microprice_bps"] = quotes.l1_microprice_bps.resample(frequency).last()
    result["l1_ofi_normalized"] = quotes["_ofi"].resample(frequency).sum() / quotes["_depth"].resample(frequency).median()
    result["l1_quote_updates"] = quotes.event_type.resample(frequency).count()

    trades = events.loc[events.event_type == "trade"].copy().sort_index(kind="stable")
    if trades.empty:
        result["l1_signed_trade_imbalance"] = np.nan
    else:
        if not {"price", "size"}.issubset(trades.columns):
            raise ValueError("Real trade print fields are incomplete")
        trades[["price", "size"]] = trades[["price", "size"]].astype(float)
        if not np.isfinite(trades[["price", "size"]].to_numpy()).all() or (trades[["price", "size"]] <= 0).any().any():
            raise ValueError("Invalid trade price/size")
        asof_quotes = pd.merge_asof(
            trades[["price", "size"]].reset_index(names="timestamp").sort_values("timestamp", kind="stable"),
            quotes[["bid_price", "ask_price"]].reset_index(names="quote_timestamp").sort_values("quote_timestamp", kind="stable"),
            left_on="timestamp", right_on="quote_timestamp", direction="backward", allow_exact_matches=False, tolerance=pd.Timedelta(quote_tolerance),
        ).set_index("timestamp")
        sign = np.where(asof_quotes.price >= asof_quotes.ask_price, 1.0,
                        np.where(asof_quotes.price <= asof_quotes.bid_price, -1.0, np.nan))
        same_day = asof_quotes.index.tz_convert("America/New_York").date == asof_quotes.quote_timestamp.dt.tz_convert("America/New_York").dt.date
        sign = np.where(same_day & asof_quotes.ask_price.gt(asof_quotes.bid_price), sign, np.nan)
        signed = pd.Series(sign * asof_quotes["size"].to_numpy(), index=asof_quotes.index)
        result["l1_signed_trade_imbalance"] = signed.resample(frequency).sum(min_count=1) / asof_quotes["size"].where(np.isfinite(sign)).resample(frequency).sum(min_count=1)
    result = result.loc[:, REAL_L1_FEATURES].replace([np.inf, -np.inf], np.nan)
    if as_of is not None:
        result = result.loc[result.index + pd.Timedelta(frequency) <= cutoff]
    result.attrs.update(source=",".join(sorted(events.source.unique())), market_depth="L1", feature_version="real_l1_v2",
                        timestamp_convention="bar_open_available_at_end", feed=events.feed.iloc[0] if "feed" in events else "unspecified")
    return result


def feature_availability(features: pd.DataFrame) -> dict:
    """Report data availability; never convert missing raw L1 data into zeros."""
    if not set(REAL_L1_FEATURES).issubset(features.columns):
        raise ValueError("Unexpected L1 feature schema")
    complete = features.loc[:, REAL_L1_FEATURES].notna().all(axis=1)
    return {
        "feature_version": "real_l1_v2",
        "market_depth": features.attrs.get("market_depth"),
        "source": features.attrs.get("source"),
        "rows": int(len(features)),
        "complete_rows": int(complete.sum()),
        "complete_fraction": float(complete.mean()) if len(features) else 0.0,
        "usable_for_model": bool(complete.any()),
    }
