"""Prevent mutation through public research deployments without broker imports."""
from __future__ import annotations

import os
from collections.abc import Mapping

from starlette.responses import JSONResponse


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
READ_ONLY_MESSAGE = (
    "This public deployment is read-only. Trading and other state-changing "
    "API requests are disabled."
)


def public_read_only(environment: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environment is None else environment
    # A public Space cannot opt back into trading with a false/empty override.
    # Local deployments can explicitly enable the same boundary with value 1.
    return "SPACE_ID" in env or env.get("QUANT_PUBLIC_READ_ONLY", "").strip() == "1"


class PublicReadOnlyMiddleware:
    """Deny API mutations before the endpoint can read a body or perform work.

    Register before CORSMiddleware so CORS wraps denied responses as well.
    The policy is intentionally not an authentication scheme for remote control.
    """

    def __init__(self, app, *, environment: Mapping[str, str] | None = None):
        self.app = app
        self.environment = environment

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            is_api = path == "/api" or path.startswith("/api/")
            if is_api and scope.get("method", "").upper() not in SAFE_METHODS and public_read_only(self.environment):
                response = JSONResponse({"detail": READ_ONLY_MESSAGE, "code": "public_read_only"}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
