# backend/app/broker/risk_position_sizer.py
"""
Risk Management & Position Sizing Module
Handles entry/exit TTL concurrency locks, shortability checks, and buying-power position sizing.
"""

import math
import time
from typing import Dict, Optional

class RiskPositionSizer:
    def __init__(self):
        self.pending_entry_locks = {}  # {ticker: timestamp} 60s TTL
        self.pending_exit_locks = {}   # {ticker: timestamp} 60s TTL
        self._asset_shortability_cache = {}

    def is_entry_locked(self, ticker: str) -> bool:
        now = time.time()
        t = self.pending_entry_locks.get(ticker)
        if t and (now - t < 60):
            return True
        elif t:
            self.pending_entry_locks.pop(ticker, None)
        return False

    def is_exit_locked(self, ticker: str) -> bool:
        now = time.time()
        t = self.pending_exit_locks.get(ticker)
        if t and (now - t < 60):
            return True
        elif t:
            self.pending_exit_locks.pop(ticker, None)
        return False

    def lock_entry(self, ticker: str):
        self.pending_entry_locks[ticker] = time.time()

    def unlock_entry(self, ticker: str):
        self.pending_entry_locks.pop(ticker, None)

    def lock_exit(self, ticker: str):
        self.pending_exit_locks[ticker] = time.time()

    def unlock_exit(self, ticker: str):
        self.pending_exit_locks.pop(ticker, None)

    def can_open_short(self, ticker: str, adapter) -> bool:
        now = time.time()
        cached = self._asset_shortability_cache.get(ticker)
        if cached and now - cached[0] < 600.0:
            return cached[1]
        try:
            client = None
            if hasattr(adapter, "get_asset"):
                client = adapter
            else:
                for attr in ("trading_client", "client", "api"):
                    candidate = getattr(adapter, attr, None)
                    if candidate is not None and hasattr(candidate, "get_asset"):
                        client = candidate
                        break
            if client is None:
                return True
            asset = client.get_asset(ticker)
            get_value = (lambda key, default=None: asset.get(key, default)) if isinstance(asset, dict) else (lambda key, default=None: getattr(asset, key, default))
            shortable = bool(get_value("shortable", False))
            easy_to_borrow = bool(get_value("easy_to_borrow", False))
            borrow_status = str(get_value("borrow_status", "")).lower()
            allowed = shortable and (easy_to_borrow or borrow_status not in ("hard_to_borrow", "htb"))
            self._asset_shortability_cache[ticker] = (now, allowed)
            return allowed
        except Exception:
            return True

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) else float(default)
        except (TypeError, ValueError):
            return float(default)

    def size_aggressive_entry(
        self,
        account: Dict,
        close_price: float,
        opportunity: Dict,
        strategy_params: Dict,
        prob_eval: Optional[Dict] = None
    ) -> Dict:
        equity = max(0.0, self._safe_float(account.get("equity"), account.get("portfolio_value", 0.0)))
        cash = max(0.0, self._safe_float(account.get("cash"), 0.0))
        multiplier = max(1.0, self._safe_float(account.get("multiplier"), 1.0))
        # Live dynamic buying power returned from Alpaca API
        available_bp = max(0.0, self._safe_float(account.get("buying_power"), cash * multiplier))
        score = self._safe_float(opportunity.get("score"), 0.0)
        min_score = self._safe_float(strategy_params.get("entry_score_min"), 78.0)
        full_score = max(min_score + 1.0, self._safe_float(strategy_params.get("full_size_score"), 90.0))
        starter = self._safe_float(strategy_params.get("starter_buying_power_pct"), 0.35)
        maximum = self._safe_float(strategy_params.get("max_position_buying_power_pct"), 0.95)
        strength = min(1.0, max(0.0, (score - min_score) / (full_score - min_score)))
        bp_fraction = min(maximum, starter + (maximum - starter) * strength)

        # Kelly Criterion adjustment if probability evaluation is available
        if prob_eval and prob_eval.get("kelly_fraction", 0.0) > 0:
            kelly_f = prob_eval["kelly_fraction"]
            bp_fraction = min(maximum, bp_fraction * min(1.3, max(0.8, kelly_f * 2.0)))

        utilization = self._safe_float(strategy_params.get("buying_power_utilization_pct"), 0.95)
        notional = available_bp * min(utilization, bp_fraction)
        stop_pct = max(0.001, self._safe_float(opportunity.get("_stop_pct"), 0.0100))
        risk_budget = equity * self._safe_float(strategy_params.get("max_position_risk_pct"), 0.040)
        shares = int(notional / close_price) if close_price > 0 else 0
        # High-price stock protection (e.g. SNDK > $500/sh): ensure at least 1 share if buying power permits
        if shares == 0 and close_price > 500.0 and available_bp >= close_price * 0.9:
            shares = 1

        return {
            "shares": shares,
            "notional": shares * close_price,
            "available_buying_power": available_bp,
            "buying_power_fraction": bp_fraction,
            "risk_budget": risk_budget,
            "stop_pct": stop_pct,
        }

    def size_probe_entry(
        self,
        account: Dict,
        close_price: float,
        opportunity: Dict,
        strategy_params: Dict,
        prob_eval: Optional[Dict] = None
    ) -> Dict:
        """
        Calculates position sizing for Early Probe Entry (试探建仓).
        Allocates a starter fraction (25%) of target buying power so the algorithm can enter
        early before major momentum spikes, securing better cost basis.
        """
        equity = max(0.0, self._safe_float(account.get("equity"), account.get("portfolio_value", 0.0)))
        cash = max(0.0, self._safe_float(account.get("cash"), 0.0))
        multiplier = max(1.0, self._safe_float(account.get("multiplier"), 1.0))
        available_bp = max(0.0, self._safe_float(account.get("buying_power"), cash * multiplier))
        probe_bp_pct = self._safe_float(strategy_params.get("starter_buying_power_pct"), 0.25)
        utilization = self._safe_float(strategy_params.get("buying_power_utilization_pct"), 0.95)
        notional = available_bp * min(utilization, probe_bp_pct)
        stop_pct = max(0.001, self._safe_float(opportunity.get("_stop_pct"), 0.0100))
        shares = int(notional / close_price) if close_price > 0 else 0
        # High-price stock protection (e.g. SNDK > $500/sh): ensure at least 1 share if buying power permits
        if shares == 0 and close_price > 500.0 and available_bp >= close_price * 0.9:
            shares = 1

        return {
            "shares": shares,
            "notional": shares * close_price,
            "available_buying_power": available_bp,
            "buying_power_fraction": probe_bp_pct,
            "stop_pct": stop_pct,
            "is_probe": True,
        }

    def size_pyramid_entry(
        self,
        account: Dict,
        close_price: float,
        opportunity: Dict,
        strategy_params: Dict,
        prob_eval: Optional[Dict] = None
    ) -> Dict:
        """
        Calculates position sizing for Pyramiding / Adding to winning positions (加仓/补仓).
        Allocates a portion of remaining available buying power.
        """
        equity = max(0.0, self._safe_float(account.get("equity"), account.get("portfolio_value", 0.0)))
        cash = max(0.0, self._safe_float(account.get("cash"), 0.0))
        multiplier = max(1.0, self._safe_float(account.get("multiplier"), 1.0))
        available_bp = max(0.0, self._safe_float(account.get("buying_power"), cash * multiplier))
        pyramid_bp_pct = self._safe_float(strategy_params.get("starter_buying_power_pct"), 0.35)
        utilization = self._safe_float(strategy_params.get("buying_power_utilization_pct"), 0.95)
        notional = available_bp * min(utilization, pyramid_bp_pct)
        stop_pct = max(0.001, self._safe_float(opportunity.get("_stop_pct"), 0.0100))
        shares = int(notional / close_price) if close_price > 0 else 0

        return {
            "shares": shares,
            "notional": shares * close_price,
            "available_buying_power": available_bp,
            "buying_power_fraction": pyramid_bp_pct,
            "stop_pct": stop_pct,
        }


