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
        Anti-Bull/Bear Trap & Upper/Lower Wick Rejection Engine:
        Detects false breakouts where buyers/sellers attempt to push higher/lower but are absorbed by passive walls.
        - Long upper wick >= 40% + Ask wall >= 2.5x -> Active SHORT Opportunity (Penalty -55.0)
        - Long lower wick >= 40% + Bid wall >= 2.5x -> Active LONG Opportunity (Bonus +55.0)
        Returns: (is_trap, penalty_score, trap_reason)
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
        ask_to_bid_ratio = ask_size / max(1.0, bid_size)

        # Bull Trap / Upper Wick Rejection -> Severe Penalty to trigger SHORT Alpha
        is_upper_wick_trap = upper_wick_ratio >= 0.40 and (high - open_p) > 0
        is_ask_wall_trap = ask_to_bid_ratio >= 2.5 and (close >= open_p)

        if is_upper_wick_trap and is_ask_wall_trap:
            return True, -55.0, f"⚡ 诱多强做空信号 (Severe Bull Trap: 上影线{upper_wick_ratio:.0%} + 卖压墙{ask_to_bid_ratio:.1f}x)"
        elif is_upper_wick_trap:
            return True, -35.0, f"上影线拒买 (Upper Wick Rejection: {upper_wick_ratio:.0%})"
        elif is_ask_wall_trap:
            return True, -25.0, f"卖盘墙压制 (Ask Depth Wall: {ask_to_bid_ratio:.1f}x)"

        # Bear Trap / Lower Wick Rejection -> Severe Bonus to trigger LONG Alpha
        is_lower_wick_trap = lower_wick_ratio >= 0.40 and (open_p - low) > 0
        bid_to_ask_ratio = bid_size / max(1.0, ask_size)
        is_bid_wall_trap = bid_to_ask_ratio >= 2.5 and (close <= open_p)

        if is_lower_wick_trap and is_bid_wall_trap:
            return True, +55.0, f"⚡ 诱空强买入信号 (Severe Bear Trap: 下影线{lower_wick_ratio:.0%} + 买盘墙{bid_to_ask_ratio:.1f}x)"
        elif is_lower_wick_trap:
            return True, +35.0, f"下影线支撑 (Lower Wick Support: {lower_wick_ratio:.0%})"
        elif is_bid_wall_trap:
            return True, +25.0, f"买盘墙托盘 (Bid Depth Support: {bid_to_ask_ratio:.1f}x)"

        return False, 0.0, "Normal Microstructure"

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
        Dynamically adjusts weights based on market regime (Trend vs Range).
        Applies Anti-Bull/Bear Trap filtering.
        """
        alpha_ofi = self.compute_ofi_alpha(row, prev_row)
        alpha_micro = self.compute_micro_price_alpha(row)
        alpha_ou = self.compute_ou_stat_arb_alpha(row, adx=adx)
        alpha_lead_lag = self.compute_lead_lag_alpha(row, sector_return_pct=sector_return_pct)

        # ML Probability Alpha [-1.0, +1.0]
        alpha_ml = (ml_p_win_long - ml_p_win_short) * 2.0
        alpha_ml = float(np.clip(alpha_ml, -1.0, 1.0))

        # Intraday Multi-Wave Regime Calibration (美股日内波段时段动态自适应引擎)
        # 09:30-10:35: 开盘突破浪 (Opening Surge) -> 提升动量与订单流权重，追击多头主升
        # 10:35-12:00: 冲高衰竭浪 (Mid-Day Exhaustion) -> 提升均值回归权重，捕获空头回调
        # 12:00-13:30: 午盘 VWAP 支撑浪 (Noon Rebound) -> 提升 VWAP 支撑与订单流买盘，捕获反弹
        # 13:30-14:35: 下行调整浪 (Afternoon Dip) -> 捕获二次调整空头
        # 14:35-15:55: 尾盘冲刺浪 (Power Hour Surge) -> 机构 MOC 动量追击
        current_est_hour = row.get("est_hour", 10)
        current_est_minute = row.get("est_minute", 0)
        est_float = current_est_hour + current_est_minute / 60.0

        if 9.5 <= est_float < 10.6:
            # 开盘冲刺浪：主打订单流与动量
            w_ofi, w_micro, w_ou, w_lead_lag, w_ml = 0.40, 0.20, 0.05, 0.20, 0.15
        elif 10.6 <= est_float < 12.0:
            # 冲高衰竭做空浪：主打均值回归与微观结构
            w_ofi, w_micro, w_ou, w_lead_lag, w_ml = 0.15, 0.35, 0.35, 0.05, 0.10
        elif 12.0 <= est_float < 13.5:
            # 午盘反弹浪：主打订单流与 lead-lag 联动
            w_ofi, w_micro, w_ou, w_lead_lag, w_ml = 0.35, 0.20, 0.15, 0.20, 0.10
        elif 13.5 <= est_float < 14.6:
            # 下午调整浪：均值回归做空
            w_ofi, w_micro, w_ou, w_lead_lag, w_ml = 0.20, 0.30, 0.35, 0.05, 0.10
        else:
            # 尾盘冲刺浪：动量与 ML 主导
            w_ofi, w_micro, w_ou, w_lead_lag, w_ml = 0.35, 0.15, 0.05, 0.25, 0.20

        if adx >= 25.0:
            # 强趋势修正：增加趋势与 OFI 权重
            w_ofi = min(0.50, w_ofi + 0.10)

        composite_alpha_raw = (
            w_ofi * alpha_ofi +
            w_micro * alpha_micro +
            w_ou * alpha_ou +
            w_lead_lag * alpha_lead_lag +
            w_ml * alpha_ml
        )

        composite_score = float(np.clip(composite_alpha_raw * 100.0, -100.0, 100.0))

        # Apply Anti-Trap Filter
        is_trap, trap_penalty, trap_reason = self.compute_anti_bull_trap_filter(row)
        if is_trap:
            composite_score = float(np.clip(composite_score + trap_penalty, -100.0, 100.0))

        composite_score = round(composite_score, 1)

        return {
            "composite_alpha_score": composite_score,
            "alpha_ofi": round(alpha_ofi, 3),
            "alpha_micro": round(alpha_micro, 3),
            "alpha_ou": round(alpha_ou, 3),
            "alpha_lead_lag": round(alpha_lead_lag, 3),
            "alpha_ml": round(alpha_ml, 3),
            "is_trap": is_trap,
            "trap_reason": trap_reason,
            "regime_type": "RANGE_STAT_ARB" if adx < 22.0 else "TREND_MOMENTUM",
        }

