"""Capture real stock top-of-book quotes and trades from Alpaca.

This is an L1 collector: each quote has one best bid and one best ask, with
their displayed sizes.  It is not an L2/L3 feed and must not be labelled as a
multi-level order book.  The module is inert until its explicit CLI is run.
"""

from __future__ import annotations

import asyncio
import json
import hashlib
import os
import queue
import numpy as np
from pathlib import Path
import threading
import time
from typing import Iterable
import uuid

import pandas as pd
from .history import validate_symbol


_WIRE_FIELDS = {
    "symbol": "S", "timestamp": "t", "bid_price": "bp", "bid_size": "bs",
    "ask_price": "ap", "ask_size": "as", "bid_exchange": "bx",
    "ask_exchange": "ax", "conditions": "c", "price": "p", "size": "s",
    "exchange": "x", "id": "i",
}


def _field(value, name):
    if isinstance(value, dict):
        return value.get(name, value.get(_WIRE_FIELDS.get(name)))
    return getattr(value, name, None)


def _timestamp(value) -> str:
    # msgpack.Timestamp.to_datetime() truncates sub-microsecond precision.
    if hasattr(value, "seconds") and hasattr(value, "nanoseconds"):
        value = pd.Timestamp(value.seconds, unit="s", tz="UTC") + pd.Timedelta(value.nanoseconds, unit="ns")
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("An explicit timezone-aware event timestamp is required")
    return stamp.tz_convert("UTC").isoformat()


def _json_value(value):
    """Keep raw market fields JSON-safe, including anomalous numeric values."""
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "seconds") and hasattr(value, "nanoseconds"):
        return {"seconds": value.seconds, "nanoseconds": value.nanoseconds}
    if isinstance(value, (pd.Timestamp,)) or hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return {"unsupported_type": type(value).__name__}


class AlpacaL1Capture:
    """Append-only raw capture.  It does not submit orders or alter a strategy."""

    def __init__(self, symbols: Iterable[str], output_dir: str | Path, *, feed: str = "iex", status_interval_seconds: float = 5.0,
                 writer_queue_capacity: int = 8192, writer_batch_size: int = 256,
                 writer_drain_timeout_seconds: float = 10.0):
        clean = tuple(sorted({validate_symbol(symbol) for symbol in symbols}))
        if not clean:
            raise ValueError("At least one symbol is required")
        if feed.lower() not in {"iex", "sip"}:
            raise ValueError("feed must be iex or sip")
        self.symbols = clean
        self.output_dir = Path(output_dir)
        self.feed = feed.lower()
        if not np.isfinite(status_interval_seconds) or status_interval_seconds < 0:
            raise ValueError("status_interval_seconds must be finite and nonnegative")
        self.status_interval_seconds = status_interval_seconds
        for name, value in (("writer_queue_capacity", writer_queue_capacity), ("writer_batch_size", writer_batch_size)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.writer_queue_capacity = writer_queue_capacity
        self.writer_batch_size = writer_batch_size
        if not np.isfinite(writer_drain_timeout_seconds) or writer_drain_timeout_seconds <= 0:
            raise ValueError("writer_drain_timeout_seconds must be finite and positive")
        self.writer_drain_timeout_seconds = writer_drain_timeout_seconds
        self._lock = threading.RLock()
        self._status_lock = threading.Lock()
        self._writer_queue = None
        self._writer_thread = None
        self._writer_handles = {}
        self._writer_closing = False
        self._writer_drain_timed_out = False
        self._backpressure_started = None
        self._writer_end = object()
        self._sequence = 0
        self._stream = None
        self._stop_requested = False
        self._fatal_error = None
        self._last_status_write = 0.0
        self._state = {
            "schema_version": 1, "capture_session_id": uuid.uuid4().hex, "pid": os.getpid(),
            "feed": self.feed, "symbols": list(self.symbols), "status": "idle",
            "authenticated": False, "subscribed": False,
            "started_at": None, "stopped_at": None, "connection_id": 0,
            "reconnects": 0, "events": 0, "valid_events": 0, "quarantined_events": 0,
            "last_received_at": None, "last_event_at": None,
            "last_event_by_symbol": {}, "counts_by_symbol": {}, "reconnect_policy": "alpaca_sdk",
            "writer_mode": "synchronous_fixture", "writer_queue_capacity": writer_queue_capacity,
            "writer_batch_size": writer_batch_size, "writer_drain_timeout_seconds": writer_drain_timeout_seconds,
            "observed_events": 0,
            "enqueued_events": 0, "flushed_events": 0, "queue_high_watermark": 0,
            "backpressure_events": 0, "backpressure_seconds": 0.0,
            "last_observed_at": None, "last_flushed_at": None,
            "last_queue_delay_ms": None, "max_queue_delay_ms": 0.0,
            "last_batch_write_ms": None, "max_batch_write_ms": 0.0,
            "last_exchange_to_observed_ms": None,
            "timing_semantics": {
                "received_at": "sdk_callback_start_after_recv_decode_and_dispatch; not socket receipt",
                "exchange_to_observed_ms": "signed host_wall_clock_minus_exchange_timestamp; includes clock offset, feed and SDK delays",
                "queue_delay_ms": "local monotonic time from callback observation to writer processing",
                "flush": "Python buffers flushed to OS; no per-batch fsync durability guarantee",
            },
        }

    def status(self) -> dict:
        """An in-memory snapshot; timestamps distinguish old data from live data."""
        with self._lock:
            result = json.loads(json.dumps(self._state))
            result["writer_queue_events"] = self._writer_queue.qsize() if self._writer_queue is not None else 0
            result["pending_flush_events"] = max(0, result["enqueued_events"] - result["flushed_events"])
            result["unaccepted_observed_events"] = max(0, result["observed_events"] - result["enqueued_events"])
            result["active_backpressure_seconds"] = (time.monotonic() - self._backpressure_started
                                                     if self._backpressure_started is not None else 0.0)
            result["snapshot_at"] = pd.Timestamp.now(tz="UTC").isoformat()
            result["writer_alive"] = bool(self._writer_thread and self._writer_thread.is_alive())
            return result

    def _persist_status(self, *, force: bool = False) -> None:
        with self._status_lock:
            if not force and time.monotonic() - self._last_status_write < self.status_interval_seconds:
                return
            self.output_dir.mkdir(parents=True, exist_ok=True)
            target = self.output_dir / "capture_status.json"
            temporary = target.with_name(f".capture_status.{self._state['capture_session_id']}.tmp")
            temporary.write_text(json.dumps(self.status(), allow_nan=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(target)
            self._last_status_write = time.monotonic()

    def _transition(self, status: str, **details) -> None:
        now = pd.Timestamp.now(tz="UTC").isoformat()
        with self._lock:
            if self._fatal_error:
                details.update(requested_lifecycle_status=status, error_type=self._fatal_error)
                status = "storage_error"
            self._state.update(status=status, updated_at=now, **details)
        path = self.output_dir / "sessions" / f"{self._state['capture_session_id']}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"timestamp": now, "status": status, **details}, allow_nan=False) + "\n")
        self._persist_status(force=True)

    def _event_path(self, timestamp: str, symbol: str) -> Path:
        day = pd.Timestamp(timestamp).tz_convert("America/New_York").date().isoformat()
        return self.output_dir / day / f"{symbol}.jsonl"

    def _append(self, event: dict) -> None:
        valid = event["quality_valid"]
        symbol = event["symbol"] if event["symbol"] in self.symbols else "UNKNOWN"
        path = self._event_path(event["timestamp"] or event["received_at"], symbol)
        if not valid:
            # Keep malformed/crossed source records for audit without
            # feeding malformed rows to existing factor loaders.
            path = path.parent / "quarantine" / path.name
        line = json.dumps(event, allow_nan=False, separators=(",", ":")) + "\n"
        if self._writer_queue is not None:
            # Only the single writer thread owns these handles. The SDK loop
            # neither opens files nor serializes large event payloads.
            if path not in self._writer_handles:
                # Bound descriptors over multi-day runs, including late rows
                # that reopen older partitions.
                if len(self._writer_handles) >= max(8, len(self.symbols) * 4):
                    self._writer_handles.pop(next(iter(self._writer_handles))).close()
                path.parent.mkdir(parents=True, exist_ok=True)
                self._writer_handles[path] = path.open("a", encoding="utf-8")
            self._writer_handles[path].write(line)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
        with self._lock:
            self._state["events"] += 1
            self._state["valid_events" if valid else "quarantined_events"] += 1
            counts = self._state["counts_by_symbol"].setdefault(symbol, {
                "quote_events": 0, "trade_events": 0, "quarantined_events": 0,
            })
            counts[f"{event['event_type']}_events" if valid else "quarantined_events"] += 1
            self._state["last_received_at"] = event["received_at"]
            if event["timestamp"] is not None:
                self._state["last_event_at"] = event["timestamp"]
            self._state["last_event_by_symbol"][symbol] = {
                "timestamp": event["timestamp"], "received_at": event["received_at"],
                "quality_valid": valid,
            }
            if self._writer_queue is None:
                self._state["flushed_events"] += 1
                self._state["last_flushed_at"] = pd.Timestamp.now(tz="UTC").isoformat()
        if self._writer_queue is None:
            self._persist_status()

    def _normalize(self, value, event_type: str, *, received_at=None, connection_id=None) -> dict:
        received_at = received_at or pd.Timestamp.now(tz="UTC").isoformat()
        flags = []
        try:
            timestamp = _timestamp(_field(value, "timestamp"))
        except (TypeError, ValueError, OverflowError):
            timestamp = None
            flags.append("invalid_timestamp")
        symbol = str(_field(value, "symbol") or "").upper()
        if symbol not in self.symbols:
            flags.append("unrequested_or_invalid_symbol")
        fields = ("bid_price", "bid_size", "ask_price", "ask_size") if event_type == "quote" else ("price", "size")
        numeric = {}
        for field in fields:
            try:
                number = float(_field(value, field))
                if not np.isfinite(number):
                    raise ValueError("nonfinite")
                numeric[field] = number
            except (TypeError, ValueError, OverflowError):
                numeric[field] = None
                flags.append(f"invalid_{field}")
        if all(number is not None for number in numeric.values()):
            if event_type == "quote":
                if min(numeric["bid_price"], numeric["ask_price"]) <= 0:
                    flags.append("nonpositive_price")
                if min(numeric["bid_size"], numeric["ask_size"]) < 0:
                    flags.append("negative_size")
                if numeric["bid_price"] > numeric["ask_price"]:
                    flags.append("crossed_quote")
            elif min(numeric.values()) <= 0:
                flags.append("nonpositive_price_or_size")
        valid = not flags
        if event_type == "quote" and valid:
            if numeric["bid_price"] == numeric["ask_price"]:
                flags.append("locked_quote")
            if min(numeric["bid_size"], numeric["ask_size"]) == 0:
                flags.append("zero_displayed_size")
        metadata = ("conditions", "bid_exchange", "ask_exchange") if event_type == "quote" else ("exchange", "conditions")
        raw = value if isinstance(value, dict) else {name: _field(value, name) for name in ("symbol", "timestamp", *fields, *metadata, "id")}
        event = {
            "schema_version": 1, "event_type": event_type,
            "source": "alpaca_stock_websocket", "market_depth": "L1" if event_type == "quote" else "trade_print",
            "feed": self.feed, "symbol": symbol, "timestamp": timestamp,
            "received_at": received_at,
            "received_at_semantics": "sdk_callback_start",
            "capture_session_id": self._state["capture_session_id"],
            "connection_id": self._state["connection_id"] if connection_id is None else connection_id,
            "quality_valid": valid, "quality_flags": flags, "raw": _json_value(raw),
            **numeric, **{field: _json_value(_field(value, field)) for field in metadata},
        }
        if event_type == "quote":
            event["quote_size_unit"] = "round_lots"
        else:
            event.update(trade_size_unit="shares", trade_id=_json_value(_field(value, "id")))
        return event

    def _capture(self, value, event_type: str) -> None:
        received_at = pd.Timestamp.now(tz="UTC").isoformat()
        with self._lock:
            self._state["observed_events"] += 1
            self._state["enqueued_events"] += 1  # Synchronous fixture acceptance.
            self._state["last_observed_at"] = received_at
        try:
            self._append(self._normalize(value, event_type, received_at=received_at))
        except OSError as error:
            # SDK handlers catch exceptions; explicitly stop on failed storage
            # instead of silently continuing with a hole in the capture.
            self._storage_failure(error)
            raise

    def _storage_failure(self, error: Exception) -> None:
        self._fatal_error = self._fatal_error or type(error).__name__
        with self._lock:
            self._state.update(status="storage_error", error_type=self._fatal_error,
                               storage_failure_at=pd.Timestamp.now(tz="UTC").isoformat())
        # Never hold the state lock while asking the SDK event loop to stop.
        try:
            self.stop()
        except Exception:
            # stop() has already set _stop_requested; the stream's existing
            # reconnect hooks also observe that request.
            pass

    def _start_writer(self) -> None:
        if self._writer_queue is not None:
            raise RuntimeError("The collector writer has already been started")
        self._writer_queue = queue.Queue(maxsize=self.writer_queue_capacity)
        self._state["writer_mode"] = "bounded_single_thread"
        self._writer_thread = threading.Thread(target=self._write_loop, name="alpaca-l1-writer", daemon=True)
        self._writer_thread.start()

    def _finish_backpressure(self) -> None:
        with self._lock:
            if self._backpressure_started is not None:
                self._state["backpressure_seconds"] += time.monotonic() - self._backpressure_started
                self._backpressure_started = None

    async def _enqueue(self, value, event_type: str) -> None:
        # This is the first point this handler can observe an event. The SDK
        # has already received, decoded and dispatched it; this is not wire
        # arrival time. Wall-clock offsets are retained, never shifted/clamped.
        observed_mono = time.monotonic()
        observed_at = pd.Timestamp.now(tz="UTC").isoformat()
        with self._lock:
            self._state["observed_events"] += 1
            self._state["last_observed_at"] = observed_at
        if self._writer_closing or self._fatal_error:
            raise RuntimeError("The L1 writer is closing or has failed")
        self._sequence += 1
        item = (dict(value) if isinstance(value, dict) else value, event_type,
                observed_at, observed_mono, self._state["connection_id"], self._sequence)
        waited_at = None
        while True:
            if self._writer_closing or self._fatal_error:
                self._finish_backpressure()
                raise RuntimeError("The L1 writer closed before accepting the event")
            try:
                with self._lock:
                    self._writer_queue.put_nowait(item)
                    self._state["enqueued_events"] += 1
                    self._state["last_observed_at"] = observed_at
                    self._state["queue_high_watermark"] = max(
                        self._state["queue_high_watermark"], self._writer_queue.qsize())
                break
            except queue.Full:
                if self._stop_requested:
                    self._finish_backpressure()
                    self._state["shutdown_incomplete"] = True
                    raise RuntimeError("L1 capture stopped while an observed event awaited queue capacity")
                if waited_at is None:
                    waited_at = time.monotonic()
                    with self._lock:
                        self._state["backpressure_events"] += 1
                        self._backpressure_started = waited_at
                # Bounded memory with explicit backpressure. Yielding here
                # lets websocket ping/timeout tasks run even on slow storage.
                await asyncio.sleep(0.001)
        if waited_at is not None:
            self._finish_backpressure()
        # A decoded SDK frame may contain many events without any other await
        # that suspends. This also gives heartbeat and stop tasks a turn.
        await asyncio.sleep(0)

    def _write_loop(self) -> None:
        finishing = False
        try:
            while not finishing and not self._writer_drain_timed_out:
                try:
                    first = self._writer_queue.get(timeout=0.5)
                except queue.Empty:
                    self._persist_status()
                    continue
                if first is self._writer_end:
                    break
                batch = [first]
                while len(batch) < self.writer_batch_size:
                    try:
                        item = self._writer_queue.get_nowait()
                    except queue.Empty:
                        break
                    if item is self._writer_end:
                        finishing = True
                        break
                    batch.append(item)
                started = time.monotonic()
                for value, kind, observed_at, observed_mono, connection, sequence in batch:
                    delay_ms = (time.monotonic() - observed_mono) * 1000
                    event = self._normalize(value, kind, received_at=observed_at, connection_id=connection)
                    event.update(collector_sequence=sequence, writer_queue_delay_ms=delay_ms)
                    signed_ms = (float((pd.Timestamp(observed_at) - pd.Timestamp(event["timestamp"])).total_seconds()) * 1000
                                 if event["timestamp"] is not None else None)
                    with self._lock:
                        self._state["last_queue_delay_ms"] = delay_ms
                        self._state["max_queue_delay_ms"] = max(self._state["max_queue_delay_ms"], delay_ms)
                        self._state["last_exchange_to_observed_ms"] = signed_ms
                    self._append(event)
                for handle in self._writer_handles.values():
                    handle.flush()
                elapsed_ms = (time.monotonic() - started) * 1000
                with self._lock:
                    self._state["flushed_events"] += len(batch)
                    self._state["last_flushed_at"] = pd.Timestamp.now(tz="UTC").isoformat()
                    self._state["last_batch_write_ms"] = elapsed_ms
                    self._state["max_batch_write_ms"] = max(self._state["max_batch_write_ms"], elapsed_ms)
                self._persist_status()
        except Exception as error:
            # The failed batch and any remaining queued events are reported as
            # pending, never silently counted as successfully flushed.
            self._storage_failure(error)
        finally:
            for handle in self._writer_handles.values():
                try:
                    handle.close()
                except OSError as error:
                    self._storage_failure(error)
            self._writer_handles.clear()
            try:
                self._persist_status(force=True)
            except OSError as error:
                self._storage_failure(error)

    def _drain_writer(self) -> bool:
        """Called after SDK callbacks finish; all accepted events precede EOF."""
        self._writer_closing = True
        if self._writer_thread is None:
            return True
        deadline = time.monotonic() + self.writer_drain_timeout_seconds
        while self._writer_thread.is_alive():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                self._writer_queue.put(self._writer_end, timeout=min(0.1, remaining))
                break
            except queue.Full:
                continue
        self._writer_thread.join(timeout=max(0, deadline - time.monotonic()))
        if self._writer_thread.is_alive():
            self._writer_drain_timed_out = True
            self._fatal_error = "WriterDrainTimeout"
            self._stop_requested = True
            with self._lock:
                self._state.update(status="storage_error", error_type=self._fatal_error, shutdown_incomplete=True)
            return False
        return not self._fatal_error

    async def on_quote(self, quote) -> None:
        if self._writer_queue is None:
            self._capture(quote, "quote")
        else:
            await self._enqueue(quote, "quote")

    async def on_trade(self, trade) -> None:
        if self._writer_queue is None:
            self._capture(trade, "trade")
        else:
            await self._enqueue(trade, "trade")

    def stop(self) -> None:
        """Request shutdown, from a CLI signal handler or a different thread."""
        self._stop_requested = True
        stream = self._stream
        if stream is None:
            return
        loop = getattr(stream, "_loop", None)
        if loop is None or not loop.is_running():
            return
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            loop.create_task(stream.stop_ws())
        else:
            stream.stop()

    def run(self, api_key: str, secret_key: str) -> None:
        """Run the websocket until interrupted by the operator."""
        if not api_key or not secret_key:
            raise ValueError("Alpaca market-data credentials are required")
        from alpaca.data.enums import DataFeed
        from alpaca.data.live import StockDataStream

        collector = self

        class ObservedStockDataStream(StockDataStream):
            # The SDK owns reconnect/authentication. These hooks only persist
            # observable lifecycle facts; they do not create a second retry loop.
            async def _start_ws(self):
                await asyncio.to_thread(collector._transition, "connecting")
                try:
                    await super()._start_ws()
                except Exception as error:
                    await asyncio.to_thread(collector._transition, "connection_error", error_type=type(error).__name__)
                    raise
                connection = collector._state["connection_id"] + 1
                await asyncio.to_thread(collector._transition, "connected", authenticated=True, subscribed=False,
                                        connection_id=connection, reconnects=connection - 1)
                if collector._stop_requested:
                    await self.stop_ws()

            async def _dispatch(self, message):
                if message.get("T") == "subscription":
                    quotes = sorted(message.get("quotes") or [])
                    trades = sorted(message.get("trades") or [])
                    subscribed = set(collector.symbols).issubset(quotes) and set(collector.symbols).issubset(trades)
                    await asyncio.to_thread(collector._transition, "subscribed" if subscribed else "subscription_incomplete",
                                            subscribed=subscribed, subscribed_quotes=quotes, subscribed_trades=trades)
                elif message.get("T") == "error":
                    # Store only the documented numeric code, never an auth
                    # payload or arbitrary exception text.
                    await asyncio.to_thread(collector._transition, "server_error", error_code=message.get("code"))
                await super()._dispatch(message)

            async def _consume(self):
                try:
                    await super()._consume()
                except Exception as error:
                    await asyncio.to_thread(collector._transition, "disconnected", authenticated=False, subscribed=False,
                                            error_type=type(error).__name__)
                    raise

        stream = ObservedStockDataStream(api_key, secret_key, raw_data=True, feed=DataFeed(self.feed))
        self._stream = stream
        self._transition("starting", started_at=pd.Timestamp.now(tz="UTC").isoformat())
        self._start_writer()
        try:
            if not self._stop_requested:
                stream.subscribe_quotes(self.on_quote, *self.symbols)
                stream.subscribe_trades(self.on_trade, *self.symbols)
                stream.run()
        finally:
            try:
                self._transition("draining", authenticated=False, subscribed=False)
            except OSError as error:
                self._storage_failure(error)
            finally:
                self._drain_writer()
            self._stream = None
            status = ("storage_error" if self._fatal_error else "stopped_incomplete" if self._state.get("shutdown_incomplete")
                      else "stopped" if self._stop_requested else "stream_ended")
            self._transition(status, authenticated=False, subscribed=False,
                             stopped_at=pd.Timestamp.now(tz="UTC").isoformat())
        if self._fatal_error:
            raise RuntimeError(f"L1 capture stopped after a storage error ({self._fatal_error})")


def load_real_l1_events(capture_dir: str | Path, symbol: str, session_date=None) -> pd.DataFrame:
    """Load real events, checking selected-file hashes and manifest structure.

    Every declared file must exist inside the capture root. Content hashes are
    checked for files actually read by this query, so a per-session request does
    not repeatedly hash unrelated multi-million-event archives.
    """
    root = Path(capture_dir)
    symbol = validate_symbol(symbol)
    files = [root / str(session_date) / f"{symbol}.jsonl"] if session_date else sorted(root.glob(f"*/{symbol}.jsonl"))
    verified_files = None
    manifest_path = root/'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('status') != 'complete' or not manifest.get('normalized_files'):
            raise ValueError('Historical capture is incomplete or has no verified normalized files')
        verified_files = {}
        for entry in manifest['normalized_files']:
            path = (root/entry['path']).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError('Historical normalized data integrity check failed')
            if path in verified_files:
                raise ValueError('Historical normalized manifest contains duplicate files')
            verified_files[path] = entry['sha256']
    rows = []
    for path in files:
        if not path.exists():
            if verified_files is not None and path.resolve() in verified_files:
                raise ValueError('Historical normalized data integrity check failed')
            continue
        if verified_files is not None and path.resolve() not in verified_files:
            raise ValueError('Historical event file is not listed in the verified manifest')
        digest = hashlib.sha256()
        # Parse incrementally while hashing the exact same bytes; no second
        # file-sized buffer or separate verification/read race is needed.
        with path.open("rb") as handle:
            for line in handle:
                if verified_files is not None:
                    digest.update(line)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    if verified_files is not None:
                        raise ValueError('Historical normalized data integrity check failed') from error
                    raise
                if (event.get("schema_version") == 1 and event.get("event_type") in {"quote", "trade"}
                        and event.get("source") in {"alpaca_stock_websocket", "alpaca_stock_historical"} and event.get("symbol") == symbol):
                    stamp=pd.Timestamp(event.get('timestamp'))
                    if pd.isna(stamp) or stamp.tzinfo is None:raise ValueError('Event file has missing or timezone-naive timestamp')
                    rows.append(event)
        if verified_files is not None and digest.hexdigest() != verified_files[path.resolve()]:
            raise ValueError('Historical normalized data integrity check failed')
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


def _live_capture_status(root: Path, symbol: str, *, max_event_age_seconds: float, tail_bytes: int) -> dict:
    """Bounded UI read of process metadata and the newest day's event tail."""
    snapshot = json.loads((root / "capture_status.json").read_text(encoding="utf-8"))
    try:
        pid = int(snapshot.get("pid", 0))
        if pid <= 0:
            raise ValueError("missing process id")
        os.kill(pid, 0)  # Signal zero only checks existence; it does not alter the process.
        process_alive = True
    except (TypeError, ValueError, OverflowError, ProcessLookupError):
        process_alive = False
    except PermissionError:
        process_alive = True
    latest = snapshot.get("last_event_by_symbol", {}).get(symbol, {})
    received_at = pd.to_datetime(latest.get("received_at"), utc=True, errors="coerce")
    age = None if received_at is None or pd.isna(received_at) else float((pd.Timestamp.now(tz="UTC") - received_at).total_seconds())
    event_at = pd.to_datetime(latest.get("timestamp"), utc=True, errors="coerce")
    event_age = None if event_at is None or pd.isna(event_at) else float((pd.Timestamp.now(tz="UTC") - event_at).total_seconds())
    subscribed = bool(process_alive and snapshot.get("status") == "subscribed" and snapshot.get("subscribed")
                      and symbol in snapshot.get("symbols", []))
    is_live = bool(subscribed and latest.get("quality_valid") and age is not None and 0 <= age <= max_event_age_seconds
                   and event_age is not None and 0 <= event_age <= max_event_age_seconds)

    files = sorted(root.glob(f"*/{symbol}.jsonl"))
    rows = []
    if files:
        with files[-1].open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            start = max(0, size - tail_bytes)
            handle.seek(start)
            if start:
                handle.readline(tail_bytes)  # Skip a possible partial first record.
            tail = handle.read(max(0, size - handle.tell()))
            for line in tail.splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # A concurrent append can expose an unfinished final line.
                if (row.get("schema_version") == 1 and row.get("source") == "alpaca_stock_websocket"
                        and row.get("symbol") == symbol and row.get("event_type") in {"quote", "trade"}
                        and row.get("quality_valid", True)):
                    stamp = pd.to_datetime(row.get("timestamp"), utc=True, errors="coerce")
                    if stamp is not None and not pd.isna(stamp):
                        rows.append(row)
    quotes = [row for row in rows if row["event_type"] == "quote" and row.get("market_depth") == "L1"]
    latest_quote = None
    quote_is_live = False
    if quotes:
        quote = max(quotes, key=lambda row: pd.Timestamp(row["timestamp"]))
        try:
            fields = {field: float(quote[field]) for field in ("bid_price", "bid_size", "ask_price", "ask_size")}
            if (all(np.isfinite(value) for value in fields.values()) and fields["bid_price"] > 0
                    and fields["ask_price"] >= fields["bid_price"] and min(fields["bid_size"], fields["ask_size"]) >= 0):
                latest_quote = {"timestamp": quote["timestamp"], **fields}
                quote_age = float((pd.Timestamp.now(tz="UTC") - pd.Timestamp(quote["timestamp"])).total_seconds())
                quote_is_live = bool(is_live and 0 <= quote_age <= max_event_age_seconds
                                     and quote.get("capture_session_id") == snapshot.get("capture_session_id"))
        except (KeyError, TypeError, ValueError):
            pass
    counts = snapshot.get("counts_by_symbol", {}).get(symbol)
    if counts is None:
        counts = {"quote_events": len(quotes), "trade_events": sum(row["event_type"] == "trade" for row in rows)}
        count_scope = "latest_file_tail_window"
    else:
        count_scope = "current_capture_session_symbol"
    observed = bool(rows)
    waiting = subscribed and latest.get("received_at") is None
    return {
        "success": observed, "status": "complete" if observed else "waiting_for_events" if waiting else "unavailable",
        "ticker": symbol, "source": ["alpaca_stock_websocket"] if observed else [],
        "feed": sorted({row.get("feed") for row in rows if row.get("feed")}),
        "market_depth": "L1" if quotes else None, "quote_size_unit": "round_lots", "trade_size_unit": "shares",
        "events": int(counts.get("quote_events", 0) + counts.get("trade_events", 0)),
        "quote_events": int(counts.get("quote_events", 0)), "trade_events": int(counts.get("trade_events", 0)),
        "quarantined_events": int(counts.get("quarantined_events", 0)), "event_count_scope": count_scope,
        "first_event": min((row["timestamp"] for row in rows), default=None),
        "last_event": max((row["timestamp"] for row in rows), default=None),
        "event_time_scope": "latest_file_tail_window", "latest_quote": latest_quote,
        "is_live": is_live, "latest_quote_is_live": quote_is_live, "last_received_age_seconds": age,
        "last_event_age_seconds": event_age, "live_max_event_age_seconds": max_event_age_seconds,
        "collector": {"pid": snapshot.get("pid"), "process_alive": process_alive,
                      "reported_status": snapshot.get("status"), "updated_at": snapshot.get("updated_at"),
                      "capture_session_id": snapshot.get("capture_session_id"), "subscribed": subscribed,
                      "waiting_for_events": waiting, "connection_id": snapshot.get("connection_id"),
                      "reconnects": snapshot.get("reconnects"), "last_received_at": latest.get("received_at")},
        "reason": ("Subscription acknowledged; waiting for new real quote/trade events." if waiting else
                   "Recent real quote/trade events received by the running collector." if is_live else
                   "Retained L1 data are available; this status does not confirm a fresh live quote." if observed else
                   "No retained real L1 events for this symbol. Check the collector status."),
    }


def l1_capture_status(capture_dir: str | Path, symbol: str, *, max_event_age_seconds: float = 60.0, tail_bytes: int = 262_144) -> dict:
    """Small, read-only status record for the UI; it never invents a book."""
    root = Path(capture_dir)
    symbol = validate_symbol(symbol)
    if not np.isfinite(max_event_age_seconds) or max_event_age_seconds < 0 or tail_bytes < 1:
        raise ValueError("Nonnegative event age and positive tail window are required")
    if not (root / "manifest.json").exists() and (root / "capture_status.json").exists():
        return _live_capture_status(root, symbol, max_event_age_seconds=max_event_age_seconds, tail_bytes=tail_bytes)
    events = load_real_l1_events(capture_dir, symbol)
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
