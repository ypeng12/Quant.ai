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
        prob_eval: Optional[Dict] = None,
        tier: int = 1,
        existing_notional: float = 0.0,
    ) -> Dict:
        equity = max(0.0, self._safe_float(account.get("equity"), account.get("portfolio_value", 58000.0)))
        cash = max(0.0, self._safe_float(account.get("cash"), 0.0))
        multiplier = max(1.0, self._safe_float(account.get("multiplier"), 1.0))
        available_bp = max(0.0, self._safe_float(account.get("buying_power"), cash * multiplier))
        utilization = self._safe_float(strategy_params.get("buying_power_utilization_pct"), 0.95)
        
        # Pure Alpha & Kelly Dynamic Sizing Core Rule:
        # Scale position dynamically according to Alpha conviction & ML win probability & buying power.
        # No arbitrary hard dollar cap.
        max_bp_pct = self._safe_float(strategy_params.get("max_single_position_bp_pct"), 0.45)
        max_eq_mult = self._safe_float(strategy_params.get("max_single_position_equity_multiplier"), 1.80)
        
        if available_bp > equity * 1.2:
            base_position_budget = min(available_bp * max_bp_pct, equity * max_eq_mult)
        else:
            base_position_budget = equity * self._safe_float(strategy_params.get("max_single_position_equity_pct"), 0.70)
        
        # Kelly Criterion & ML Alpha Conviction Sizing:
        score = self._safe_float(opportunity.get("score"), 50.0)
        p_win = self._safe_float(opportunity.get("win_probability", prob_eval.get("win_probability", 0.50) if prob_eval else 0.50), 0.50)
        conviction_mult = max(0.60, min(1.0, (p_win - 0.45) * 3.0 + (score / 100.0) * 0.5))
        if opportunity.get("is_explosive", False) or self._safe_float(opportunity.get("expected_mfe_pct"), 0.0) >= 1.5:
            conviction_mult = 1.0
        
        total_position_budget = min(base_position_budget * conviction_mult, available_bp * utilization)
        
        staged_enabled = strategy_params.get("staged_entry_enabled", True)
        tier1_ratio = self._safe_float(strategy_params.get("tier1_size_ratio"), 0.40)
        tier2_ratio = self._safe_float(strategy_params.get("tier2_size_ratio"), 0.60)
        
        stop_pct = max(0.005, self._safe_float(opportunity.get("_stop_pct"), 0.0100))
        max_risk_dollars = equity * self._safe_float(strategy_params.get("max_trade_risk_pct"), 0.035)

        if staged_enabled and tier == 1:
            intended_notional = total_position_budget * tier1_ratio
            risk_constrained_notional = (max_risk_dollars * tier1_ratio / stop_pct) if stop_pct > 0 else intended_notional
            final_notional = min(intended_notional, risk_constrained_notional, available_bp * utilization)
        elif staged_enabled and tier == 2:
            remaining_budget = max(0.0, total_position_budget - existing_notional)
            intended_notional = total_position_budget * tier2_ratio
            final_notional = min(intended_notional, remaining_budget, available_bp * utilization)
        else:
            final_notional = total_position_budget

        shares = int(final_notional / close_price) if close_price > 0 else 0
        
        # Volatility-Parity (Risk Parity) Guard:
        # High-volatility & high-dollar stocks (e.g. SNDK > $1,500 moving $40+/day)
        # must be scaled so that a 1.5x ATR swing cannot exceed the allocated trade risk budget.
        atr_val = self._safe_float(opportunity.get("_atr"), close_price * 0.015)
        atr_dollar_risk = max(close_price * 0.008, atr_val * 1.50)
        tier_risk_ratio = tier1_ratio if tier == 1 else tier2_ratio
        trade_risk_budget = equity * self._safe_float(strategy_params.get("max_trade_risk_pct"), 0.025) * tier_risk_ratio
        vol_parity_shares = int(trade_risk_budget / atr_dollar_risk) if atr_dollar_risk > 0 else shares
        if vol_parity_shares > 0:
            shares = min(shares, vol_parity_shares)

        # High-price stock protection: ensure at least 1 share if buying power permits
        if shares == 0 and close_price > 500.0 and available_bp >= close_price * 0.9:
            shares = 1

        return {
            "shares": shares,
            "notional": shares * close_price,
            "available_buying_power": available_bp,
            "buying_power_fraction": (shares * close_price) / equity if equity > 0 else 0.0,
            "risk_budget": max_risk_dollars,
            "stop_pct": stop_pct,
            "tier": tier,
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


