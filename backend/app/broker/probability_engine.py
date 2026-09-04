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

def get_advanced_ml_bundle(ticker: Optional[str] = None):
    """
    Loads and caches specialized per-ticker Advanced ML Bundle (Classifier + MFE/MAE Regressors),
    falling back to universal market model if per-ticker bundle is not available.
    """
    if ticker:
        ticker = str(ticker).upper()
        cache_key = f"bundle_{ticker}"
        if cache_key in _ML_MODELS_CACHE:
            return _ML_MODELS_CACHE[cache_key]
        per_ticker_path = os.path.join(MODELS_DIR, "per_ticker", f"advanced_ml_bundle_{ticker}.joblib")
        if os.path.exists(per_ticker_path):
            try:
                bundle = joblib.load(per_ticker_path)
                _ML_MODELS_CACHE[cache_key] = bundle
                return bundle
            except Exception as e:
                print(f"⚠️ Failed to load advanced ML bundle from {per_ticker_path}: {e}")

    if "bundle_universal" in _ML_MODELS_CACHE:
        return _ML_MODELS_CACHE["bundle_universal"]
    universal_path = os.path.join(MODELS_DIR, "universal", "universal_ml_bundle.joblib")
    if os.path.exists(universal_path):
        try:
            bundle = joblib.load(universal_path)
            _ML_MODELS_CACHE["bundle_universal"] = bundle
            return bundle
        except Exception as e:
            print(f"⚠️ Failed to load universal ML bundle from {universal_path}: {e}")
    return None

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

def get_calibrated_ml_model(direction: str = "long", ticker: Optional[str] = None):
    """
    Loads and caches specialized per-ticker LightGBM ML model (e.g. SNDK, TSLA, MSTR, NVDA),
    falling back to general direction model if per-ticker model not available.
    """
    direction = direction.lower()
    if ticker:
        ticker = str(ticker).upper()
        ticker_cache_key = f"{ticker}_{direction}"
        if ticker_cache_key in _ML_MODELS_CACHE:
            return _ML_MODELS_CACHE[ticker_cache_key]

        per_ticker_path = os.path.join(MODELS_DIR, "per_ticker", f"win_rate_model_{ticker}.joblib")
        if os.path.exists(per_ticker_path):
            try:
                model = joblib.load(per_ticker_path)
                _ML_MODELS_CACHE[ticker_cache_key] = model
                return model
            except Exception as e:
                print(f"⚠️ Failed to load per-ticker ML model from {per_ticker_path}: {e}")

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
    Uses Advanced ML Bundle (dedicated per-ticker or universal market model).
    """
    ticker = ""
    if opportunity:
        ticker = str(opportunity.get("ticker", "")).upper()

    bundle = get_advanced_ml_bundle(ticker)
    p_std = 0.04

    if opportunity is not None and bundle is not None:
        try:
            feat_dict = {}
            for col in bundle["features"]:
                if col == "feature_ofi":
                    val = float(opportunity.get("alpha_ofi", opportunity.get("feature_ofi", 0.0)))
                elif col == "feature_ofi_slope":
                    val = float(opportunity.get("alpha_ofi_slope", 0.0))
                elif col == "feature_rvol":
                    val = float(opportunity.get("rvol", rvol))
                elif col == "feature_vol_accel":
                    val = float(opportunity.get("vol_accel", 1.0))
                elif col == "feature_dollar_vol_log":
                    price_val = float(opportunity.get("price", 100.0))
                    vol_val = float(opportunity.get("volume", 1000.0))
                    val = float(opportunity.get("dollar_vol_log", math.log(max(1.0, price_val * vol_val))))
                elif col == "feature_bar_close_loc":
                    val = float(opportunity.get("bar_close_loc", 0.5))
                elif col == "feature_upper_wick_ratio":
                    val = float(opportunity.get("upper_wick_ratio", 0.1))
                elif col == "feature_mom_1m":
                    val = float(opportunity.get("momentum_1m_pct", 0.0))
                elif col == "feature_mom_3m":
                    val = float(opportunity.get("momentum_3_pct", momentum_3_pct))
                elif col == "feature_mom_5m":
                    val = float(opportunity.get("momentum_5m_pct", opportunity.get("momentum_3_pct", momentum_3_pct)))
                elif col == "feature_mom_15m":
                    val = float(opportunity.get("momentum_15m_pct", opportunity.get("momentum_10_pct", 0.0)))
                elif col == "feature_mom_accel":
                    val = float(opportunity.get("momentum_accel", 0.0))
                elif col == "feature_vwap_dist_pct":
                    val = float(opportunity.get("vwap_dist_pct", opportunity.get("_vwap_dist_pct", 0.0)))
                elif col == "feature_vwap_slope":
                    val = float(opportunity.get("vwap_slope", 0.0))
                elif col == "feature_vwap_zscore":
                    val = float(opportunity.get("vwap_zscore", 0.0))
                elif col == "feature_ema_diff_pct":
                    val = float(opportunity.get("ema_diff_pct", 
                        ((opportunity.get("_ema_9", 1.0) - opportunity.get("_ema_21", 1.0)) / max(1e-5, opportunity.get("_ema_21", 1.0)) * 100.0)
                    ))
                elif col == "feature_ema9_slope":
                    val = float(opportunity.get("ema9_slope", 0.0))
                elif col == "feature_atr_pct":
                    val = float(opportunity.get("atr_pct", atr_pct))
                elif col == "feature_atr_expansion":
                    val = float(opportunity.get("atr_expansion", 1.0))
                elif col == "feature_er":
                    val = float(opportunity.get("er", opportunity.get("efficiency_ratio", 0.25)))
                elif col == "feature_donchian_breakout":
                    val = float(opportunity.get("donchian_breakout", 0.0))
                elif col == "feature_session_range_pct":
                    val = float(opportunity.get("session_range_pct", 1.0))
                elif col == "feature_high_dist_pct":
                    val = float(opportunity.get("high_to_now_pct", 0.0))
                elif col == "feature_minutes_from_open":
                    val = float(opportunity.get("minutes_from_open", 0.25))
                else:
                    val = 0.0
                feat_dict[col] = val

            df_feat = pd.DataFrame([feat_dict])
            raw_p = float(bundle["classifier"].predict_proba(df_feat)[0, 1])
            p0 = float(bundle.get("base_rate_p0", 0.42))
            raw_p = max(0.01, min(0.99, raw_p))
            odds_ratio = (raw_p / (1.0 - raw_p)) / (p0 / (1.0 - p0))
            prob_calibrated = odds_ratio / (1.0 + odds_ratio)

            prob_adj = prob_calibrated - 0.03
            bounded_p_win = max(0.38, min(0.88, prob_adj))
            rank_score = round(bounded_p_win * 100.0, 1)
            return round(bounded_p_win, 4), round(p_std, 4), round(rank_score, 4)
        except Exception as ex:
            pass

    # Fallback to standard calibrated model or heuristics
    vwap_dist = float(opportunity.get("vwap_dist_pct", 0.0)) if opportunity else 0.0
    z_vwap = max(-1.5, min(1.5, vwap_dist)) * 0.4
    z_rvol = max(-1.0, min(2.0, rvol - 1.0)) * 0.4
    z_mom = max(-2.0, min(2.0, abs(momentum_3_pct) / max(0.2, atr_pct))) * 0.4
    regime_bonus = 0.4 if "REVERSAL" in regime else (0.2 if "TREND" in regime else 0.0)

    logits = z_vwap + z_rvol + z_mom + regime_bonus
    base_p = sigmoid(logits)
    p_win = 0.38 + base_p * (0.88 - 0.38)
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
    Evaluates Mathematical Expectation E[PnL], Forward Profit Expectancy (MFE/MAE),
    and Kelly Criterion for an intraday opportunity using Advanced ML Bundles.
    """
    score = float(opportunity.get("score", 0.0))
    rvol = float(opportunity.get("rvol", 1.0))
    momentum_3 = float(opportunity.get("momentum_3_pct", 0.0))
    atr_pct = float(opportunity.get("atr_pct", 0.5))
    regime = opportunity.get("regime", "RANGE")
    stop_pct = float(opportunity.get("_stop_pct", 0.0100))
    ticker = str(opportunity.get("ticker", "")).upper()

    bundle = get_advanced_ml_bundle(ticker)

    pred_mfe = atr_pct * 1.5
    pred_mae = atr_pct * 1.0

    p_win, p_std, rank_score = calculate_win_rate_probability(score, rvol, momentum_3, atr_pct, regime, opportunity=opportunity)

    if bundle is not None:
        try:
            feat_dict = {}
            for col in bundle["features"]:
                if col == "feature_ofi":
                    val = float(opportunity.get("alpha_ofi", opportunity.get("feature_ofi", 0.0)))
                elif col == "feature_ofi_slope":
                    val = float(opportunity.get("alpha_ofi_slope", 0.0))
                elif col == "feature_rvol":
                    val = float(opportunity.get("rvol", rvol))
                elif col == "feature_vol_accel":
                    val = float(opportunity.get("vol_accel", 1.0))
                elif col == "feature_dollar_vol_log":
                    price_val = float(opportunity.get("price", 100.0))
                    vol_val = float(opportunity.get("volume", 1000.0))
                    val = float(opportunity.get("dollar_vol_log", math.log(max(1.0, price_val * vol_val))))
                elif col == "feature_bar_close_loc":
                    val = float(opportunity.get("bar_close_loc", 0.5))
                elif col == "feature_upper_wick_ratio":
                    val = float(opportunity.get("upper_wick_ratio", 0.1))
                elif col == "feature_mom_1m":
                    val = float(opportunity.get("momentum_1m_pct", 0.0))
                elif col == "feature_mom_3m":
                    val = float(opportunity.get("momentum_3_pct", momentum_3))
                elif col == "feature_mom_5m":
                    val = float(opportunity.get("momentum_5m_pct", opportunity.get("momentum_3_pct", momentum_3)))
                elif col == "feature_mom_15m":
                    val = float(opportunity.get("momentum_15m_pct", opportunity.get("momentum_10_pct", 0.0)))
                elif col == "feature_mom_accel":
                    val = float(opportunity.get("momentum_accel", 0.0))
                elif col == "feature_vwap_dist_pct":
                    val = float(opportunity.get("vwap_dist_pct", opportunity.get("_vwap_dist_pct", 0.0)))
                elif col == "feature_vwap_slope":
                    val = float(opportunity.get("vwap_slope", 0.0))
                elif col == "feature_vwap_zscore":
                    val = float(opportunity.get("vwap_zscore", 0.0))
                elif col == "feature_ema_diff_pct":
                    val = float(opportunity.get("ema_diff_pct", 
                        ((opportunity.get("_ema_9", 1.0) - opportunity.get("_ema_21", 1.0)) / max(1e-5, opportunity.get("_ema_21", 1.0)) * 100.0)
                    ))
                elif col == "feature_ema9_slope":
                    val = float(opportunity.get("ema9_slope", 0.0))
                elif col == "feature_atr_pct":
                    val = float(opportunity.get("atr_pct", atr_pct))
                elif col == "feature_atr_expansion":
                    val = float(opportunity.get("atr_expansion", 1.0))
                elif col == "feature_er":
                    val = float(opportunity.get("er", opportunity.get("efficiency_ratio", 0.25)))
                elif col == "feature_donchian_breakout":
                    val = float(opportunity.get("donchian_breakout", 0.0))
                elif col == "feature_session_range_pct":
                    val = float(opportunity.get("session_range_pct", 1.0))
                elif col == "feature_high_dist_pct":
                    val = float(opportunity.get("high_to_now_pct", 0.0))
                elif col == "feature_minutes_from_open":
                    val = float(opportunity.get("minutes_from_open", 0.25))
                else:
                    val = 0.0
                feat_dict[col] = val

            df_feat = pd.DataFrame([feat_dict])
            pred_mfe = float(bundle["regressor_mfe"].predict(df_feat)[0])
            pred_mae = float(bundle["regressor_mae"].predict(df_feat)[0])
        except Exception:
            pass

    expected_gain_pct = max(0.25, pred_mfe)
    expected_loss_pct = max(0.25, pred_mae)
    rr_est = round(max(1.0, min(5.0, expected_gain_pct / expected_loss_pct)), 2)

    # Net Expected Edge in percentage: P_win * Gain - (1 - P_win) * Loss - Friction
    net_edge_pct = (p_win * expected_gain_pct) - ((1.0 - p_win) * expected_loss_pct) - 0.04
    # Expected Value in R units
    e_pnl_r = round(net_edge_pct / expected_loss_pct, 3)

    # Optimal Kelly position fraction f* = (p*b - q) / b
    q = 1.0 - p_win
    b = rr_est
    kelly_f = round(max(0.0, (p_win * b - q) / b) if b > 0 else 0.0, 3)

    # Explosive Trend Flag: Predicted Gain >= 1.8% and P_win >= 52%
    is_explosive = bool(expected_gain_pct >= 1.8 and p_win >= 0.52)

    min_ev_r = float(strategy_params.get("min_expected_value_r", 0.05))
    is_positive_ev = (e_pnl_r >= min_ev_r) and (p_win >= 0.50)

    return {
        "win_probability": p_win,
        "win_rate_pct": round(p_win * 100.0, 1),
        "prediction_uncertainty_std": p_std,
        "rank_score": rank_score,
        "expected_mfe_pct": round(expected_gain_pct, 2),
        "expected_mae_pct": round(expected_loss_pct, 2),
        "expected_net_edge_pct": round(net_edge_pct, 2),
        "is_explosive": is_explosive,
        "expected_rr": rr_est,
        "expected_value_r": e_pnl_r,
        "kelly_fraction": kelly_f,
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

