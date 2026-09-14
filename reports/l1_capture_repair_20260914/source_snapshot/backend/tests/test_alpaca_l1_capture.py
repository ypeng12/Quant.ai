import asyncio
import ast
import json
from pathlib import Path
import sys
import threading
import time

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.market_data.alpaca_l1_capture import AlpacaL1Capture, l1_capture_status, load_real_l1_events, load_real_l1_quotes, real_l1_to_five_minute


class Quote:
    symbol = "TSLA"
    timestamp = pd.Timestamp("2026-09-11T14:30:01Z")
    bid_price = 300.10
    bid_size = 25
    ask_price = 300.12
    ask_size = 15
    bid_exchange = "Q"
    ask_exchange = "P"


class Trade:
    symbol = "TSLA"
    timestamp = pd.Timestamp("2026-09-11T14:30:02Z")
    price = 300.11
    size = 4
    exchange = "Q"
    id = 99
    conditions = ["@"]


def test_real_l1_capture_persists_only_actual_quote_fields(tmp_path):
    collector = AlpacaL1Capture(["tsla"], tmp_path, feed="iex")
    asyncio.run(collector.on_quote(Quote()))
    asyncio.run(collector.on_trade(Trade()))
    path = tmp_path / "2026-09-11" / "TSLA.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert [event["event_type"] for event in events] == ["quote", "trade"]
    assert events[0]["market_depth"] == "L1"
    assert events[0]["bid_size"] == 25
    assert "Close" not in events[0]
    quotes = load_real_l1_quotes(tmp_path, "TSLA", "2026-09-11")
    assert quotes.iloc[0].ask_price == 300.12
    status = l1_capture_status(tmp_path, "TSLA")
    assert status["status"] == "complete" and status["market_depth"] == "L1"


def test_loader_rejects_proxy_or_invalid_quote_data(tmp_path):
    path = tmp_path / "2026-09-11" / "TSLA.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": 1, "event_type": "quote", "source": "bar_proxy", "market_depth": "L1", "symbol": "TSLA", "timestamp": "2026-09-11T14:30:00Z", "bid_price": 1, "bid_size": 1, "ask_price": 2, "ask_size": 1}) + "\n")
    assert load_real_l1_quotes(tmp_path, "TSLA").empty


def test_final_l1_quote_is_used_per_five_minute_interval(tmp_path):
    collector = AlpacaL1Capture(["TSLA"], tmp_path)
    first = {"symbol": "TSLA", "timestamp": pd.Timestamp("2026-09-11T14:30:01Z"), "bid_price": 100, "bid_size": 10, "ask_price": 101, "ask_size": 20}
    second = {**first, "timestamp": pd.Timestamp("2026-09-11T14:34:59Z"), "bid_price": 102, "ask_price": 103}
    asyncio.run(collector.on_quote(first))
    asyncio.run(collector.on_quote(second))
    bars = real_l1_to_five_minute(load_real_l1_quotes(tmp_path, "TSLA"))
    assert len(bars) == 1
    assert bars.iloc[0].bid_price == 102


@pytest.mark.parametrize("changed,flag", [
    ({"bid_price": 302}, "crossed_quote"),
    ({"bid_price": float("nan")}, "invalid_bid_price"),
    ({"ask_size": None}, "invalid_ask_size"),
    ({"bid_size": -1}, "negative_size"),
    ({"timestamp": "not-a-timestamp"}, "invalid_timestamp"),
    ({"symbol": "../../secret"}, "unrequested_or_invalid_symbol"),
])
def test_anomalous_events_are_retained_and_next_quote_still_captured(tmp_path, changed, flag):
    collector = AlpacaL1Capture(["TSLA"], tmp_path, status_interval_seconds=0)
    quote = {field: getattr(Quote, field) for field in ("symbol", "timestamp", "bid_price", "bid_size", "ask_price", "ask_size")}
    asyncio.run(collector.on_quote({**quote, **changed}))
    asyncio.run(collector.on_quote(quote))

    rejected = list(tmp_path.glob("*/quarantine/*.jsonl"))
    assert len(rejected) == 1
    event = json.loads(rejected[0].read_text())
    assert event["quality_valid"] is False and flag in event["quality_flags"]
    assert "raw" in event
    assert len(load_real_l1_quotes(tmp_path, "TSLA")) == 1
    status = json.loads((tmp_path / "capture_status.json").read_text())
    assert status["events"] == 2
    assert status["valid_events"] == 1 and status["quarantined_events"] == 1
    assert status["last_event_by_symbol"]["TSLA"]["quality_valid"] is True


def test_raw_sdk_message_preserves_nanosecond_exchange_timestamp(tmp_path):
    from msgpack import Timestamp

    collector = AlpacaL1Capture(["TSLA"], tmp_path)
    stamp = Timestamp(1789137001, 123456789)
    quote = {"T": "q", "S": "TSLA", "t": stamp, "bp": 300.10,
             "ap": 300.12, "bs": 25, "as": 15, "bx": "Q", "ax": "P", "c": ["R"]}
    asyncio.run(collector.on_quote(quote))
    path = next(tmp_path.glob("*/TSLA.jsonl"))
    event = json.loads(path.read_text())
    assert event["timestamp"].endswith(".123456789+00:00")
    assert event["raw"]["t"] == {"seconds": stamp.seconds, "nanoseconds": stamp.nanoseconds}
    assert event["bid_exchange"] == "Q" and event["conditions"] == ["R"]
    assert event["capture_session_id"] == collector.status()["capture_session_id"]


def test_bad_trade_preserves_raw_value_without_json_nan(tmp_path):
    collector = AlpacaL1Capture(["TSLA"], tmp_path)
    asyncio.run(collector.on_trade({"S": "TSLA", "t": Trade.timestamp,
                                   "p": float("inf"), "s": 10, "i": 3}))
    path = next(tmp_path.glob("*/quarantine/TSLA.jsonl"))
    event = json.loads(path.read_text())
    assert event["price"] is None and event["raw"]["p"] == "inf"
    assert event["trade_id"] == 3 and "invalid_price" in event["quality_flags"]


def test_locked_quote_is_retained_with_quality_warning(tmp_path):
    collector = AlpacaL1Capture(["TSLA"], tmp_path)
    asyncio.run(collector.on_quote({"S": "TSLA", "t": Quote.timestamp,
                                   "bp": 300, "ap": 300, "bs": 0, "as": 10}))
    event = json.loads(next(tmp_path.glob("*/TSLA.jsonl")).read_text())
    assert event["quality_valid"] is True
    assert set(event["quality_flags"]) == {"locked_quote", "zero_displayed_size"}


def test_sdk_lifecycle_records_reconnect_ack_and_controlled_stop(tmp_path, monkeypatch):
    import alpaca.data.live

    collector = AlpacaL1Capture(["TSLA"], tmp_path)

    class FakeStockDataStream:
        def __init__(self, api_key, secret_key, **kwargs):
            assert kwargs["raw_data"] is True
            self._loop = None
            self.consumptions = 0
            self.stopped = False

        def subscribe_quotes(self, handler, *symbols):
            self.on_quote = handler

        def subscribe_trades(self, handler, *symbols):
            self.on_trade = handler

        async def _start_ws(self):
            pass

        async def _dispatch(self, message):
            pass

        async def _consume(self):
            self.consumptions += 1
            if self.consumptions == 1:
                raise ConnectionError("test network disconnect")
            await self.on_quote(Quote())

        async def stop_ws(self):
            self.stopped = True

        def run(self):
            async def consume():
                self._loop = asyncio.get_running_loop()
                await self._start_ws()
                await self._dispatch({"T": "subscription", "quotes": ["TSLA"], "trades": []})
                assert collector.status()["status"] == "subscription_incomplete"
                try:
                    await self._consume()
                except ConnectionError:
                    assert collector.status()["status"] == "disconnected"
                # Simulate the existing SDK's reconnect loop, exercising only
                # observer hooks in our subclass.
                await self._start_ws()
                await self._dispatch({"T": "subscription", "quotes": ["TSLA"], "trades": ["TSLA"]})
                assert collector.status()["status"] == "subscribed"
                await self._consume()
                collector.stop()
                await asyncio.sleep(0)
                assert self.stopped
            asyncio.run(consume())

    monkeypatch.setattr(alpaca.data.live, "StockDataStream", FakeStockDataStream)
    collector.run("test-key", "test-secret")
    status = collector.status()
    assert status["status"] == "stopped" and status["subscribed"] is False
    assert status["connection_id"] == 2 and status["reconnects"] == 1
    assert status["pid"] > 0 and status["last_received_at"]
    event = json.loads(next(tmp_path.glob("*/TSLA.jsonl")).read_text())
    assert event["connection_id"] == 2
    journal = next((tmp_path / "sessions").glob("*.jsonl")).read_text()
    assert "disconnected" in journal and "subscribed" in journal
    assert "test-key" not in journal and "test-secret" not in journal


def test_storage_failure_stops_capture_instead_of_losing_more_events(tmp_path, monkeypatch):
    collector = AlpacaL1Capture(["TSLA"], tmp_path)

    def unavailable_storage(event):
        raise OSError("disk unavailable")

    monkeypatch.setattr(collector, "_append", unavailable_storage)
    with pytest.raises(OSError):
        asyncio.run(collector.on_quote(Quote()))
    assert collector.status()["status"] == "storage_error"
    assert collector._stop_requested is True


def test_bounded_writer_preserves_order_and_callback_clock_while_loop_remains_responsive(tmp_path, monkeypatch):
    collector = AlpacaL1Capture(["TSLA"], tmp_path, writer_queue_capacity=2, writer_batch_size=2)
    original_append = collector._append
    writer_started = threading.Event()
    release_writer = threading.Event()

    def slow_append(event):
        writer_started.set()
        assert release_writer.wait(timeout=3)
        time.sleep(0.003)
        original_append(event)

    monkeypatch.setattr(collector, "_append", slow_append)
    collector._start_writer()
    future_stamp = (pd.Timestamp.now(tz="UTC") + pd.Timedelta("1h")).isoformat()
    quote = {"S": "TSLA", "t": future_stamp, "bp": 300, "ap": 301, "bs": 10, "as": 20}
    ticks = []

    async def run():
        collector._state["connection_id"] = 7
        await collector.on_quote(quote)
        assert await asyncio.to_thread(writer_started.wait, 1)
        collector._state["connection_id"] = 8

        async def enqueue_rest():
            for index in range(20):
                await collector.on_quote({**quote, "bs": index})

        async def heartbeat():
            for _ in range(10):
                ticks.append(time.monotonic())
                await asyncio.sleep(0.002)
            release_writer.set()

        await asyncio.wait_for(asyncio.gather(enqueue_rest(), heartbeat()), 3)
        await asyncio.to_thread(collector._drain_writer)

    try:
        asyncio.run(run())
    finally:
        release_writer.set()
        collector._drain_writer()
    events = [json.loads(row) for path in tmp_path.glob("*/TSLA.jsonl") for row in path.read_text().splitlines()]
    assert len(events) == 21 and [event["collector_sequence"] for event in events] == list(range(1, 22))
    assert events[0]["connection_id"] == 7 and all(event["connection_id"] == 8 for event in events[1:])
    assert all(event["timestamp"] == future_stamp for event in events)
    assert all(event["received_at_semantics"] == "sdk_callback_start" for event in events)
    assert pd.Timestamp(events[0]["received_at"]) < pd.Timestamp(events[1]["received_at"])
    status = collector.status()
    assert status["observed_events"] == status["enqueued_events"] == status["flushed_events"] == status["events"] == 21
    assert status["unaccepted_observed_events"] == 0
    assert status["pending_flush_events"] == 0 and status["writer_alive"] is False
    assert status["queue_high_watermark"] <= 2
    assert status["backpressure_events"] > 0 and status["backpressure_seconds"] > 0
    assert status["max_queue_delay_ms"] > 10 and status["last_exchange_to_observed_ms"] < 0
    assert len(ticks) == 10  # Writer stall did not block the independent coroutine.


def test_async_writer_failure_is_explicit_and_drain_does_not_hang(tmp_path, monkeypatch):
    collector = AlpacaL1Capture(["TSLA"], tmp_path, writer_queue_capacity=1)

    def fail_append(event):
        raise OSError("storage unavailable")

    monkeypatch.setattr(collector, "_append", fail_append)
    collector._start_writer()

    async def run():
        await collector.on_quote(Quote())
        for _ in range(100):
            if collector._fatal_error:
                break
            await asyncio.sleep(0.005)
        assert collector._fatal_error == "OSError"
        with pytest.raises(RuntimeError, match="closing or has failed"):
            await collector.on_trade(Trade())
        await asyncio.wait_for(asyncio.to_thread(collector._drain_writer), 2)

    asyncio.run(run())
    status = collector.status()
    assert status["status"] == "storage_error" and collector._stop_requested
    assert status["enqueued_events"] == status["pending_flush_events"] == 1
    assert status["observed_events"] == 2 and status["unaccepted_observed_events"] == 1
    assert status["flushed_events"] == status["events"] == 0


def test_flush_failure_does_not_count_buffered_writes_as_flushed(tmp_path):
    collector = AlpacaL1Capture(["TSLA"], tmp_path)

    class FailedFlush:
        def write(self, line):
            pass

        def flush(self):
            raise OSError("flush failed")

        def close(self):
            pass

    collector._writer_handles[tmp_path / "2026-09-11" / "TSLA.jsonl"] = FailedFlush()
    collector._start_writer()

    async def run():
        await collector.on_quote(Quote())
        await asyncio.to_thread(collector._drain_writer)

    asyncio.run(run())
    status = collector.status()
    assert status["events"] == 1 and status["flushed_events"] == 0
    assert status["status"] == "storage_error" and status["pending_flush_events"] == 1


def test_writer_drain_timeout_reports_pending_without_claiming_success(tmp_path, monkeypatch):
    collector = AlpacaL1Capture(["TSLA"], tmp_path, writer_drain_timeout_seconds=0.05)
    original_append = collector._append
    entered = threading.Event()
    release = threading.Event()

    def blocked_append(event):
        entered.set()
        assert release.wait(timeout=3)
        original_append(event)

    monkeypatch.setattr(collector, "_append", blocked_append)
    collector._start_writer()
    try:
        asyncio.run(collector.on_quote(Quote()))
        assert entered.wait(timeout=1)
        start = time.monotonic()
        assert collector._drain_writer() is False
        assert time.monotonic() - start < 0.5
        status = collector.status()
        assert status["error_type"] == "WriterDrainTimeout" and status["shutdown_incomplete"]
        assert status["pending_flush_events"] == 1 and status["flushed_events"] == 0
    finally:
        release.set()
        collector._writer_thread.join(timeout=2)
    assert not collector._writer_thread.is_alive()


def test_stop_during_backpressure_counts_observed_but_unaccepted_event(tmp_path, monkeypatch):
    collector = AlpacaL1Capture(["TSLA"], tmp_path, writer_queue_capacity=1)
    original_append = collector._append
    entered = threading.Event()
    release = threading.Event()

    def blocked_append(event):
        entered.set()
        assert release.wait(timeout=3)
        original_append(event)

    monkeypatch.setattr(collector, "_append", blocked_append)
    collector._start_writer()

    async def run():
        await collector.on_quote(Quote())
        assert await asyncio.to_thread(entered.wait, 1)
        await collector.on_quote(Quote())
        waiting = asyncio.create_task(collector.on_quote(Quote()))
        await asyncio.sleep(0.01)
        collector.stop()
        with pytest.raises(RuntimeError, match="awaited queue capacity"):
            await asyncio.wait_for(waiting, 1)
        release.set()
        await asyncio.to_thread(collector._drain_writer)

    try:
        asyncio.run(run())
    finally:
        release.set()
        collector._drain_writer()
    status = collector.status()
    assert status["observed_events"] == 3 and status["enqueued_events"] == status["flushed_events"] == 2
    assert status["unaccepted_observed_events"] == 1 and status["shutdown_incomplete"]


@pytest.mark.parametrize("kwargs", [{"writer_queue_capacity": 0}, {"writer_queue_capacity": True},
                                    {"writer_batch_size": 0}, {"writer_batch_size": 1.5}])
def test_writer_buffer_configuration_is_bounded_positive_integer(tmp_path, kwargs):
    with pytest.raises(ValueError, match="positive integer"):
        AlpacaL1Capture(["TSLA"], tmp_path, **kwargs)


def test_loader_hashes_only_requested_files_and_reads_incrementally(tmp_path, monkeypatch):
    import hashlib

    collector = AlpacaL1Capture(["TSLA", "NVDA"], tmp_path)
    asyncio.run(collector.on_quote(Quote()))
    asyncio.run(collector.on_quote({"S": "NVDA", "t": Quote.timestamp,
                                   "bp": 100, "ap": 101, "bs": 10, "as": 10}))
    selected = tmp_path / "2026-09-11" / "TSLA.jsonl"
    other = tmp_path / "2026-09-11" / "NVDA.jsonl"
    manifest = {"status": "complete", "normalized_files": [
        {"path": str(selected.relative_to(tmp_path)), "sha256": hashlib.sha256(selected.read_bytes()).hexdigest()},
        # This hash must be checked when NVDA is queried, not on TSLA queries.
        {"path": str(other.relative_to(tmp_path)), "sha256": "0" * 64},
    ]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("Whole-file byte read is not allowed"))
    original_read_text = Path.read_text

    def read_metadata_only(path, *args, **kwargs):
        assert path.name == "manifest.json", "JSONL must be read incrementally"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_metadata_only)
    assert len(load_real_l1_events(tmp_path, "TSLA", "2026-09-11")) == 1
    with pytest.raises(ValueError, match="integrity"):
        load_real_l1_events(tmp_path, "NVDA", "2026-09-11")
    other.unlink()
    with pytest.raises(ValueError, match="integrity"):
        load_real_l1_events(tmp_path, "TSLA", "2026-09-11")


def test_realtime_status_uses_bounded_tail_and_symbol_session_counts(tmp_path, monkeypatch):
    import app.market_data.alpaca_l1_capture as capture_module

    collector = AlpacaL1Capture(["TSLA", "NVDA"], tmp_path, status_interval_seconds=0)
    for _ in range(5):
        asyncio.run(collector.on_quote(Quote()))
    asyncio.run(collector.on_trade(Trade()))
    asyncio.run(collector.on_quote({"S": "NVDA", "t": Quote.timestamp,
                                   "bp": 100, "ap": 101, "bs": 10, "as": 10}))
    monkeypatch.setattr(capture_module, "load_real_l1_events", lambda *args, **kwargs: pytest.fail("UI must not load all history"))
    status = l1_capture_status(tmp_path, "TSLA", tail_bytes=1600)
    assert status["events"] == 6 and status["quote_events"] == 5 and status["trade_events"] == 1
    assert status["event_count_scope"] == "current_capture_session_symbol"
    assert status["event_time_scope"] == "latest_file_tail_window"
    assert status["latest_quote"]["bid_price"] == Quote.bid_price
    assert status["is_live"] is False


def test_subscribed_empty_capture_reports_waiting_without_inventing_data(tmp_path):
    collector = AlpacaL1Capture(["TSLA"], tmp_path)
    collector._transition("subscribed", subscribed=True, authenticated=True)
    status = l1_capture_status(tmp_path, "TSLA")
    assert status["status"] == "waiting_for_events" and status["success"] is False
    assert status["collector"]["subscribed"] is True
    assert status["collector"]["waiting_for_events"] is True
    assert status["latest_quote"] is None and status["is_live"] is False
    assert l1_capture_status(tmp_path, "NVDA")["status"] == "unavailable"


def test_stale_or_dead_collector_snapshot_never_marks_data_live(tmp_path, monkeypatch):
    import app.market_data.alpaca_l1_capture as capture_module

    collector = AlpacaL1Capture(["TSLA"], tmp_path, status_interval_seconds=0)
    asyncio.run(collector.on_quote({"S": "TSLA", "t": "2020-01-01T00:00:00Z",
                                   "bp": 300, "ap": 301, "bs": 10, "as": 10}))
    collector._transition("subscribed", subscribed=True, authenticated=True)
    assert l1_capture_status(tmp_path, "TSLA")["is_live"] is False  # A newly received old event is still stale.
    asyncio.run(collector.on_quote({"S": "TSLA", "t": pd.Timestamp.now(tz="UTC"),
                                   "bp": 300, "ap": 301, "bs": 10, "as": 10}))
    assert l1_capture_status(tmp_path, "TSLA")["is_live"] is True
    # Stale receipt metadata cannot be treated as a currently streaming feed.
    collector._state["last_event_by_symbol"]["TSLA"]["received_at"] = "2020-01-01T00:00:00+00:00"
    collector._persist_status(force=True)
    assert l1_capture_status(tmp_path, "TSLA")["is_live"] is False
    collector._state["last_event_by_symbol"]["TSLA"]["received_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    collector._persist_status(force=True)

    def absent_process(pid, signal):
        assert signal == 0
        raise ProcessLookupError()

    monkeypatch.setattr(capture_module.os, "kill", absent_process)
    status = l1_capture_status(tmp_path, "TSLA")
    assert status["is_live"] is False and status["collector"]["subscribed"] is False
    assert status["collector"]["process_alive"] is False


def test_orderbook_api_retires_random_l2_response():
    """The public OFI route must never recreate the former random book."""
    source = Path(__file__).resolve().parents[1] / "main_api.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    retired = ast.get_source_segment(source.read_text(encoding="utf-8"), functions["calculate_orderbook_ofi"])
    status = ast.get_source_segment(source.read_text(encoding="utf-8"), functions["get_orderbook_l1_status"])
    assert "np.random" not in retired
    assert "l1_capture_status" in status


def test_public_ml_demo_routes_do_not_emit_synthetic_predictions():
    source = Path(__file__).resolve().parents[1] / "main_api.py"
    text = source.read_text(encoding="utf-8")
    tree = ast.parse(text)
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("get_ml_prediction", "get_ml_model_zoo_predictions", "get_market_regime_hmm", "audit_deflated_sharpe"):
        body = ast.get_source_segment(text, functions[name])
        assert '"status": "unavailable"' in body
        assert "np.random" not in body and "t_seed" not in body
