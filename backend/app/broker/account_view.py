"""Optional account display credentials; this module only performs broker reads.

ALPACA_ACCOUNT_* credentials are independent of the automatic trading runner.
No account response or credential is written to disk by this module.
"""
import os
import threading
import time
from functools import lru_cache

from .alpaca_adapter import AlpacaAdapter


class AccountView:
    def __init__(self, key, secret, endpoint):
        self.adapter = AlpacaAdapter(key, secret, endpoint)
        self.cache = {}
        self.lock = threading.Lock()

    def read(self, resource, period="1M", timeframe=None):
        cache_key = (resource, period, timeframe)
        with self.lock:
            cached = self.cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < 5:
                return cached[1]
            if resource == "account":
                result = self.adapter.get_account_summary()
            elif resource == "positions":
                positions = self.adapter.client.get_all_positions()
                result = {"success": True, "positions": [dict(
                    ticker=p.symbol, shares=float(p.qty), avg_entry_price=float(p.avg_entry_price),
                    market_value=float(p.market_value), current_price=float(p.current_price),
                    unrealized_pnl=float(p.unrealized_pl),
                    unrealized_pnl_pct=float(p.unrealized_plpc) * 100,
                ) for p in positions]}
            elif resource == "history":
                result = self.adapter.get_portfolio_history(period, timeframe)
            else:
                raise ValueError("Unknown account display resource")
            if result.get("success"):
                self.cache[cache_key] = (time.monotonic(), result)
            return result


@lru_cache(maxsize=1)
def _view(key, secret, endpoint):
    return AccountView(key, secret, endpoint)


def read_configured_account_view(resource, period="1M", timeframe=None):
    """None means unconfigured; a failed configured account never falls back."""
    key = os.getenv("ALPACA_ACCOUNT_API_KEY", "")
    secret = os.getenv("ALPACA_ACCOUNT_SECRET_KEY", "")
    if not key and not secret:
        return None
    endpoint = os.getenv("ALPACA_ACCOUNT_BASE_URL", "https://paper-api.alpaca.markets")
    allowed = {"https://paper-api.alpaca.markets", "https://api.alpaca.markets"}
    endpoint = endpoint.removesuffix("/").removesuffix("/v2")
    unavailable = {"success": False, "status": "unavailable", "positions": None,
                   "error": "The configured account display connection could not be read."}
    if not key or not secret or endpoint not in allowed:
        return unavailable
    try:
        return _view(key, secret, endpoint).read(resource, period, timeframe)
    except Exception:
        return unavailable
