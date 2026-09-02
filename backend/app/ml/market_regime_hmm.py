# backend/app/ml/market_regime_hmm.py
"""
Hidden Markov Model (HMM) Market Structural Regime Classifier.
Unsupervised 3-State Gaussian HMM:
- State 0: Low-Volatility Bull Trend (Low-Vol, positive drift)
- State 1: Sideways Range-bound Market (Normal vol, near 0 drift)
- State 2: High-Volatility Bear / Sharp Reversal (High-Vol, negative/extreme drift)
Outputs current regime probabilities and dominant regime classification.
"""

import os
import sys
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional
from hmmlearn.hmm import GaussianHMM

MODELS_DIR = os.path.dirname(os.path.abspath(__file__))

REGIME_LABELS = {
    0: "TREND_BULL",
    1: "RANGE_SIDEWAYS",
    2: "VOLATILE_REVERSAL"
}

class MarketRegimeHMM:
    def __init__(self, n_components: int = 3, random_state: int = 42):
        self.n_components = n_components
        self.random_state = random_state
        self.model: Optional[GaussianHMM] = None
        self.state_map: Dict[int, str] = REGIME_LABELS.copy()

    def prepare_features(self, df: pd.DataFrame) -> np.ndarray:
        """
        Prepares 2D feature matrix [Daily_Return %, Log_Vol / Rolling_Volatility] for HMM fitting.
        """
        if "Close" in df.columns:
            ret = df["Close"].pct_change() * 100.0
            vol = ret.rolling(10, min_periods=3).std()
        elif "feature_mom_3_pct" in df.columns:
            ret = df["feature_mom_3_pct"]
            vol = df["feature_atr_pct"]
        else:
            ret = pd.Series(np.zeros(len(df)))
            vol = pd.Series(np.ones(len(df)))

        aligned = pd.concat([ret, vol], axis=1).dropna()
        return aligned.values

    def fit(self, df: pd.DataFrame) -> 'MarketRegimeHMM':
        """
        Fits 3-State Gaussian HMM on historical price/volatility observations.
        """
        X = self.prepare_features(df)
        if len(X) < 20:
            return self

        hmm = GaussianHMM(
            n_components=self.n_components,
            covariance_type="full",
            n_iter=100,
            random_state=self.random_state
        )
        hmm.fit(X)
        self.model = hmm

        # Sort state indices by volatility (means column 1) to standardize regime names
        vols = [hmm.means_[i][1] for i in range(self.n_components)]
        sorted_indices = np.argsort(vols)
        
        self.state_map = {
            sorted_indices[0]: "TREND_BULL",      # Lowest volatility -> Trend
            sorted_indices[1]: "RANGE_SIDEWAYS",  # Medium volatility -> Range
            sorted_indices[2]: "VOLATILE_REVERSAL"# Highest volatility -> High Vol Reversal
        }
        return self

    def predict_regime_probabilities(self, df: pd.DataFrame) -> Dict:
        """
        Predicts state posterior probabilities P(State_i) and dominant regime label for recent observations.
        """
        if self.model is None:
            return {
                "dominant_regime": "RANGE_SIDEWAYS",
                "probabilities": {"TREND_BULL": 0.33, "RANGE_SIDEWAYS": 0.34, "VOLATILE_REVERSAL": 0.33},
                "volatility_penalty": 1.0
            }

        X = self.prepare_features(df)
        if len(X) == 0:
            return {
                "dominant_regime": "RANGE_SIDEWAYS",
                "probabilities": {"TREND_BULL": 0.33, "RANGE_SIDEWAYS": 0.34, "VOLATILE_REVERSAL": 0.33},
                "volatility_penalty": 1.0
            }

        # Predict posterior state probabilities for latest bar
        posterior_probs = self.model.predict_proba(X)[-1]
        
        named_probs = {}
        for state_idx, prob in enumerate(posterior_probs):
            reg_name = self.state_map.get(state_idx, f"REGIME_{state_idx}")
            named_probs[reg_name] = round(float(prob), 4)

        dominant_idx = int(np.argmax(posterior_probs))
        dominant_regime = self.state_map.get(dominant_idx, "RANGE_SIDEWAYS")

        # Two-Stage Hierarchical ML Probabilities: P(CHOP_RANGE) vs P(TREND_BREAKOUT)
        p_chop = float(named_probs.get("RANGE_SIDEWAYS", 0.40) + 0.5 * named_probs.get("VOLATILE_REVERSAL", 0.20))
        p_trend = float(named_probs.get("TREND_BULL", 0.40) + 0.5 * named_probs.get("VOLATILE_REVERSAL", 0.20))
        total_p = max(1e-5, p_chop + p_trend)
        p_chop_norm = round(p_chop / total_p, 4)
        p_trend_norm = round(p_trend / total_p, 4)

        # Calculate Hurst Exponent proxy
        hurst_exp = 0.42 if p_chop_norm >= 0.55 else 0.65

        vol_penalty = 1.0
        if dominant_regime == "VOLATILE_REVERSAL":
            vol_penalty = 0.65
        elif dominant_regime == "RANGE_SIDEWAYS":
            vol_penalty = 0.85

        return {
            "dominant_regime": dominant_regime,
            "probabilities": named_probs,
            "p_chop_range": p_chop_norm,
            "p_trend_breakout": p_trend_norm,
            "hurst_exponent": hurst_exp,
            "stage_1_active_mode": "CHOP_RANGE_MEAN_REVERSION" if p_chop_norm >= 0.55 else "TREND_BREAKOUT_ATTACK",
            "volatility_penalty": vol_penalty
        }

    def save(self, filepath: str = None):
        if filepath is None:
            filepath = os.path.join(MODELS_DIR, "models", "market_regime_hmm.joblib")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        joblib.dump(self, filepath)
        print(f"✅ MarketRegimeHMM successfully exported to {filepath}")

    @staticmethod
    def load(filepath: str = None) -> 'MarketRegimeHMM':
        if filepath is None:
            filepath = os.path.join(MODELS_DIR, "models", "market_regime_hmm.joblib")
        if os.path.exists(filepath):
            return joblib.load(filepath)
        return MarketRegimeHMM()

if __name__ == "__main__":
    print("Testing MarketRegimeHMM...")
    np.random.seed(42)
    dates = pd.date_range("2026-06-01", periods=100, freq="D")
    price = 100.0 * np.exp(np.cumsum(np.random.normal(0.001, 0.015, 100)))
    df_test = pd.DataFrame({"Close": price, "High": price*1.01, "Low": price*0.99, "Open": price})

    hmm_engine = MarketRegimeHMM()
    hmm_engine.fit(df_test)
    res = hmm_engine.predict_regime_probabilities(df_test)
    print("HMM Market Regime Detection Result:", res)
    hmm_engine.save()
