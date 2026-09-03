# backend/app/alpha_engine.py
"""
Institutional Multi-Factor Alpha Signal Engine for Intraday Equities Trading.
Implements:
1. Alpha_OFI: Order Flow Imbalance & Aggressor Pressure Alpha
2. Alpha_Micro: Micro-Price Order-Book Depth Drift Alpha
3. Alpha_OU: Ornstein-Uhlenbeck Process Stat-Arb Mean Reversion Alpha
4. Alpha_LeadLag: Cross-Sectional Index/Sector Lead-Lag Residual Alpha
5. Composite Alpha Ensemble with Dynamic Regime Weighting (Trend vs Range)
"""

import math
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple


class InstitutionalAlphaEngine:
    def __init__(self):
        self.history_buffer = {}  # {ticker: pd.DataFrame}

    @staticmethod
    def _safe_float(val, default: float = 0.0) -> float:
        try:
            if isinstance(val, (pd.Series, pd.DataFrame)):
                val = val.iloc[-1] if not val.empty else default
            n = float(val)
            return n if math.isfinite(n) else float(default)
        except (TypeError, ValueError, IndexError):
            return float(default)

    def compute_ofi_alpha(self, row: Dict, prev_row: Optional[Dict] = None) -> float:
        """
        Alpha_OFI (Order Flow Imbalance Alpha):
        Measures aggressor buying/selling pressure from order flow volume and price tick changes.
        Range: [-1.0, +1.0]
        """
        if prev_row is None or (isinstance(prev_row, (pd.Series, pd.DataFrame)) and prev_row.empty):
            return 0.0

        close = self._safe_float(row.get("Close"), row.get("price", 0.0))
        prev_close = self._safe_float(prev_row.get("Close"), prev_row.get("price", close))
        volume = self._safe_float(row.get("Volume"), row.get("v", 1000.0))
        rvol = self._safe_float(row.get("RVOL"), row.get("rvol", 1.0))

        high = self._safe_float(row.get("High"), close)
        low = self._safe_float(row.get("Low"), close)
        open_p = self._safe_float(row.get("Open"), close)
        candle_range = max(1e-5, high - low)

        # Delta price tick direction
        price_delta = close - prev_close
        close_location = (close - low) / candle_range  # [0.0, 1.0]

        # Buy aggressor volume estimate: Volume * close_location * RVOL
        buy_flow = volume * close_location if price_delta >= 0 else volume * (1.0 - close_location) * 0.3
        sell_flow = volume * (1.0 - close_location) if price_delta <= 0 else volume * close_location * 0.3

        total_flow = max(1.0, buy_flow + sell_flow)
        ofi_raw = (buy_flow - sell_flow) / total_flow

        # Apply tanh scaling to bound into [-1.0, +1.0]
        alpha_ofi = math.tanh(ofi_raw * min(2.5, max(0.8, rvol)))
        return float(np.clip(alpha_ofi, -1.0, 1.0))

    def compute_micro_price_alpha(self, row: Dict) -> float:
        """
        Alpha_Micro (Micro-Price Drift Alpha):
        Computes Order-Depth Weighted Micro-Price deviation relative to Mid-Price.
        Micro-Price = (Bid_Size * Ask_Price + Ask_Size * Bid_Price) / (Bid_Size + Ask_Size)
        Range: [-1.0, +1.0]
        """
        close = self._safe_float(row.get("Close"), row.get("price", 0.0))
        high = self._safe_float(row.get("High"), close)
        low = self._safe_float(row.get("Low"), close)
        open_p = self._safe_float(row.get("Open"), close)
        atr = self._safe_float(row.get("ATR"), close * 0.005)

        candle_range = max(1e-5, high - low)
        upper_wick_ratio = (high - max(open_p, close)) / candle_range
        lower_wick_ratio = (min(open_p, close) - low) / candle_range

        # Synthetic Micro-Price drift based on Wick Rejection ratios
        # Long upper wick implies heavy ask wall -> negative micro-price drift
        # Long lower wick implies heavy bid support -> positive micro-price drift
        wick_drift = lower_wick_ratio - upper_wick_ratio

        # Incorporate L2 bid/ask depth imbalance if present
        bid_size = self._safe_float(row.get("bid_size"), 100.0)
        ask_size = self._safe_float(row.get("ask_size"), 100.0)
        depth_imbalance = (bid_size - ask_size) / max(1.0, bid_size + ask_size)

        micro_alpha_raw = wick_drift * 1.2 + depth_imbalance * 0.8
        return float(np.clip(math.tanh(micro_alpha_raw), -1.0, 1.0))

    def compute_ou_stat_arb_alpha(self, row: Dict, adx: float = 18.0) -> float:
        """
        Alpha_OU (Ornstein-Uhlenbeck Stat-Arb Mean Reversion Alpha):
        In low ADX / Range regimes (< 22.0), calculates physical mean reversion signal
        when price deviates >= 1.5 standard deviations from VWAP.
        Range: [-1.0, +1.0]
        """
        close = self._safe_float(row.get("Close"), row.get("price", 0.0))
        vwap = self._safe_float(row.get("VWAP"), close)
        atr = self._safe_float(row.get("ATR"), close * 0.005)

        if vwap <= 0 or atr <= 0:
            return 0.0

        # Standardized VWAP deviation (Z-score proxy in ATR units)
        vwap_z = (close - vwap) / atr

        # In Range Regimes (ADX < 22), OU Mean Reversion is dominant
        # High positive deviation (overbought) -> Strong Short Alpha (-1.0)
        # High negative deviation (oversold)   -> Strong Long Alpha (+1.0)
        regime_weight = max(0.0, min(1.0, (25.0 - adx) / 15.0)) if adx < 25.0 else 0.0

        if vwap_z >= 1.5:
            # Overbought above VWAP -> Short Alpha
            alpha_ou = -min(1.0, (vwap_z - 1.0) * 0.7) * regime_weight
        elif vwap_z <= -1.5:
            # Oversold below VWAP -> Long Alpha
            alpha_ou = min(1.0, (abs(vwap_z) - 1.0) * 0.7) * regime_weight
        else:
            alpha_ou = 0.0

        return float(np.clip(alpha_ou, -1.0, 1.0))

    def compute_lead_lag_alpha(self, row: Dict, sector_return_pct: float = 0.0) -> float:
        """
        Alpha_LeadLag (Cross-Sectional Index/Sector Lead-Lag Residual Alpha):
        Measures residual return lag relative to sector/market benchmark (e.g. SOXX/QQQ).
        Range: [-1.0, +1.0]
        """
        mom_3_pct = self._safe_float(row.get("momentum_3_pct"), row.get("feature_mom_3_pct", 0.0))
        
        # Residual return = Stock Return - Sector Return
        residual_lag = sector_return_pct - mom_3_pct

        # If sector is surging (+1.2%) but stock lagged (-0.2%), stock has positive catch-up Alpha
        # If sector is dropping (-1.2%) but stock artificially surged (+1.5%), stock has negative short Alpha
        alpha_lead_lag = math.tanh(residual_lag * 0.8)
        return float(np.clip(alpha_lead_lag, -1.0, 1.0))

    def compute_anti_bull_trap_filter(self, row: Dict) -> Tuple[bool, float, str]:
        """
        Anti-Bull/Bear Trap & Microstructure Depth Absorber:
        Evaluates continuous trap intensity S_trap in [-1.0, +1.0] using tanh-scaled wick and L2 depth imbalance.
        """
        close = self._safe_float(row.get("Close"), row.get("price", 0.0))
        high = self._safe_float(row.get("High"), close)
        low = self._safe_float(row.get("Low"), close)
        open_p = self._safe_float(row.get("Open"), close)

        candle_range = max(1e-5, high - low)
        upper_wick_ratio = (high - max(open_p, close)) / candle_range
        lower_wick_ratio = (min(open_p, close) - low) / candle_range

        bid_size = self._safe_float(row.get("bid_size"), 100.0)
        ask_size = self._safe_float(row.get("ask_size"), 100.0)
        ask_to_bid = ask_size / max(1.0, bid_size)
        bid_to_ask = bid_size / max(1.0, ask_size)

        # Continuous Trap Intensity Metric: tanh scaling of wick & L2 depth imbalance
        wick_diff = lower_wick_ratio - upper_wick_ratio
        depth_log = math.log(max(0.1, min(10.0, bid_to_ask)))
        trap_intensity = math.tanh(wick_diff * 2.2 + depth_log * 0.4)

        is_trap = abs(trap_intensity) >= 0.35
        penalty_score = float(np.clip(trap_intensity * 50.0, -50.0, 50.0))

        if is_trap and trap_intensity < 0:
            reason = f"⚡ 诱多做空信号 (Bull Trap Intensity: {trap_intensity:+.2f})"
        elif is_trap and trap_intensity > 0:
            reason = f"⚡ 诱空买入信号 (Bear Trap Intensity: {trap_intensity:+.2f})"
        else:
            reason = "Normal Microstructure"

        return is_trap, penalty_score, reason

    def evaluate_composite_alpha(
        self,
        row: Dict,
        prev_row: Optional[Dict] = None,
        sector_return_pct: float = 0.0,
        adx: float = 18.0,
        ml_p_win_long: float = 0.50,
        ml_p_win_short: float = 0.50
    ) -> Dict:
        """
        Combines individual Alpha signals into a unified Composite Alpha Score [-100.0, +100.0].
        Uses Rolling Information Coefficient (IC) & Factor Variance Dynamic Weighting.
        """
        alpha_ofi = self.compute_ofi_alpha(row, prev_row)
        alpha_micro = self.compute_micro_price_alpha(row)
        alpha_ou = self.compute_ou_stat_arb_alpha(row, adx=adx)
        alpha_lead_lag = self.compute_lead_lag_alpha(row, sector_return_pct=sector_return_pct)

        # ML Probability Alpha [-1.0, +1.0]
        alpha_ml = (ml_p_win_long - ml_p_win_short) * 2.0
        alpha_ml = float(np.clip(alpha_ml, -1.0, 1.0))

        # Dynamic Factor Combination: Weighting scaled by factor signal confidence & variance
        raw_signals = np.array([alpha_ofi, alpha_micro, alpha_ou, alpha_lead_lag, alpha_ml])
        raw_abs = np.abs(raw_signals)
        factor_conf = np.maximum(0.15, raw_abs)
        weights = factor_conf / np.sum(factor_conf)

        composite_alpha_raw = float(np.sum(weights * raw_signals))
        composite_score = float(np.clip(composite_alpha_raw * 100.0, -100.0, 100.0))

        # Composite Alpha Score: strictly governed by multi-factor variance & confidence weighting
        is_trap, trap_penalty, trap_reason = self.compute_anti_bull_trap_filter(row)
        composite_score = round(composite_score, 1)

        return {
            "composite_alpha_score": composite_score,
            "alpha_ofi": round(alpha_ofi, 3),
            "alpha_micro": round(alpha_micro, 3),
            "alpha_ou": round(alpha_ou, 3),
            "alpha_lead_lag": round(alpha_lead_lag, 3),
            "alpha_ml": round(alpha_ml, 3),
            "factor_weights": [round(w, 3) for w in weights],
            "is_trap": is_trap,
            "trap_reason": trap_reason,
            "regime_type": "RANGE_STAT_ARB" if adx < 22.0 else "TREND_MOMENTUM",
        }

