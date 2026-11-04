"""Real API handlers and runner lifecycle with fake brokers and fake workers.

Only the selected AST nodes are compiled: importing the production application
would construct services and is deliberately avoided. No network or broker
client is used; TestClient's requests stay inside this synthetic application.
"""
import ast
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest

from app.public_read_only import PublicReadOnlyMiddleware
from app.runtime_status import market_clock_view
from test_explicit_execution_startup import stopped_runner
from test_research_execution import runner_type


ORIGIN = "https://example-paper.hf.space"
HEADERS = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PAPER_ENV = {
    "SPACE_ID": "example/paper", "SPACE_HOST": "example-paper.hf.space",
    "QUANT_ONE_CLICK_PAPER": "1", "QUANT_OWNER_ORIGIN": ORIGIN,
    "ALPACA_API_KEY": "fixture-key", "ALPACA_SECRET_KEY": "fixture-secret",
    "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
}


@pytest.fixture
def flow(stopped_runner):
    runner, effects = stopped_runner
    app = FastAPI()
    namespace = {"app": app, "BaseModel": BaseModel, "Optional": Optional,
                 "List": List, "live_runner": runner,
                 "market_clock_view": market_clock_view}
    tree = ast.parse((Path(__file__).resolve().parents[1] / "main_api.py").read_text())
    names = {"LiveStartRequest", "start_live_trading", "stop_live_trading", "get_live_status"}
    nodes = [node for node in tree.body
             if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == names
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, "actual_main_api_lifecycle_handlers", "exec"), namespace)
    environment = dict(PAPER_ENV)
    app.add_middleware(PublicReadOnlyMiddleware, environment=environment)
    with TestClient(app) as client:
        yield client, runner, effects, environment


def test_cookie_free_single_start_and_stop_reach_real_lifecycle(flow):
    client, runner, effects, _ = flow
    assert client.cookies == {}
    # Loading/refreshing the page's status does not create an execution worker.
    before = client.get("/api/live/status").json()
    assert before["status"]["is_running"] is False
    assert effects["threads"] == effects["sync_workers"] == effects["saved_config"] == []

    start = client.post("/api/live/start", json={}, headers=HEADERS)
    assert start.status_code == 200
    assert start.json()["success"] is True
    assert start.json()["status"]["is_running"] is True
    assert runner.is_running
    assert len(effects["threads"]) == len(effects["sync_workers"]) == 1
    assert effects["saved_config"] == [True]
    assert client.cookies == {} and "set-cookie" not in start.headers

    # Repeated browser clicks cannot create a second execution worker.
    repeated = client.post("/api/live/start", json={}, headers=HEADERS)
    assert repeated.json()["success"] is False
    assert repeated.json()["status"]["is_running"] is True
    assert len(effects["threads"]) == len(effects["sync_workers"]) == 1

    stop = client.post("/api/live/stop", headers=HEADERS)
    assert stop.status_code == 200 and stop.json()["success"] is True
    assert stop.json()["status"]["is_running"] is False
    assert effects["saved_config"] == [True, False]
    assert client.get("/api/live/status").json()["status"]["is_running"] is False
    assert client.cookies == {}


def test_disconnected_start_keeps_real_reason_without_running_worker(flow, monkeypatch):
    client, runner, effects, _ = flow
    monkeypatch.setattr(runner, "init_alpaca_adapter", lambda: setattr(
        runner, "_broker_connection", {"connected": False, "reason": "Broker read timed out"}))
    response = client.post("/api/live/start", json={}, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False and body["status"]["is_running"] is False
    assert body["status"]["quant_policy"]["reason"] == "Broker read timed out"
    assert effects["threads"] == effects["sync_workers"] == []


@pytest.mark.parametrize("payload", ["invalid JSON", '{"tickers": "not-a-list"}'])
def test_malformed_request_never_reaches_execution(flow, payload):
    client, _, effects, _ = flow
    response = client.post("/api/live/start", content=payload,
                           headers={**HEADERS, "Content-Type": "application/json"})
    assert response.status_code == 422
    assert effects["threads"] == effects["sync_workers"] == effects["saved_config"] == []


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://other.example"},
                                      {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"}])
def test_other_origin_does_not_reach_real_runner(flow, headers):
    client, _, effects, _ = flow
    assert client.post("/api/live/start", json={}, headers=headers).status_code == 403
    assert effects["threads"] == effects["sync_workers"] == effects["saved_config"] == []


def test_live_configuration_cannot_use_anonymous_paper_start(flow):
    client, _, effects, environment = flow
    environment["ALPACA_BASE_URL"] = "https://api.alpaca.markets"
    assert client.post("/api/live/start", json={}, headers=HEADERS).status_code == 403
    assert effects["threads"] == effects["sync_workers"] == effects["saved_config"] == []
