"""Features from recorded, genuine top-of-book quotes and trade prints.

The output is a research input, not an automatic signal.  It refuses OHLCV
proxies because a model trained on an invented book cannot establish a LOB edge.
"""

from __future__ import annotations

from typing import Iterable

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
    if events["source"].ne("alpaca_stock_websocket").any():
        raise ValueError("L1 features reject non-websocket or proxy events")
    quotes = events.loc[events.event_type == "quote"].copy()
    if quotes.empty or quotes.market_depth.ne("L1").any():
        raise ValueError("Real L1 quote events are required")
    fields = ["bid_price", "bid_size", "ask_price", "ask_size"]
    if not set(fields).issubset(quotes.columns):
        raise ValueError("L1 quote fields are incomplete")
    quotes[fields] = quotes[fields].astype(float)
    if ((quotes.bid_price <= 0) | (quotes.ask_price <= 0) | (quotes.bid_size < 0)
            | (quotes.ask_size < 0) | (quotes.bid_price > quotes.ask_price)).any():
        raise ValueError("Invalid L1 quote fields")
    return quotes.sort_index()


def _ofi(quotes: pd.DataFrame) -> pd.Series:
    """Cont, Kukanov & Stoikov top-of-book OFI from actual quote updates."""
    bid_px, ask_px = quotes.bid_price, quotes.ask_price
    bid_sz, ask_sz = quotes.bid_size, quotes.ask_size
    d_bid = np.where(bid_px.gt(bid_px.shift()), bid_sz,
                     np.where(bid_px.eq(bid_px.shift()), bid_sz.diff(), 0.0))
    d_ask = np.where(ask_px.lt(ask_px.shift()), ask_sz,
                     np.where(ask_px.eq(ask_px.shift()), ask_sz.diff(), 0.0))
    return pd.Series(d_bid - d_ask, index=quotes.index).fillna(0.0)


def build_real_l1_features(events: pd.DataFrame, frequency: str = "5min") -> pd.DataFrame:
    """Aggregate causal L1 features; each bucket uses events up to its end."""
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

    trades = events.loc[events.event_type == "trade"].copy().sort_index()
    if trades.empty:
        result["l1_signed_trade_imbalance"] = np.nan
    else:
        if not {"price", "size"}.issubset(trades.columns):
            raise ValueError("Real trade print fields are incomplete")
        trades[["price", "size"]] = trades[["price", "size"]].astype(float)
        asof_quotes = pd.merge_asof(
            trades[["price", "size"]].reset_index(names="timestamp").sort_values("timestamp"),
            quotes[["bid_price", "ask_price"]].reset_index(names="quote_timestamp").sort_values("quote_timestamp"),
            left_on="timestamp", right_on="quote_timestamp", direction="backward",
        ).set_index("timestamp")
        sign = np.where(asof_quotes.price >= asof_quotes.ask_price, 1.0,
                        np.where(asof_quotes.price <= asof_quotes.bid_price, -1.0, np.nan))
        signed = pd.Series(sign * asof_quotes["size"].to_numpy(), index=asof_quotes.index)
        result["l1_signed_trade_imbalance"] = signed.resample(frequency).sum(min_count=1) / asof_quotes["size"].resample(frequency).sum(min_count=1)
    result = result.loc[:, REAL_L1_FEATURES].replace([np.inf, -np.inf], np.nan)
    result.attrs.update(source="alpaca_stock_websocket", market_depth="L1", feature_version="real_l1_v1")
    return result


def feature_availability(features: pd.DataFrame) -> dict:
    """Report data availability; never convert missing raw L1 data into zeros."""
    if not set(REAL_L1_FEATURES).issubset(features.columns):
        raise ValueError("Unexpected L1 feature schema")
    complete = features.loc[:, REAL_L1_FEATURES].notna().all(axis=1)
    return {
        "feature_version": "real_l1_v1",
        "market_depth": features.attrs.get("market_depth"),
        "source": features.attrs.get("source"),
        "rows": int(len(features)),
        "complete_rows": int(complete.sum()),
        "complete_fraction": float(complete.mean()) if len(features) else 0.0,
        "usable_for_model": bool(complete.any()),
    }
