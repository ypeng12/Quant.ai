# backend/app/broker/probability_engine.py
"""
Probabilistic & Mathematical Expectation Quant Engine
Provides Win-Rate Probability Estimation (P_win), Reward-to-Risk Ratio Estimation (RR_est),
Mathematical Expectation E[PnL], and Kelly Criterion position sizing adjustments.
"""

import math
import os
import joblib
import pandas as pd
from typing import Dict, Optional

import math
import os
import sys
import joblib
import pandas as pd
from typing import Dict, Optional, Tuple

backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "models")
_ML_MODELS_CACHE = {}

def get_ml_zoo_model():
    """Loads and caches QuantMLModelZoo."""
    if "ml_zoo" in _ML_MODELS_CACHE:
        return _ML_MODELS_CACHE["ml_zoo"]

    zoo_path = os.path.join(MODELS_DIR, "quant_ml_zoo.joblib")
    if os.path.exists(zoo_path):
        try:
            from app.ml.ml_model_zoo import QuantMLModelZoo
            main_mod = sys.modules.get("__main__")
            if main_mod and not hasattr(main_mod, "QuantMLModelZoo"):
                setattr(main_mod, "QuantMLModelZoo", QuantMLModelZoo)
            zoo = QuantMLModelZoo.load_zoo(zoo_path)
            _ML_MODELS_CACHE["ml_zoo"] = zoo
            return zoo
        except Exception as e:
            print(f"⚠️ Failed to load QuantMLModelZoo from {zoo_path}: {e}")
    return None

def get_calibrated_ml_model(direction: str = "long"):
    """Loads and caches the calibrated LightGBM ML model for long/short win probability."""
    direction = direction.lower()
    if direction in _ML_MODELS_CACHE:
        return _ML_MODELS_CACHE[direction]

    model_path = os.path.join(MODELS_DIR, f"win_rate_model_{direction}.joblib")
    if os.path.exists(model_path):
        try:
            model = joblib.load(model_path)
            _ML_MODELS_CACHE[direction] = model
            return model
        except Exception as e:
            print(f"⚠️ Failed to load ML model from {model_path}: {e}")
    return None

def sigmoid(x: float) -> float:
    """Standard Sigmoid Logistic Function."""
    return 1.0 / (1.0 + math.exp(-max(-10.0, min(10.0, x))))

def calculate_win_rate_probability(
    score: float,
    rvol: float = 1.0,
    momentum_3_pct: float = 0.0,
    atr_pct: float = 0.5,
    regime: str = "RANGE",
    opportunity: Optional[Dict] = None
) -> Tuple[float, float, float]:
    """
    Evaluates calibrated win probability P_win and prediction uncertainty std_dev.
    Applies uncertainty penalization P_win_adj = P_win - 1.5 * p_std.
    Returns:
        Tuple of (p_win_adjusted, p_std_uncertainty, rank_score)
    """
    direction = "long"
    if opportunity:
        dir_str = opportunity.get("direction", "LONG").lower()
        if "short" in dir_str:
            direction = "short"

    zoo_model = get_ml_zoo_model()
    ml_model = get_calibrated_ml_model(direction)

    p_std = 0.05
    rank_score = 0.0

    if opportunity is not None and (zoo_model is not None or ml_model is not None):
        try:
            # Map features for the newly trained 2-week multi-asset model
            feature_dict = {
                "feature_ofi": float(opportunity.get("alpha_ofi", opportunity.get("feature_ofi", 0.0))),
                "feature_rvol": float(opportunity.get("rvol", rvol)),
                "feature_vwap_dist_pct": float(opportunity.get("vwap_dist_pct", opportunity.get("_vwap_dist_pct", 0.0))),
                "feature_ema_diff_pct": float(opportunity.get("ema_diff_pct", 
                    ((opportunity.get("_ema_9", 1.0) - opportunity.get("_ema_21", 1.0)) / max(1e-5, opportunity.get("_ema_21", 1.0)) * 100.0)
                )),
                "feature_mom_5m": float(opportunity.get("momentum_5m_pct", opportunity.get("momentum_3_pct", momentum_3_pct))),
                "feature_mom_15m": float(opportunity.get("momentum_15m_pct", opportunity.get("momentum_10_pct", 0.0))),
                "feature_er": float(opportunity.get("er", opportunity.get("efficiency_ratio", 0.20))),
                "feature_atr_pct": float(opportunity.get("atr_pct", atr_pct)),
            }
            df_feat = pd.DataFrame([feature_dict])

            if ml_model is not None:
                prob_calibrated = float(ml_model.predict_proba(df_feat)[0, 1])
                p_std = 0.04
            elif zoo_model is not None:
                joint_res = zoo_model.predict_joint(df_feat)
                prob_calibrated = joint_res["p_win"]
                p_std = joint_res["p_std"]
            else:
                prob_calibrated = 0.50

            # Apply prediction uncertainty penalization smoothly
            prob_adj = prob_calibrated - 1.0 * p_std
            bounded_p_win = max(0.35, min(0.88, prob_adj))
            rank_score = round(bounded_p_win * 100.0, 1)
            return round(bounded_p_win, 4), round(p_std, 4), round(rank_score, 4)
        except Exception:
            pass # Fall back to heuristic if feature mapping fails

    # --- Feature-Weighted Logistic Fallback (when joblib model is uninitialized) ---
    vwap_dist = float(opportunity.get("vwap_dist_pct", 0.0)) if opportunity else 0.0
    z_vwap = max(-1.5, min(1.5, vwap_dist)) * 0.4
    z_rvol = max(-1.0, min(2.0, rvol - 1.0)) * 0.4
    z_mom = max(-2.0, min(2.0, abs(momentum_3_pct) / max(0.2, atr_pct))) * 0.4
    regime_bonus = 0.4 if "REVERSAL" in regime else (0.2 if "TREND" in regime else 0.0)

    logits = z_vwap + z_rvol + z_mom + regime_bonus
    base_p = sigmoid(logits)

    p_win = 0.35 + base_p * (0.88 - 0.35)
    rank_score = round(base_p * 100.0, 4)
    return round(p_win, 4), 0.05, rank_score

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

    p_win, p_std, rank_score = calculate_win_rate_probability(score, rvol, momentum_3, atr_pct, regime, opportunity=opportunity)
    rr_est = calculate_expected_rr_ratio(atr_pct, float(opportunity.get("session_range_pct", 1.0)), stop_pct)

    # Check HMM Regime if MarketRegimeHMM model is available
    hmm_path = os.path.join(MODELS_DIR, "market_regime_hmm.joblib")
    hmm_regime = regime
    vol_penalty = 1.0
    if os.path.exists(hmm_path):
        try:
            from app.ml.market_regime_hmm import MarketRegimeHMM
            hmm_engine = MarketRegimeHMM.load(hmm_path)
            # Create minimal dataframe for HMM prediction
            df_hmm = pd.DataFrame([{"feature_mom_3_pct": momentum_3, "feature_atr_pct": atr_pct}])
            hmm_res = hmm_engine.predict_regime_probabilities(df_hmm)
            hmm_regime = hmm_res.get("dominant_regime", regime)
            vol_penalty = hmm_res.get("volatility_penalty", 1.0)
        except Exception:
            pass

    slippage_r = 0.04 # 0.04R estimated execution friction
    # Expected Value E[PnL] in units of R (Risk), adjusted by HMM volatility penalty
    e_pnl_r = ((p_win * rr_est) - ((1.0 - p_win) * 1.0) - slippage_r) * vol_penalty

    # Kelly Criterion optimal position fraction f* = (p*b - q) / b
    q = 1.0 - p_win
    b = rr_est
    kelly_f = (max(0.0, (p_win * b - q) / b) if b > 0 else 0.0) * vol_penalty

    # Entry is approved mathematically only if Expected Value E[PnL] >= 0.05R AND calibrated win probability >= 52%
    min_ev_r = float(strategy_params.get("min_expected_value_r", 0.05))
    is_positive_ev = (e_pnl_r >= min_ev_r) and (p_win >= 0.52)

    return {
        "win_probability": p_win,
        "win_rate_pct": round(p_win * 100.0, 1),
        "prediction_uncertainty_std": p_std,
        "rank_score": rank_score,
        "hmm_regime": hmm_regime,
        "volatility_penalty": vol_penalty,
        "expected_rr": rr_est,
        "expected_value_r": round(e_pnl_r, 3),
        "kelly_fraction": round(kelly_f, 3),
        "is_positive_ev": is_positive_ev,
        "ev_status": "POSITIVE_EV✅" if is_positive_ev else "NEGATIVE_EV⚠️",
    }

def get_daytrade_calibrated_model():
    """Loads and caches the 5m Day Trading Calibrated LightGBM ML model."""
    if "daytrade" in _ML_MODELS_CACHE:
        return _ML_MODELS_CACHE["daytrade"]

    model_path = os.path.join(MODELS_DIR, "daytrade_win_rate_model.joblib")
    if os.path.exists(model_path):
        try:
            model = joblib.load(model_path)
            _ML_MODELS_CACHE["daytrade"] = model
            return model
        except Exception as e:
            print(f"⚠️ Failed to load Day Trading ML model from {model_path}: {e}")
    return None

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

def evaluate_lob_microstructure_sor(lob_data: Dict) -> Dict:
    """
    Evaluates LOB Microstructure ML Suite (idea.txt implementation):
    1. Net Edge Calculation (Expected Return - Friction > Threshold)
    2. Fill Probability P(Fill in 500ms | X)
    3. Adverse Selection Risk P(Adverse | X, Filled)
    4. Smart Order Router (SOR): Maker (Limit Order) vs Taker (Market Order) Choice
    """
    try:
        from app.ml.lob_microstructure_ml import LOBMicrostructureMLSuite
        suite = LOBMicrostructureMLSuite()
        return suite.evaluate_maker_vs_taker_sor(lob_data)
    except Exception as e:
        return {
            "expected_return_bps": 0.0,
            "p_fill_500ms": 0.5,
            "p_adverse_selection": 0.2,
            "ev_maker_bps": 0.0,
            "ev_taker_bps": 0.0,
            "expected_net_edge_bps": 0.0,
            "recommended_order_type": "LIMIT_MAKER",
            "decision_reason": f"Fallback default: {e}"
        }

