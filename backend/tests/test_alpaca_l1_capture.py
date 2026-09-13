import asyncio
import ast
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.market_data.alpaca_l1_capture import AlpacaL1Capture, l1_capture_status, load_real_l1_quotes, real_l1_to_five_minute


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
