"""Describe runtime capabilities and observed clock data without broker calls."""
from collections.abc import Mapping
from datetime import datetime, timezone

from .public_read_only import public_read_only
from .paper_controls import paper_controls_enabled


def market_clock_view(clock: Mapping | None = None, *, now: datetime | None = None) -> dict:
    clock = clock or {}
    observed_at = clock.get("timestamp")
    try:
        observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
        age = ((now or datetime.now(timezone.utc)) - observed).total_seconds()
        # Display freshness only: never reuse yesterday's stopped-runner clock.
        # This does not alter the runner's clock or any execution decision.
        fresh = 0 <= age <= 60
    except (TypeError, ValueError):
        fresh = False
    available = fresh and clock.get("success") is True and type(clock.get("is_open")) is bool
    return {
        "is_market_open": clock["is_open"] if available else None,
        "market_status_available": available,
        "market_clock_observed_at": observed_at,
    }


def runtime_capabilities(environment: Mapping[str, str] | None = None, clock: Mapping | None = None,
                         owner_state: Mapping | None = None) -> dict:
    read_only = public_read_only(environment)
    paper = paper_controls_enabled(environment)
    owner_state = owner_state or {}
    owner = not paper and read_only and owner_state.get("owner_authenticated") is True
    return {
        "mode": "paper" if paper else "owner_authenticated" if owner else "public_read_only" if read_only else "local",
        "trading_available": paper or not read_only or owner,
        "owner_authenticated": owner,
        "owner_login_available": not paper and read_only and owner_state.get("owner_login_available") is True,
        "owner_session_expires_at": owner_state.get("owner_session_expires_at") if owner else None,
        # These describe available API features, not successful authentication.
        "account_available": True,
        "market_status_available": market_clock_view(clock)["market_status_available"],
        "message": (
            "Paper trading controls are ready." if paper else
            "Owner controls are unlocked for this browser. Use Start AI Bot to request execution." if owner else
            "Public view: account and research data are available. Sign in as the owner to use trading controls."
            if read_only else "Local trading controls are available. Account and execution status are reported separately."
        ),
    }
