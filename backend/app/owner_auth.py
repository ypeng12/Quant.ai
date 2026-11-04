"""Short-lived owner sessions for the public website; no broker dependencies.

Set QUANT_OWNER_SECRET to a random secret of at least 32 characters in server
secrets. QUANT_OWNER_ORIGIN may specify the exact HTTPS origin; Hugging Face
otherwise supplies SPACE_HOST. Sessions are process-local and expire on restart.
Use the Space's direct website, not a cross-site embedded frame.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse

COOKIE_NAME = "__Host-quant_owner"
SESSION_SECONDS = 15 * 60
LOGIN_WINDOW_SECONDS = 5 * 60
MAX_PEER_ATTEMPTS = 5
MAX_GLOBAL_ATTEMPTS = 30
MAX_BODY_BYTES = 4096


def _origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            return None
        port = parsed.port
        host = parsed.hostname.lower()
        if any(c.isspace() for c in host) or "," in host:
            return None
        return "https://" + host + (f":{port}" if port and port != 443 else "")
    except ValueError:
        return None


class OwnerSessions:
    def __init__(self, environment: Mapping[str, str] | None = None, *, clock=time.monotonic):
        self.environment = environment
        self.clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, tuple[float, bytes]] = {}
        self._attempts: dict[str, deque] = {}
        self._global_attempts: deque = deque()

    def _env(self):
        return os.environ if self.environment is None else self.environment

    def expected_origin(self) -> str | None:
        env = self._env()
        configured = env.get("QUANT_OWNER_ORIGIN", "")
        if configured:
            return _origin(configured)
        host = env.get("SPACE_HOST", "")
        return _origin("https://" + host) if host else None

    def _secret(self) -> str:
        value = self._env().get("QUANT_OWNER_SECRET", "")
        return value if 32 <= len(value) <= 1024 else ""

    def configured(self) -> bool:
        return bool(self._secret() and self.expected_origin())

    def same_origin(self, scope) -> bool:
        headers = Headers(scope=scope)
        origins = headers.getlist("origin")
        return (len(origins) == 1 and origins[0] == self.expected_origin()
                and headers.get("sec-fetch-site") in (None, "same-origin", "none"))

    def _purge(self, now):
        self._sessions = {key: value for key, value in self._sessions.items() if value[0] > now}
        for peer, attempts in list(self._attempts.items()):
            while attempts and attempts[0] <= now - LOGIN_WINDOW_SECONDS:
                attempts.popleft()
            if not attempts:
                del self._attempts[peer]
        while self._global_attempts and self._global_attempts[0] <= now - LOGIN_WINDOW_SECONDS:
            self._global_attempts.popleft()

    def reserve_login_attempt(self, scope) -> int:
        # Do not trust client-controlled X-Forwarded-For headers. A shared proxy
        # can share this bucket; the global limit also bounds distributed attempts.
        peer = str((scope.get("client") or ("unknown",))[0])
        with self._lock:
            now = self.clock()
            self._purge(now)
            attempts = self._attempts.get(peer, deque())
            full = []
            if len(attempts) >= MAX_PEER_ATTEMPTS:
                full.append(attempts[0])
            if len(self._global_attempts) >= MAX_GLOBAL_ATTEMPTS:
                full.append(self._global_attempts[0])
            if full:
                return max(1, math.ceil(max(full) + LOGIN_WINDOW_SECONDS - now))
            self._attempts.setdefault(peer, attempts).append(now)
            self._global_attempts.append(now)
            return 0

    def verify_secret(self, supplied: str) -> bool:
        expected = self._secret()
        try:
            return bool(expected) and hmac.compare_digest(
                hashlib.sha256(supplied.encode()).digest(), hashlib.sha256(expected.encode()).digest())
        except UnicodeEncodeError:
            return False

    def issue(self) -> str:
        token = secrets.token_urlsafe(32)
        key = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            now = self.clock()
            self._purge(now)
            if len(self._sessions) >= 32:
                del self._sessions[min(self._sessions, key=lambda k: self._sessions[k][0])]
            self._sessions[key] = (now + SESSION_SECONDS, hashlib.sha256(self._secret().encode()).digest())
        return token

    def _token_key(self, scope) -> str:
        token = HTTPConnection(scope).cookies.get(COOKIE_NAME, "")
        return hashlib.sha256(token.encode()).hexdigest() if 1 <= len(token) <= 128 else ""

    def status(self, scope) -> dict:
        with self._lock:
            now = self.clock()
            self._purge(now)
            session = self._sessions.get(self._token_key(scope))
            valid = bool(self.configured() and session and hmac.compare_digest(
                session[1], hashlib.sha256(self._secret().encode()).digest()))
            remaining = max(0, session[0] - now) if valid else 0
        expires = datetime.fromtimestamp(time.time() + remaining, timezone.utc).isoformat() if valid else None
        return {"owner_authenticated": valid, "owner_login_available": self.configured(),
                "owner_session_expires_at": expires}

    def authenticated(self, scope) -> bool:
        return self.status(scope)["owner_authenticated"]

    def revoke(self, scope):
        with self._lock:
            self._sessions.pop(self._token_key(scope), None)


def _response(payload, status_code=200, headers=None):
    return JSONResponse(payload, status_code=status_code,
                        headers={"Cache-Control": "no-store", **(headers or {})})


def owner_auth_router(sessions: OwnerSessions) -> APIRouter:
    router = APIRouter(prefix="/api/auth")

    @router.post("/login")
    async def login(request: Request):
        if not sessions.configured():
            return _response({"detail": "Owner access has not been configured on this server.",
                              "code": "owner_access_unconfigured"}, 503)
        if not sessions.same_origin(request.scope):
            return _response({"detail": "Open the website directly to unlock owner controls.",
                              "code": "origin_rejected"}, 403)
        retry = sessions.reserve_login_attempt(request.scope)
        if retry:
            return _response({"detail": "Too many sign-in attempts. Please wait before trying again.",
                              "code": "login_rate_limited"}, 429, {"Retry-After": str(retry)})
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                return _response({"detail": "Sign-in request is too large."}, 413)
            body.extend(chunk)
        try:
            data = json.loads(body)
            supplied = data.get("secret") if isinstance(data, dict) else None
        except (ValueError, UnicodeDecodeError):
            supplied = None
        if not isinstance(supplied, str) or len(supplied) > 1024 or not sessions.verify_secret(supplied):
            return _response({"detail": "Owner access was not accepted.", "code": "invalid_owner_secret"}, 401)
        sessions.revoke(request.scope)
        response = _response({"success": True, "message": "Owner controls unlocked for this browser."})
        response.set_cookie(COOKIE_NAME, sessions.issue(), max_age=SESSION_SECONDS,
                            secure=True, httponly=True, samesite="strict", path="/")
        return response

    @router.post("/logout")
    async def logout(request: Request):
        if not sessions.same_origin(request.scope):
            return _response({"detail": "A same-origin request is required.", "code": "origin_rejected"}, 403)
        sessions.revoke(request.scope)
        response = _response({"success": True})
        response.delete_cookie(COOKIE_NAME, secure=True, httponly=True, samesite="strict", path="/")
        return response

    return router
