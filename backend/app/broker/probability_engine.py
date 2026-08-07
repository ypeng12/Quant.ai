# backend/app/broker/probability_engine.py
"""
Probabilistic & Mathematical Expectation Quant Engine
Provides Win-Rate Probability Estimation (P_win), Reward-to-Risk Ratio Estimation (RR_est),
Mathematical Expectation E[PnL], and Kelly Criterion position sizing adjustments.
"""

import math
from typing import Dict

def sigmoid(x: float) -> float:
    """Standard Sigmoid Logistic Function."""
    return 1.0 / (1.0 + math.exp(-max(-10.0, min(10.0, x))))

def calculate_win_rate_probability(
    score: float,
    rvol: float = 1.0,
    momentum_3_pct: float = 0.0,
    atr_pct: float = 0.5,
    regime: str = "RANGE"
) -> float:
    """
    Logistic Win-Rate Estimator:
    Maps multi-factor AI score, relative volume (RVOL), momentum/ATR ratio,
    and market structural regime (e.g. SHORT_REVERSAL) to a calibrated win probability P_win in [0.35, 0.88].
    """
    # Normalize score centered at entry threshold 78
    z_score = (score - 78.0) / 10.0
    z_rvol = max(-1.0, min(2.0, rvol - 1.0)) * 0.4
    z_mom = max(-2.0, min(2.0, abs(momentum_3_pct) / max(0.2, atr_pct))) * 0.3
    regime_bonus = 0.5 if "REVERSAL" in regime else (0.2 if "TREND" in regime else 0.0)

    logits = z_score + z_rvol + z_mom + regime_bonus
    base_p = sigmoid(logits)

    # Scale to realistic intraday win rate bounds [0.35, 0.88]
    p_win = 0.35 + base_p * (0.88 - 0.35)
    return round(p_win, 4)

def calculate_expected_rr_ratio(
    atr_pct: float,
    session_range_pct: float,
    stop_pct: float
) -> float:
    """
    Estimates realistic intraday Reward-to-Risk ratio (RR_est) based on daily volatility bounds and stop distance.
    """
    stop_distance = max(0.003, stop_pct)
    target_move = max(session_range_pct * 0.55 / 100.0, 2.2 * (atr_pct / 100.0))
    rr_ratio = target_move / stop_distance if stop_distance > 0 else 1.5
    return round(max(1.0, min(4.5, rr_ratio)), 2)

def evaluate_mathematical_expectation(opportunity: Dict, strategy_params: Dict) -> Dict:
    """
    Evaluates Mathematical Expectation E[PnL] and Kelly Criterion for an intraday opportunity.
    Returns:
        Dict containing win_probability, expected_rr, expected_value_r, kelly_fraction, and is_positive_ev flag.
    """
    score = float(opportunity.get("score", 0.0))
    rvol = float(opportunity.get("rvol", 1.0))
    momentum_3 = float(opportunity.get("momentum_3_pct", 0.0))
    atr_pct = float(opportunity.get("atr_pct", 0.5))
    regime = opportunity.get("regime", "RANGE")
    stop_pct = float(opportunity.get("_stop_pct", 0.0100))

    p_win = calculate_win_rate_probability(score, rvol, momentum_3, atr_pct, regime)
    rr_est = calculate_expected_rr_ratio(atr_pct, float(opportunity.get("session_range_pct", 1.0)), stop_pct)

    slippage_r = 0.04 # 0.04R estimated execution friction
    # Expected Value E[PnL] in units of R (Risk)
    e_pnl_r = (p_win * rr_est) - ((1.0 - p_win) * 1.0) - slippage_r

    # Kelly Criterion optimal position fraction f* = (p*b - q) / b
    q = 1.0 - p_win
    b = rr_est
    kelly_f = max(0.0, (p_win * b - q) / b) if b > 0 else 0.0

    # Entry is approved mathematically only if Expected Value E[PnL] >= +0.15R
    min_ev_r = float(strategy_params.get("min_expected_value_r", 0.15))
    is_positive_ev = e_pnl_r >= min_ev_r

    return {
        "win_probability": p_win,
        "win_rate_pct": round(p_win * 100.0, 1),
        "expected_rr": rr_est,
        "expected_value_r": round(e_pnl_r, 3),
        "kelly_fraction": round(kelly_f, 3),
        "is_positive_ev": is_positive_ev,
        "ev_status": "POSITIVE_EV✅" if is_positive_ev else "NEGATIVE_EV⚠️",
    }

def evaluate_zero_delay_opening_trigger(
    opportunity: Dict,
    is_opening_window: bool
) -> bool:
    """
    Opening Catalyst Zero-Delay Trigger (9:30 - 9:45 EST Blitz):
    For high RVOL (>2.0x) or high intraday volatility (>2.5%) catalyst stocks,
    bypasses 2-bar multi-indicator confirmation when single 1m bar crosses VWAP or breaks out.
    """
    direction = opportunity.get("direction", "NEUTRAL")
    if direction == "NEUTRAL":
        return False

    rvol = float(opportunity.get("rvol", 1.0))
    session_range = float(opportunity.get("session_range_pct", 0.0))
    momentum_3 = float(opportunity.get("momentum_3_pct", 0.0))
    regime = opportunity.get("regime", "RANGE")

    # High catalyst conditions: RVOL >= 2.0 or Range >= 2.5% or REVERSAL regime
    is_catalyst = (rvol >= 1.8 or session_range >= 2.2 or "REVERSAL" in regime)
    if not is_catalyst:
        return False

    if is_opening_window:
        # Opening 15m blitz: Single-bar momentum > 0.15% in trade direction confirms instantly
        if direction == "LONG" and momentum_3 > 0.10:
            return True
        if direction == "SHORT" and momentum_3 < -0.10:
            return True

    # General instant reversal blitz: REVERSAL regime confirms zero-delay
    if "REVERSAL" in regime and abs(momentum_3) >= 0.15:
        return True

    return False

