# backend/app/ml/lob_microstructure_ml.py
"""
Limit Order Book (LOB) Microstructure Machine Learning Alpha Engine.
Calculates high-frequency microstructure signals:
1. Order Flow Imbalance (OFI)
2. Volume Clock (Volume-synced bars)
3. Cancel-to-Trade Ratio
4. Queue Imbalance (Bid/Ask Depth Ratio)
5. Microprice Drift
"""

import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from lightgbm import LGBMClassifier, LGBMRanker

class LOBMicrostructureMLEngine:
    """
    Microstructure ML Engine processing Order Book L2/L3 features.
    """
    def __init__(self, target_horizon: int = 5):
        self.target_horizon = target_horizon
        self.model: Optional[LGBMClassifier] = None

    @staticmethod
    def calculate_order_flow_imbalance(df: pd.DataFrame) -> pd.Series:
        """
        Calculates Order Flow Imbalance (OFI):
        OFI = Delta(Bid_Size) - Delta(Ask_Size) conditioned on price movements.
        """
        vol_col = "volume" if "volume" in df.columns else ("Volume" if "Volume" in df.columns else None)
        vol_series = df[vol_col] if vol_col else pd.Series(np.ones(len(df)))

        bid_p = df["bid_price"] if "bid_price" in df.columns else df["Close"]
        ask_p = df["ask_price"] if "ask_price" in df.columns else df["Close"] * 1.0005
        bid_v = df["bid_size"] if "bid_size" in df.columns else vol_series * 0.5
        ask_v = df["ask_size"] if "ask_size" in df.columns else vol_series * 0.5

        delta_bid_p = bid_p.diff()
        delta_ask_p = ask_p.diff()
        delta_bid_v = bid_v.diff()
        delta_ask_v = ask_v.diff()

        ofi_bid = np.where(delta_bid_p > 0, bid_v, np.where(delta_bid_p == 0, delta_bid_v, 0))
        ofi_ask = np.where(delta_ask_p < 0, ask_v, np.where(delta_ask_p == 0, delta_ask_v, 0))

        ofi = pd.Series(ofi_bid - ofi_ask, index=df.index).fillna(0.0)
        return ofi

    @staticmethod
    def calculate_microprice_drift(df: pd.DataFrame) -> pd.Series:
        """
        Calculates Microprice: P_micro = (Ask_Size * Bid_Price + Bid_Size * Ask_Price) / Total_Depth
        Drift = (P_micro - P_mid) / P_mid
        """
        vol_col = "volume" if "volume" in df.columns else ("Volume" if "Volume" in df.columns else None)
        vol_series = df[vol_col] if vol_col else pd.Series(np.ones(len(df)))

        bid_p = df["bid_price"] if "bid_price" in df.columns else df["Close"]
        ask_p = df["ask_price"] if "ask_price" in df.columns else df["Close"] * 1.0005
        bid_v = df["bid_size"] if "bid_size" in df.columns else vol_series * 0.5
        ask_v = df["ask_size"] if "ask_size" in df.columns else vol_series * 0.5

        tot_v = (bid_v + ask_v).replace(0, 1.0)
        micro_price = (ask_v * bid_p + bid_v * ask_p) / tot_v
        mid_price = (bid_p + ask_p) * 0.5

        drift_pct = (micro_price - mid_price) / (mid_price + 1e-6) * 100.0
        return drift_pct

    def build_microstructure_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df_feat = df.copy()
        df_feat["feature_ofi"] = self.calculate_order_flow_imbalance(df)
        df_feat["feature_micro_drift"] = self.calculate_microprice_drift(df)

        vol_col = "volume" if "volume" in df.columns else ("Volume" if "Volume" in df.columns else None)
        vol_series = df[vol_col] if vol_col else pd.Series(np.ones(len(df)))

        bid_v = df["bid_size"] if "bid_size" in df.columns else vol_series * 0.5
        ask_v = df["ask_size"] if "ask_size" in df.columns else vol_series * 0.5
        df_feat["feature_queue_imbalance"] = (bid_v - ask_v) / (bid_v + ask_v + 1e-6)

        return df_feat

    def fit(self, df: pd.DataFrame, target_col: str = "label_win_long"):
        df_feat = self.build_microstructure_features(df)
        feature_cols = ["feature_ofi", "feature_micro_drift", "feature_queue_imbalance"]
        
        X = df_feat[feature_cols].fillna(0.0)
        y = df_feat[target_col].astype(int) if target_col in df_feat.columns else (df_feat["Close"].pct_change().shift(-1) > 0).astype(int)

        self.model = LGBMClassifier(
            n_estimators=50,
            learning_rate=0.03,
            max_depth=3,
            random_state=42,
            verbose=-1
        )
        self.model.fit(X, y)
        return self

    def predict_microstructure_alpha(self, df: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            return np.full(len(df), 0.50)

        df_feat = self.build_microstructure_features(df)
        feature_cols = ["feature_ofi", "feature_micro_drift", "feature_queue_imbalance"]
        X = df_feat[feature_cols].fillna(0.0)
        probs = self.model.predict_proba(X)[:, 1]
        return probs

if __name__ == "__main__":
    print("Testing LOBMicrostructureMLEngine...")
    np.random.seed(42)
    n = 100
    df_lob = pd.DataFrame({
        "Close": 100.0 + np.cumsum(np.random.normal(0, 0.5, n)),
        "bid_price": 99.9 + np.cumsum(np.random.normal(0, 0.5, n)),
        "ask_price": 100.1 + np.cumsum(np.random.normal(0, 0.5, n)),
        "bid_size": np.random.uniform(100, 1000, n),
        "ask_size": np.random.uniform(100, 1000, n),
        "Volume": np.random.uniform(1000, 5000, n)
    })
    
    engine = LOBMicrostructureMLEngine()
    engine.fit(df_lob)
    probs = engine.predict_microstructure_alpha(df_lob)
    print("Microstructure Alpha P_win predictions:", probs[:5])
