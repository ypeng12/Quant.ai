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
        """
        Calculates disciplined institutional position sizing for initial entries.
        Enforces:
        1. Hard cap on max single position notional (max 20%~25% of Portfolio Equity, ~$11k~$14k for $57k account).
        2. Hard cap on max portfolio risk per trade (max 0.8%~1.0% equity risk = $450~$570 max loss).
        3. High-price stock safety guardrails (SNDK > $1000/sh restricted to prudent share count).
        4. Strict check against unconstrained 4x margin buying power.
        """
        equity = max(0.0, self._safe_float(account.get("equity"), account.get("portfolio_value", 58000.0)))
        cash = max(0.0, self._safe_float(account.get("cash"), 0.0))
        multiplier = max(1.0, self._safe_float(account.get("multiplier"), 1.0))
        available_bp = max(0.0, self._safe_float(account.get("buying_power"), cash * multiplier))
        
        # Hard ceiling on single stock equity exposure (default 20% of net equity)
        max_eq_pct = min(0.25, self._safe_float(strategy_params.get("max_single_position_equity_pct"), 0.20))
        max_position_notional = equity * max_eq_pct
        
        # ML Win Probability & Conviction Sizing (Base allocation 15% ~ 20% of equity)
        score = self._safe_float(opportunity.get("score"), 50.0)
        p_win = self._safe_float(opportunity.get("win_probability", prob_eval.get("win_probability", 0.50) if prob_eval else 0.50), 0.50)
        starter_pct = min(0.25, self._safe_float(strategy_params.get("starter_buying_power_pct"), 0.20))
        
        eq_fraction = max(0.12, min(max_eq_pct, p_win * starter_pct * 1.5))
        target_notional = equity * eq_fraction
        
        # Constraint 1: Account Buying Power cap
        utilization = min(0.85, self._safe_float(strategy_params.get("buying_power_utilization_pct"), 0.80))
        final_notional = min(target_notional, max_position_notional, available_bp * utilization)
        
        # Constraint 2: Risk Budget Cap (Max 1.0% portfolio risk per trade = ~$570 max loss)
        stop_pct = max(0.006, self._safe_float(opportunity.get("_stop_pct"), 0.0100))
        max_risk_pct = min(0.015, self._safe_float(strategy_params.get("max_trade_risk_pct"), 0.010))
        max_risk_dollars = equity * max_risk_pct
        risk_constrained_notional = (max_risk_dollars / stop_pct) if stop_pct > 0 else final_notional
        
        final_notional = min(final_notional, risk_constrained_notional)
        shares = int(final_notional / close_price) if close_price > 0 else 0
        
        # Extra Guardrail for Ultra-High-Price Stocks (e.g. SNDK > $1000/sh):
        # A single 1% fluctuation is $15+/share. Hard cap max shares to never exceed 8 shares.
        if close_price >= 1000.0:
            shares = min(shares, int(max_position_notional / close_price), 8)
        elif close_price >= 500.0:
            shares = min(shares, int(max_position_notional / close_price), 20)
            
        # Ensure at least 1 share if affordable within risk budget
        if shares == 0 and close_price > 0 and available_bp >= close_price and (close_price * stop_pct <= max_risk_dollars * 1.2):
            shares = 1

        return {
            "shares": shares,
            "notional": shares * close_price,
            "available_buying_power": available_bp,
            "buying_power_fraction": final_notional / equity if equity > 0 else starter_pct,
            "risk_budget": max_risk_dollars,
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
        Allocates a small starter fraction (10% of equity) so the algorithm can test the waters
        without taking on heavy exposure.
        """
        equity = max(0.0, self._safe_float(account.get("equity"), account.get("portfolio_value", 58000.0)))
        cash = max(0.0, self._safe_float(account.get("cash"), 0.0))
        multiplier = max(1.0, self._safe_float(account.get("multiplier"), 1.0))
        available_bp = max(0.0, self._safe_float(account.get("buying_power"), cash * multiplier))
        
        probe_eq_pct = min(0.12, self._safe_float(strategy_params.get("starter_buying_power_pct"), 0.10))
        notional = equity * probe_eq_pct
        stop_pct = max(0.006, self._safe_float(opportunity.get("_stop_pct"), 0.0100))
        shares = int(notional / close_price) if close_price > 0 else 0
        
        if close_price >= 1000.0:
            shares = min(shares, 4)
        elif close_price >= 500.0:
            shares = min(shares, 8)
            
        if shares == 0 and close_price > 0 and available_bp >= close_price:
            shares = 1

        return {
            "shares": shares,
            "notional": shares * close_price,
            "available_buying_power": available_bp,
            "buying_power_fraction": probe_eq_pct,
            "stop_pct": stop_pct,
            "is_probe": True,
        }

    def size_pyramid_entry(
        self,
        account: Dict,
        close_price: float,
        opportunity: Dict,
        strategy_params: Dict,
        prob_eval: Optional[Dict] = None,
        current_shares: int = 0
    ) -> Dict:
        """
        Calculates safe institutional position sizing for Pyramiding (浮盈顺势加仓).
        Rules:
        1. Pyramid add-on MUST NOT exceed 30%~40% of the original position (never invert the pyramid!).
        2. Total combined position (current_shares + pyramid_shares) MUST NOT exceed max_single_position_equity_pct (20%~25% equity).
        3. Total combined dollar risk MUST NOT exceed max_trade_risk_pct.
        4. Absolute share cap on high-price stocks.
        """
        equity = max(0.0, self._safe_float(account.get("equity"), account.get("portfolio_value", 58000.0)))
        cash = max(0.0, self._safe_float(account.get("cash"), 0.0))
        multiplier = max(1.0, self._safe_float(account.get("multiplier"), 1.0))
        available_bp = max(0.0, self._safe_float(account.get("buying_power"), cash * multiplier))
        
        cur_shares_abs = abs(int(current_shares))
        cur_notional = cur_shares_abs * close_price
        
        # Hard cap on total combined position notional
        max_eq_pct = min(0.25, self._safe_float(strategy_params.get("max_single_position_equity_pct"), 0.20))
        max_total_notional = equity * max_eq_pct
        remaining_notional = max(0.0, max_total_notional - cur_notional)
        max_pyr_by_notional = int(remaining_notional / close_price) if close_price > 0 else 0
        
        # Pyramid Fraction: At most 40% of the current base position
        pyr_multiplier = min(0.40, self._safe_float(strategy_params.get("pyramid_multiplier"), 0.35))
        base_target_shares = max(1, int(cur_shares_abs * pyr_multiplier)) if cur_shares_abs > 0 else 1
        
        # Risk Budget Cap on Combined Position
        stop_pct = max(0.006, self._safe_float(opportunity.get("_stop_pct"), 0.0100))
        max_risk_pct = min(0.015, self._safe_float(strategy_params.get("max_trade_risk_pct"), 0.010))
        max_risk_dollars = equity * max_risk_pct
        max_total_shares_by_risk = int(max_risk_dollars / (close_price * stop_pct)) if (close_price * stop_pct) > 0 else 0
        max_pyr_by_risk = max(0, max_total_shares_by_risk - cur_shares_abs)
        
        # Take the minimum of all strict safety constraints
        pyr_shares = min(base_target_shares, max_pyr_by_notional, max_pyr_by_risk)
        
        # Buying power check
        if pyr_shares * close_price > available_bp * 0.80:
            pyr_shares = int((available_bp * 0.80) / close_price) if close_price > 0 else 0
            
        # Extra Guardrail for Ultra-High-Price Stocks (e.g. SNDK > $1000/sh)
        if close_price >= 1000.0:
            pyr_shares = min(pyr_shares, 2)  # Maximum 2 shares add-on for $1000+ stocks!
        elif close_price >= 500.0:
            pyr_shares = min(pyr_shares, 5)

        pyr_shares = max(0, pyr_shares)

        return {
            "shares": pyr_shares,
            "notional": pyr_shares * close_price,
            "available_buying_power": available_bp,
            "buying_power_fraction": (cur_notional + pyr_shares * close_price) / equity if equity > 0 else 0.20,
            "stop_pct": stop_pct,
            "base_shares": cur_shares_abs,
            "total_shares": cur_shares_abs + pyr_shares
        }


