# backend/app/broker/universe_screener.py
"""
Alpaca Screener & Dynamic Universe Management Module
Fetches real-time market movers and most active stocks via Alpaca SDK / REST API.
"""

import json
import time
from typing import Dict, List

def is_valid_quality_stock_symbol(sym: str) -> bool:
    """Filter out Warrants (W/WS), Rights (R/RT), Units (U/UN/Z), and non-standard 5+ letter symbols."""
    if not sym or not isinstance(sym, str):
        return False
    s = sym.upper().strip()
    if not s.isascii() or not s.replace(".", "").isalnum():
        return False
    if len(s) > 5 or len(s) < 1:
        return False
    # Filter 5-letter warrants/units/rights (e.g. ANSCW, TMCWW, LIDRW, HUBCZ, SRZNW)
    if len(s) == 5:
        if s.endswith(("W", "R", "U", "Z")) or "WS" in s or "RT" in s or "UN" in s:
            return False
    if s.endswith(".W") or s.endswith("-W") or s.endswith("WS") or s.endswith(".U"):
        return False
    return True

def extract_screener_symbols(payload) -> List[str]:
    """Recursively extract stock ticker symbols from Alpaca screener JSON response or SDK objects, excluding warrants and penny derivatives."""
    symbols = []

    def visit(value, depth=0):
        if value is None or depth > 3:
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item, depth + 1)
            return
        if isinstance(value, dict):
            symbol = value.get("symbol")
            if symbol:
                symbols.append(str(symbol).upper())
            for key in ("most_actives", "gainers", "losers", "data"):
                if key in value:
                    visit(value[key], depth + 1)
            return
        symbol = getattr(value, "symbol", None)
        if symbol:
            symbols.append(str(symbol).upper())
        for attr in ("most_actives", "gainers", "losers", "data"):
            if hasattr(value, attr):
                visit(getattr(value, attr), depth + 1)

    visit(payload)
    return list(dict.fromkeys(sym for sym in symbols if is_valid_quality_stock_symbol(sym)))


def fetch_screener_via_rest(get_credentials_func, active_count: int, mover_count: int) -> List[str]:
    """Standard-library fallback for deployments that use REST API directly."""
    import urllib.parse
    import urllib.request

    api_key, api_secret, _base_url = get_credentials_func()
    if not api_key or not api_secret or "your_" in str(api_key).lower():
        raise RuntimeError("Alpaca market-data credentials are not configured")
    headers = {
        "APCA-API-KEY-ID": str(api_key),
        "APCA-API-SECRET-KEY": str(api_secret),
        "Accept": "application/json",
    }
    endpoints = (
        "https://data.alpaca.markets/v1beta1/screener/stocks/movers?"
        + urllib.parse.urlencode({"top": mover_count}),
        "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives?"
        + urllib.parse.urlencode({"top": active_count, "by": "volume"}),
    )
    symbols = []
    for url in endpoints:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=4.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        symbols.extend(extract_screener_symbols(payload))
    return list(dict.fromkeys(symbols))

class UniverseScreener:
    def __init__(self, get_credentials_func, log_func=None):
        self.get_credentials = get_credentials_func
        self.add_log = log_func or print
        self._screener_symbols = []
        self._screener_refreshed_at = 0.0
        self._screener_last_error_at = 0.0

    def refresh_intraday_universe(
        self,
        user_watchlist: List[str],
        active_pos_tickers,
        strategy_params: Dict,
        ticker_scores: Dict
    ) -> List[str]:
        if not strategy_params.get("dynamic_screener_enabled", True):
            return list(dict.fromkeys(user_watchlist + list(active_pos_tickers)))

        now = time.time()
        refresh_seconds = max(60.0, float(strategy_params.get("screener_refresh_seconds", 120.0)))
        if now - self._screener_refreshed_at >= refresh_seconds:
            active_count = int(strategy_params.get("screener_top_actives", 6))
            mover_count = int(strategy_params.get("screener_top_movers", 4))
            try:
                from alpaca.data.historical.screener import ScreenerClient
                from alpaca.data.requests import MarketMoversRequest, MostActivesRequest

                api_key, api_secret, _base_url = self.get_credentials()
                client = ScreenerClient(api_key=api_key, secret_key=api_secret)
                active_payload = client.get_most_actives(MostActivesRequest(top=active_count))
                mover_payload = client.get_market_movers(MarketMoversRequest(top=mover_count))
                self._screener_symbols = list(dict.fromkeys(
                    extract_screener_symbols(mover_payload)
                    + extract_screener_symbols(active_payload)
                ))
                self._screener_refreshed_at = now
            except Exception as sdk_exc:
                try:
                    self._screener_symbols = fetch_screener_via_rest(self.get_credentials, active_count, mover_count)
                    self._screener_refreshed_at = now
                except Exception as rest_exc:
                    if now - self._screener_last_error_at >= 900.0:
                        self.add_log(
                            f"⚠️ [日内动态选股降级] Alpaca Screener 暂不可用，继续使用 Watchlist: "
                            f"SDK={sdk_exc}; REST={rest_exc}"
                        )
                        self._screener_last_error_at = now
                    self._screener_refreshed_at = now

        candidates = list(dict.fromkeys(user_watchlist + list(active_pos_tickers) + self._screener_symbols))
        positions = set(active_pos_tickers)
        max_scan = max(len(positions), int(strategy_params.get("max_scan_symbols", 14)))
        candidates.sort(
            key=lambda sym: (sym in positions, ticker_scores.get(sym, 0.0)),
            reverse=True,
        )
        return candidates[:max_scan]

    def preload_premarket_catalysts(self, user_watchlist: List[str]) -> List[str]:
        """
        Pre-market catalyst pre-loader (9:15 - 9:30 EST):
        Fetches top movers & most active tickers ahead of bell so they are queued in active_tickers at 9:30:00.
        """
        try:
            active_count = 6
            mover_count = 4
            api_key, api_secret, _base_url = self.get_credentials()
            if api_key and api_secret and "your_" not in str(api_key).lower():
                try:
                    from alpaca.data.historical.screener import ScreenerClient
                    from alpaca.data.requests import MarketMoversRequest, MostActivesRequest
                    client = ScreenerClient(api_key=api_key, secret_key=api_secret)
                    active_payload = client.get_most_actives(MostActivesRequest(top=active_count))
                    mover_payload = client.get_market_movers(MarketMoversRequest(top=mover_count))
                    symbols = extract_screener_symbols(mover_payload) + extract_screener_symbols(active_payload)
                except Exception:
                    symbols = fetch_screener_via_rest(self.get_credentials, active_count, mover_count)
                
                if symbols:
                    self._screener_symbols = list(dict.fromkeys(symbols))
                    self._screener_refreshed_at = time.time()
                    combined = list(dict.fromkeys(self._screener_symbols + user_watchlist))
                    self.add_log(f"🔥 [盘前热点预加载完成] 已将 {len(self._screener_symbols)} 支爆破潜质异动股优先载入开盘监控队列: {self._screener_symbols[:6]}")
                    return combined
        except Exception as e:
            self.add_log(f"⚠️ [盘前预加载提示] 暂使用标准 Watchlist 预热 ({e})")
        return list(dict.fromkeys(user_watchlist))

