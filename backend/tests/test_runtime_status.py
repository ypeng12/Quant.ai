"""Status presentation must not infer market closure from missing observations."""
import pytest
from datetime import datetime, timezone

from app.runtime_status import market_clock_view, runtime_capabilities


@pytest.mark.parametrize("clock", [None, {}, {"success": False, "is_open": False}, {"success": True}])
def test_missing_clock_is_unknown_instead_of_market_closed(clock):
    view = market_clock_view(clock, now=datetime(2026, 11, 4, 17, 0, 30, tzinfo=timezone.utc))
    assert view["is_market_open"] is None
    assert view["market_status_available"] is False


@pytest.mark.parametrize("is_open", [True, False])
def test_verified_open_and_closed_observations_remain_distinct(is_open):
    clock = {"success": True, "is_open": is_open, "timestamp": "2026-11-04T12:00:00-05:00"}
    view = market_clock_view(clock, now=datetime(2026, 11, 4, 17, 0, 30, tzinfo=timezone.utc))
    assert view["is_market_open"] is is_open
    assert view["market_status_available"] is True
    assert view["market_clock_observed_at"] == clock["timestamp"]


@pytest.mark.parametrize("timestamp", [None, "invalid", "2026-11-04T17:00:00", "2026-11-03T17:00:00Z", "2026-11-05T17:00:00Z"])
def test_unverified_or_stale_clock_cannot_claim_current_market_state(timestamp):
    view = market_clock_view({"success": True, "is_open": False, "timestamp": timestamp},
                             now=datetime(2026, 11, 4, 17, 0, 30, tzinfo=timezone.utc))
    assert view["is_market_open"] is None
    assert view["market_status_available"] is False


def test_public_capability_preserves_account_reads_without_advertising_start():
    view = runtime_capabilities({"SPACE_ID": "owner/project", "QUANT_PUBLIC_READ_ONLY": "0"})
    assert view["mode"] == "public_read_only"
    assert view["account_available"] is True
    assert view["trading_available"] is False
    assert view["market_status_available"] is False


def test_local_capability_keeps_existing_trading_control_available():
    view = runtime_capabilities({})
    assert view["mode"] == "local"
    assert view["trading_available"] is True
