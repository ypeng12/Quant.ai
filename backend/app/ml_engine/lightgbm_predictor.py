# backend/app/ml_engine/lightgbm_predictor.py
"""
Quant.ai Real-Time LightGBM Alpha Predictor & Feature Diagnostics.
Loads trained LightGBM weights and predicts real-time probability win rate P_win.
"""

import os
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from typing import Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_DIR = os.path.join(BASE_DIR, "app", "ml_engine", "models")
MODEL_FILE = os.path.join(MODEL_DIR, "lightgbm_alpha.model")
IMPORTANCE_FILE = os.path.join(MODEL_DIR, "feature_importance.json")

class LightGBMALphaPredictor:
    """Real-time inference engine using trained LightGBM model weights."""

    def __init__(self):
        self.model: lgb.Booster = None
        self.importance_info: Dict[str, Any] = {}
        self._load_artifacts()

    def _load_artifacts(self):
        try:
            if os.path.exists(MODEL_FILE):
                self.model = lgb.Booster(model_file=MODEL_FILE)
            if os.path.exists(IMPORTANCE_FILE):
                with open(IMPORTANCE_FILE, "r", encoding="utf-8") as f:
                    self.importance_info = json.load(f)
        except Exception as e:
            print(f"[LightGBMPredictor Warning] Error loading model artifacts: {e}")

    def predict_alpha_probability(self, features: Dict[str, float]) -> Dict[str, Any]:
        """
        Predicts win rate P_win given microstructural feature dictionary.
        Features required: ofi, microprice_velocity, vpin, rvol, spread_ratio
        """
        ofi = float(features.get("ofi", 0.0))
        micro_vel = float(features.get("microprice_velocity", 0.0))
        vpin = float(features.get("vpin", 0.15))
        rvol = float(features.get("rvol", 1.0))
        spread = float(features.get("spread_ratio", 0.0005))
        adx_14 = float(features.get("adx_14", 25.0))
        sub_min_vol = float(features.get("sub_min_vol_accel", 1.0))
        trend_15m = float(features.get("trend_15m_slope", 0.0))

        if self.model is not None:
            X_input = pd.DataFrame([{
                "ofi": ofi,
                "microprice_velocity": micro_vel,
                "vpin": vpin,
                "rvol": rvol,
                "spread_ratio": spread,
                "adx_14": adx_14,
                "sub_min_vol_accel": sub_min_vol,
                "trend_15m_slope": trend_15m
            }])
            raw_prob = float(self.model.predict(X_input)[0])
        else:
            # Mathematical fallback formulation
            logit = (
                0.85 * ofi + 
                24.0 * micro_vel + 
                1.10 * (rvol - 1.0) - 
                1.80 * (vpin - 0.20) +
                0.75 * (adx_14 / 25.0) +
                1.40 * (sub_min_vol - 1.0) +
                1.60 * trend_15m * 50.0
            )
            raw_prob = float(1.0 / (1.0 + np.exp(-logit)))

        p_win = round(raw_prob, 4)
        p_star = self.importance_info.get("optimal_probability_threshold", 0.5239)
        is_signal_active = bool(p_win >= p_star)

        return {
            "p_win": p_win,
            "p_star": p_star,
            "is_signal_active": is_signal_active,
            "feature_importance": self.importance_info.get("importance_gain_pct", {
                "microprice_velocity": 33.67,
                "rvol": 30.97,
                "ofi": 28.41,
                "spread_ratio": 5.75,
                "vpin": 1.19
            }),
            "model_status": "ONLINE" if self.model is not None else "FALLBACK"
        }

# Singleton Predictor
lightgbm_predictor = LightGBMALphaPredictor()
