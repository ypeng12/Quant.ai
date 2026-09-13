"""Capture real stock top-of-book quotes and trades from Alpaca.

This is an L1 collector: each quote has one best bid and one best ask, with
their displayed sizes.  It is not an L2/L3 feed and must not be labelled as a
multi-level order book.  The module is inert until its explicit CLI is run.
"""

from __future__ import annotations

import json
import hashlib
import numpy as np
from pathlib import Path
import threading
from typing import Iterable

import pandas as pd
from .history import validate_symbol


def _field(value, name):
    return getattr(value, name, None) if not isinstance(value, dict) else value.get(name)


def _timestamp(value) -> str:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("An explicit timezone-aware event timestamp is required")
    return stamp.tz_convert("UTC").isoformat()


class AlpacaL1Capture:
    """Append-only raw capture.  It does not submit orders or alter a strategy."""

    def __init__(self, symbols: Iterable[str], output_dir: str | Path, *, feed: str = "iex"):
        clean = tuple(sorted({validate_symbol(symbol) for symbol in symbols}))
        if not clean:
            raise ValueError("At least one symbol is required")
        if feed.lower() not in {"iex", "sip"}:
            raise ValueError("feed must be iex or sip")
        self.symbols = clean
        self.output_dir = Path(output_dir)
        self.feed = feed.lower()
        self._lock = threading.Lock()

    def _event_path(self, timestamp: str, symbol: str) -> Path:
        day = pd.Timestamp(timestamp).tz_convert("America/New_York").date().isoformat()
        return self.output_dir / day / f"{symbol}.jsonl"

    def _append(self, event: dict) -> None:
        if validate_symbol(event['symbol']) not in self.symbols:
            raise ValueError('Event symbol was not requested')
        path = self._event_path(event["timestamp"], event["symbol"])
        path.parent.mkdir(parents=True, exist_ok=True)
        # JSONL retains every original event and is safe to replay/audit.
        with self._lock, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, allow_nan=False, separators=(",", ":")) + "\n")

    async def on_quote(self, quote) -> None:
        event = {
            "schema_version": 1,
            "event_type": "quote",
            "source": "alpaca_stock_websocket",
            "market_depth": "L1",
            "feed": self.feed,
            "symbol": str(_field(quote, "symbol")).upper(),
            "timestamp": _timestamp(_field(quote, "timestamp")),
            "received_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "quote_size_unit": "round_lots",
            "conditions": _field(quote, "conditions"),
            "bid_price": float(_field(quote, "bid_price")),
            "bid_size": float(_field(quote, "bid_size")),
            "ask_price": float(_field(quote, "ask_price")),
            "ask_size": float(_field(quote, "ask_size")),
            "bid_exchange": _field(quote, "bid_exchange"),
            "ask_exchange": _field(quote, "ask_exchange"),
        }
        if (not np.isfinite([event[k] for k in ('bid_price','ask_price','bid_size','ask_size')]).all()
                or min(event['bid_size'],event['ask_size']) < 0
                or event["bid_price"] <= 0 or event["ask_price"] <= 0 or event["bid_price"] > event["ask_price"]):
            raise ValueError("Invalid L1 quote received")
        self._append(event)

    async def on_trade(self, trade) -> None:
        event = {
            "schema_version": 1,
            "event_type": "trade",
            "source": "alpaca_stock_websocket",
            "market_depth": "trade_print",
            "feed": self.feed,
            "symbol": str(_field(trade, "symbol")).upper(),
            "timestamp": _timestamp(_field(trade, "timestamp")),
            "received_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "trade_size_unit": "shares",
            "price": float(_field(trade, "price")),
            "size": float(_field(trade, "size")),
            "exchange": _field(trade, "exchange"),
            "trade_id": _field(trade, "id"),
            "conditions": _field(trade, "conditions"),
        }
        if not np.isfinite([event['price'],event['size']]).all() or event["price"] <= 0 or event["size"] <= 0:
            raise ValueError("Invalid trade received")
        self._append(event)

    def run(self, api_key: str, secret_key: str) -> None:
        """Run the websocket until interrupted by the operator."""
        if not api_key or not secret_key:
            raise ValueError("Alpaca market-data credentials are required")
        from alpaca.data.enums import DataFeed
        from alpaca.data.live import StockDataStream

        stream = StockDataStream(api_key, secret_key, feed=DataFeed(self.feed))
        stream.subscribe_quotes(self.on_quote, *self.symbols)
        stream.subscribe_trades(self.on_trade, *self.symbols)
        stream.run()


def load_real_l1_events(capture_dir: str | Path, symbol: str, session_date=None) -> pd.DataFrame:
    """Load retained real L1 quote/trade events, rejecting proxy-labelled rows."""
    root = Path(capture_dir)
    verified_files = None
    manifest_path = root/'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('status') != 'complete' or not manifest.get('normalized_files'):
            raise ValueError('Historical capture is incomplete or has no verified normalized files')
        for entry in manifest['normalized_files']:
            path = (root/entry['path']).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
                raise ValueError('Historical normalized data integrity check failed')
        verified_files = {(root/e['path']).resolve() for e in manifest['normalized_files']}
    symbol = validate_symbol(symbol)
    files = [root / str(session_date) / f"{symbol}.jsonl"] if session_date else sorted(root.glob(f"*/{symbol}.jsonl"))
    rows = []
    for path in files:
        if not path.exists():
            continue
        if verified_files is not None and path.resolve() not in verified_files:
            raise ValueError('Historical event file is not listed in the verified manifest')
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if (event.get("schema_version") == 1 and event.get("event_type") in {"quote", "trade"}
                    and event.get("source") in {"alpaca_stock_websocket", "alpaca_stock_historical"} and event.get("symbol") == symbol):
                stamp=pd.Timestamp(event.get('timestamp'))
                if pd.isna(stamp) or stamp.tzinfo is None:raise ValueError('Event file has missing or timezone-naive timestamp')
                rows.append(event)
    if not rows:
        return pd.DataFrame(columns=["event_type", "timestamp", "symbol"])
    frame = pd.DataFrame(rows)
    timestamps = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True))
    frame.index = timestamps.tz_convert("America/New_York")
    frame = frame.sort_index(kind="stable")
    return frame


def load_real_l1_quotes(capture_dir: str | Path, symbol: str, session_date=None) -> pd.DataFrame:
    """Load genuine L1 quote events; no OHLCV proxy rows are accepted."""
    frame = load_real_l1_events(capture_dir, symbol, session_date)
    required = ["bid_price", "bid_size", "ask_price", "ask_size"]
    if frame.empty:
        return pd.DataFrame(columns=["timestamp", *required])
    frame = frame.loc[frame["event_type"] == "quote"].copy()
    if frame.empty or frame.get("market_depth", pd.Series(dtype=object)).ne("L1").any():
        return pd.DataFrame(columns=["timestamp", *required])
    if frame.index.has_duplicates:
        frame = frame[~frame.index.duplicated(keep="last")]
    values = frame[required].astype(float)
    if not np.isfinite(values.to_numpy()).all() or ((values.bid_price <= 0) | (values.ask_price <= 0) | (values.bid_size < 0)
            | (values.ask_size < 0) | (values.bid_price > values.ask_price)).any():
        raise ValueError("Captured L1 quote file has invalid fields")
    return values


def real_l1_to_five_minute(quotes: pd.DataFrame) -> pd.DataFrame:
    """Use the final observed real quote in each 5-minute interval."""
    if quotes.empty:
        return quotes.copy()
    return quotes.resample("5min").last().dropna(how="any")


def l1_capture_status(capture_dir: str | Path, symbol: str) -> dict:
    """Small, read-only status record for the UI; it never invents a book."""
    events = load_real_l1_events(capture_dir, symbol)
    symbol = validate_symbol(symbol)
    if events.empty:
        return {
            "success": False, "status": "unavailable", "ticker": symbol,
            "market_depth": None, "events": 0,
            "reason": "No captured real L1 quote/trade events. Start the explicit Alpaca L1 collector during market hours.",
        }
    quotes = events.loc[events.event_type == "quote"]
    trades = events.loc[events.event_type == "trade"]
    latest_quote = None
    if not quotes.empty:
        quote = quotes.iloc[-1]
        latest_quote = {
            "timestamp": quotes.index[-1].isoformat(),
            "bid_price": float(quote.bid_price), "bid_size": float(quote.bid_size),
            "ask_price": float(quote.ask_price), "ask_size": float(quote.ask_size),
        }
    return {
        "success": True, "status": "complete", "ticker": symbol,
        "source": sorted(events.source.unique().tolist()), "feed": sorted(events.feed.dropna().unique().tolist()), "market_depth": "L1",
        "quote_size_unit": "round_lots", "trade_size_unit": "shares",
        "events": int(len(events)), "quote_events": int(len(quotes)), "trade_events": int(len(trades)),
        "first_event": events.index[0].isoformat(), "last_event": events.index[-1].isoformat(),
        "latest_quote": latest_quote,
        "reason": "Recorded real top-of-book quotes and trades. This is L1, not multi-level L2 depth.",
    }
