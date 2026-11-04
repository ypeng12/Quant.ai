"""Synthetic handlers only: never import or start the trading API or runner."""
import ast
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from app.owner_auth import COOKIE_NAME, OwnerSessions, owner_auth_router, SESSION_SECONDS
from app.public_read_only import PublicReadOnlyMiddleware
from app.runtime_status import runtime_capabilities

ORIGIN = "https://example-owner.hf.space"
SECRET = "fixture-only-owner-secret-32-characters-minimum"


def fixture_api(extra=None):
    env = {"SPACE_ID": "example/owner", "SPACE_HOST": "example-owner.hf.space", "QUANT_OWNER_SECRET": SECRET}
    env.update(extra or {})
    clock = [100.0]
    sessions = OwnerSessions(env, clock=lambda: clock[0])
    app = FastAPI()
    app.include_router(owner_auth_router(sessions))
    effects = []

    @app.post("/api/live/start")
    def fake_start():
        effects.append("fixture request")
        return {"success": True}

    @app.get("/api/broker/account")
    def fake_account():
        return {"success": True, "status": "ACTIVE", "is_paper": True}

    @app.get("/api/runtime/capabilities")
    def capabilities(request: Request):
        return runtime_capabilities(env, owner_state=sessions.status(request.scope))

    app.add_middleware(PublicReadOnlyMiddleware, environment=env, owner_auth=sessions)
    return TestClient(app, base_url=ORIGIN), sessions, clock, effects, env


def sign_in(client, secret=SECRET, **kwargs):
    return client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"secret": secret}, **kwargs)


def test_owner_unlock_keeps_get_public_and_requires_explicit_same_origin_action():
    client, _, _, effects, _ = fixture_api()
    assert client.get("/api/broker/account").status_code == 200
    assert client.post("/api/live/start", headers={"Origin": ORIGIN}).status_code == 403
    assert client.get("/api/runtime/capabilities").json()["trading_available"] is False
    login = sign_in(client)
    assert login.status_code == 200 and effects == []
    cookie = login.headers["set-cookie"].lower()
    for flag in ("httponly", "secure", "samesite=strict", "path=/", "max-age=900"):
        assert flag in cookie
    assert "domain=" not in cookie
    assert login.headers["cache-control"] == "no-store"
    assert "token" not in login.json() and SECRET not in login.text
    caps = client.get("/api/runtime/capabilities").json()
    assert caps["mode"] == "owner_authenticated" and caps["trading_available"] is True
    assert caps["account_available"] is True and caps["owner_session_expires_at"]
    assert client.post("/api/live/start", headers={"Origin": ORIGIN}).status_code == 200
    assert effects == ["fixture request"]


@pytest.mark.parametrize("origin", [None, "null", "https://attacker.example", ORIGIN + ".attacker.example", ORIGIN + ":444", "http://example-owner.hf.space"])
def test_session_cannot_bypass_origin_or_host_checks(origin):
    client, _, _, effects, _ = fixture_api()
    assert sign_in(client).status_code == 200
    headers = {"Host": "attacker.example", "X-Forwarded-Host": "attacker.example"}
    if origin is not None:
        headers["Origin"] = origin
    assert client.post("/api/live/start", headers=headers).status_code == 403
    assert client.post("/api/auth/login", headers=headers, json={"secret": SECRET}).status_code == 403
    assert effects == []


def test_cross_site_and_duplicate_origin_cannot_use_owner_session():
    client, _, _, effects, _ = fixture_api()
    assert sign_in(client).status_code == 200
    assert client.post("/api/live/start", headers={"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/live/start", headers=[("Origin", ORIGIN), ("Origin", ORIGIN)]).status_code == 403
    assert effects == []


def test_invalid_missing_and_oversized_secret_never_issue_a_session():
    client, _, _, effects, _ = fixture_api()
    for body in ({"secret": "wrong"}, {"secret": 42}, {}, []):
        response = client.post("/api/auth/login", headers={"Origin": ORIGIN}, json=body)
        assert response.status_code == 401 and "set-cookie" not in response.headers
    response = client.post("/api/auth/login", headers={"Origin": ORIGIN}, content=b"x" * 4097)
    assert response.status_code == 413
    assert effects == []


@pytest.mark.parametrize("config", [{"QUANT_OWNER_SECRET": ""}, {"QUANT_OWNER_SECRET": "too-short"}, {"SPACE_HOST": ""}, {"QUANT_OWNER_ORIGIN": "http://example-owner.hf.space"}])
def test_unconfigured_owner_access_fails_closed(config):
    client, _, _, effects, _ = fixture_api(config)
    assert sign_in(client).status_code == 503
    assert client.get("/api/runtime/capabilities").json()["owner_login_available"] is False
    assert client.post("/api/live/start", headers={"Origin": ORIGIN}).status_code == 403
    assert effects == []


def test_login_throttle_and_expiry_use_server_clock_without_forwarded_ip_bypass():
    client, _, clock, _, _ = fixture_api()
    for _ in range(5):
        assert sign_in(client, "wrong").status_code == 401
    response = client.post("/api/auth/login", headers={"Origin": ORIGIN, "X-Forwarded-For": "new-address"}, json={"secret": SECRET})
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    clock[0] += 301
    assert sign_in(client).status_code == 200
    clock[0] += SESSION_SECONDS
    assert client.get("/api/runtime/capabilities").json()["mode"] == "public_read_only"
    assert client.post("/api/live/start", headers={"Origin": ORIGIN}).status_code == 403


def test_global_throttle_bounds_distributed_attempts():
    _, sessions, clock, _, _ = fixture_api()
    for number in range(30):
        assert sessions.reserve_login_attempt({"client": (str(number), 1)}) == 0
    assert sessions.reserve_login_attempt({"client": ("another", 1)}) > 0
    assert len(sessions._attempts) == 30
    clock[0] += 301
    assert sessions.reserve_login_attempt({"client": ("another", 1)}) == 0
    assert len(sessions._attempts) == 1


def test_invalid_unicode_secret_is_rejected_without_server_error():
    client, _, _, _, _ = fixture_api()
    response = client.post("/api/auth/login", headers={"Origin": ORIGIN},
                           content=b'{"secret":"\\ud800"}')
    assert response.status_code == 401


def test_logout_rotation_and_forged_tokens_revoke_access():
    client, _, _, effects, env = fixture_api()
    assert sign_in(client).status_code == 200
    old_cookie = client.cookies.get(COOKIE_NAME)
    assert sign_in(client).status_code == 200
    assert client.cookies.get(COOKIE_NAME) != old_cookie
    assert client.post("/api/live/start", headers={"Origin": ORIGIN, "Cookie": f"{COOKIE_NAME}={old_cookie}"}).status_code == 403
    assert client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code == 200
    assert client.post("/api/live/start", headers={"Origin": ORIGIN}).status_code == 403
    assert client.post("/api/live/start", headers={"Origin": ORIGIN, "Cookie": f"{COOKIE_NAME}=forged"}).status_code == 403
    assert sign_in(client).status_code == 200
    env["QUANT_OWNER_SECRET"] = SECRET + "rotated"
    assert client.post("/api/live/start", headers={"Origin": ORIGIN}).status_code == 403
    assert effects == []


def test_actual_api_uses_the_same_owner_sessions_for_router_and_middleware():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "main_api.py").read_text())
    middleware = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "add_middleware" and n.args and isinstance(n.args[0], ast.Name)
                  and n.args[0].id == "PublicReadOnlyMiddleware"]
    assert len(middleware) == 1
    assert any(k.arg == "owner_auth" and isinstance(k.value, ast.Name) and k.value.id == "owner_sessions"
               for k in middleware[0].keywords)
    routers = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "owner_auth_router"]
    assert len(routers) == 1 and routers[0].args[0].id == "owner_sessions"
