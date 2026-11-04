"""Prevent mutation through public research deployments without broker imports."""
from __future__ import annotations

import os
from collections.abc import Mapping

from starlette.responses import JSONResponse
from .owner_auth import OwnerSessions


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
READ_ONLY_MESSAGE = (
    "Owner sign-in is required to use trading controls on this public website."
)


def public_read_only(environment: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environment is None else environment
    # A public Space cannot opt back into trading with a false/empty override.
    # Local deployments can explicitly enable the same boundary with value 1.
    return "SPACE_ID" in env or env.get("QUANT_PUBLIC_READ_ONLY", "").strip() == "1"


class PublicReadOnlyMiddleware:
    """Deny API mutations before the endpoint can read a body or perform work.

    Register before CORSMiddleware so CORS wraps denied responses as well.
    Anonymous requests remain read-only; a short-lived owner session additionally
    requires a server-verified same-origin request for every mutation.
    """

    def __init__(self, app, *, environment: Mapping[str, str] | None = None,
                 owner_auth: OwnerSessions | None = None):
        self.app = app
        self.environment = environment
        self.owner_auth = owner_auth or OwnerSessions(environment)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            is_api = path == "/api" or path.startswith("/api/")
            if is_api and scope.get("method", "").upper() not in SAFE_METHODS and public_read_only(self.environment):
                # These handlers enforce origin, body limits and login throttling.
                auth_route = scope.get("method") == "POST" and path in ("/api/auth/login", "/api/auth/logout")
                if auth_route or (self.owner_auth.authenticated(scope) and self.owner_auth.same_origin(scope)):
                    await self.app(scope, receive, send)
                    return
                response = JSONResponse({"detail": READ_ONLY_MESSAGE, "code": "public_read_only"}, status_code=403,
                                        headers={"Cache-Control": "no-store"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
