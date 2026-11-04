"""Explicit deployment opt-in for keyless, same-origin paper controls.

This module resolves configuration only; it never contacts a broker or starts
execution. The server owner opts in, and no live credential family qualifies.
"""
from collections.abc import Mapping
import os

from .broker.credentials import CredentialConfigurationError, resolve_trading_credentials
from .owner_auth import OwnerSessions


PAPER_CONTROL_PATHS = frozenset({
    "/api/live/start", "/api/live/stop", "/api/live/toggle",
    "/api/live/watchlist/sync", "/api/live/market_mode",
    "/api/live/extended_hours_order", "/api/live/close_position",
    "/api/broker/limit_order", "/api/broker/cancel_orders", "/api/broker/close_positions",
    "/api/watchlist/update", "/api/watchlist/save", "/api/watchlist/reset",
})


def paper_controls_enabled(environment: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environment is None else environment
    if env.get("QUANT_ONE_CLICK_PAPER", "").strip() != "1":
        return False
    try:
        credentials = resolve_trading_credentials(env)
        return bool(credentials and credentials.is_paper and OwnerSessions(env).expected_origin())
    except (CredentialConfigurationError, TypeError, ValueError):
        return False


def paper_control_request(scope, environment=None, *, origins=None) -> bool:
    if (scope.get("method") != "POST" or scope.get("path") not in PAPER_CONTROL_PATHS
            or not paper_controls_enabled(environment)):
        return False
    return (origins or OwnerSessions(environment)).same_origin(scope)


def connected_paper_adapter(runner):
    """Use the same verified execution account for explicit cancel/close actions."""
    connection = getattr(runner, "_broker_connection", {})
    adapter = getattr(runner, "adapter", None)
    if (connection.get("connected") is not True or connection.get("is_paper") is not True
            or getattr(adapter, "is_paper", None) is not True):
        raise ValueError("Paper execution account is not connected")
    return adapter
