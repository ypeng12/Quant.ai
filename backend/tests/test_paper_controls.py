"""No brokerage calls: deployment policy and one-click HTTP behavior only."""
import ast
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.paper_controls import (PAPER_CONTROL_PATHS, connected_paper_adapter,
                                paper_controls_enabled)
from app.public_read_only import PublicReadOnlyMiddleware
from app.runtime_status import runtime_capabilities


ORIGIN = "https://example-paper.hf.space"


def environment(**updates):
    return {"SPACE_ID": "example/paper", "SPACE_HOST": "example-paper.hf.space",
            "QUANT_ONE_CLICK_PAPER": "1", "ALPACA_API_KEY": "fixture-key",
            "ALPACA_SECRET_KEY": "fixture-secret",
            "ALPACA_BASE_URL": "https://paper-api.alpaca.markets", **updates}


def fake_client(env):
    app, effects = FastAPI(), []
    for path in (*PAPER_CONTROL_PATHS, "/api/live/sync_hf", "/api/agent/execute"):
        def handler(path=path):
            effects.append(path)
            return {"success": True}
        app.add_api_route(path, handler, methods=["POST", "PUT", "DELETE"])
    app.add_middleware(PublicReadOnlyMiddleware, environment=env)
    return TestClient(app, base_url=ORIGIN), effects


def test_all_existing_paper_controls_need_only_one_same_origin_post():
    client, effects = fake_client(environment())
    # A request made by the app inside HF's frame has the app's origin; unlike
    # owner cookies, it does not depend on third-party cookie acceptance.
    for path in PAPER_CONTROL_PATHS:
        response = client.post(path, headers={"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"})
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert not response.headers.get("set-cookie")
    assert set(effects) == PAPER_CONTROL_PATHS
    assert not client.cookies


@pytest.mark.parametrize("headers", [
    {}, {"Origin": "https://other.example"}, {"Origin": "null"},
    {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"},
    {"Origin": ORIGIN + ".other.example"},
])
def test_unrelated_origins_do_not_reach_paper_handlers(headers):
    client, effects = fake_client(environment())
    assert client.post("/api/live/start", headers=headers).status_code == 403
    assert effects == []


@pytest.mark.parametrize("updates", [
    {"QUANT_ONE_CLICK_PAPER": "0"},
    {"ALPACA_BASE_URL": "https://api.alpaca.markets"},
    {"ALPACA_SECRET_KEY": ""},
    {"ALPACA_API_KEY": "", "ALPACA_SECRET_KEY": ""},
    {"SPACE_HOST": "", "QUANT_OWNER_ORIGIN": ""},
    {"APCA_API_KEY_ID": "fixture-live", "APCA_API_SECRET_KEY": "fixture-live-secret",
     "APCA_API_BASE_URL": "https://api.alpaca.markets"},
])
def test_opt_in_never_promotes_missing_incomplete_or_live_execution(updates):
    env = environment(**updates)
    client, effects = fake_client(env)
    assert not paper_controls_enabled(env)
    assert runtime_capabilities(env)["mode"] == "public_read_only"
    assert client.post("/api/live/start", headers={"Origin": ORIGIN}).status_code == 403
    assert effects == []


def test_account_paper_fallback_and_capabilities_need_no_owner_key_or_account_read():
    env = environment(ALPACA_API_KEY="", ALPACA_SECRET_KEY="",
                      ALPACA_ACCOUNT_API_KEY="fixture-account",
                      ALPACA_ACCOUNT_SECRET_KEY="fixture-account-secret")
    assert paper_controls_enabled(env)
    view = runtime_capabilities(env, owner_state={"owner_authenticated": True,
                                                "owner_login_available": True})
    assert view["mode"] == "paper" and view["trading_available"] is True
    assert view["owner_login_available"] is False
    assert view["owner_session_expires_at"] is None
    assert "fixture" not in str(view)


def test_other_mutations_and_wrong_methods_keep_the_existing_owner_boundary():
    client, effects = fake_client(environment())
    for path in ("/api/live/sync_hf", "/api/agent/execute"):
        assert client.post(path, headers={"Origin": ORIGIN}).status_code == 403
    for method in ("PUT", "DELETE"):
        assert client.request(method, "/api/live/start", headers={"Origin": ORIGIN}).status_code == 403
    assert effects == []


@pytest.mark.parametrize("connection,adapter_paper", [
    ({"connected": False, "is_paper": True}, True),
    ({"connected": True, "is_paper": False}, False),
    ({"connected": True, "is_paper": True}, False),
    ({}, None),
])
def test_explicit_cancel_close_never_pick_an_unverified_or_live_adapter(connection, adapter_paper):
    runner = SimpleNamespace(_broker_connection=connection,
                             adapter=SimpleNamespace(is_paper=adapter_paper))
    with pytest.raises(ValueError, match="Paper execution account"):
        connected_paper_adapter(runner)


def test_actual_cancel_close_routes_use_same_paper_execution_adapter_without_constructing_another():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "main_api.py").read_text())
    routes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name in {"cancel_all_orders", "close_all_positions"}]
    effects = []
    adapter = SimpleNamespace(is_paper=True,
        cancel_all_orders=lambda: effects.append("cancel") or {"success": True},
        close_all_positions=lambda: effects.append("close") or {"success": True})
    runner = SimpleNamespace(adapter=adapter,
        _broker_connection={"connected": True, "is_paper": True}, add_log=lambda message: None)
    assert connected_paper_adapter(runner) is adapter
    # Remove imports so no config loader, broker SDK or real client is executed.
    for route in routes:
        route.decorator_list = []
        route.body = [node for node in route.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    def forbidden_client(*args):
        pytest.fail("A second account adapter must not be created")
    mixed_config = environment(APCA_API_KEY_ID="fixture-paper",
        APCA_API_SECRET_KEY="fixture-paper-secret", APCA_API_BASE_URL="https://paper-api.alpaca.markets",
        ALPACA_BASE_URL="https://api.alpaca.markets")
    assert paper_controls_enabled(mixed_config)
    namespace = {"live_runner": runner, "paper_controls_enabled": lambda: paper_controls_enabled(mixed_config),
                 "connected_paper_adapter": connected_paper_adapter,
                 "AlpacaAdapter": forbidden_client}
    exec(compile(ast.fix_missing_locations(ast.Module(body=routes, type_ignores=[])),
                 "actual_cancel_close_routes", "exec"), namespace)
    assert namespace["cancel_all_orders"]()["success"] is True
    assert namespace["close_all_positions"]()["success"] is True
    assert effects == ["cancel", "cancel", "close"]


def test_spa_entry_reloads_current_bundle_but_keeps_static_asset_headers(tmp_path):
    import asyncio
    import os
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    (tmp_path / "index.html").write_text("current entry")
    (tmp_path / "bundle-hash.js").write_text("current bundle")
    tree = ast.parse((Path(__file__).resolve().parents[1] / "main_api.py").read_text())
    route = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                 and node.name == "serve_spa")
    route.decorator_list = []
    namespace = {"os": os, "_dist_dir": str(tmp_path), "FileResponse": FileResponse,
                 "HTTPException": HTTPException}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[route], type_ignores=[])),
                 "actual_spa_route", "exec"), namespace)
    for path in ("", "index.html", "account"):
        response = asyncio.run(namespace["serve_spa"](path))
        assert "no-store" in response.headers["cache-control"]
    static = asyncio.run(namespace["serve_spa"]("bundle-hash.js"))
    assert "cache-control" not in static.headers
