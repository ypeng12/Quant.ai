# backend/app/ml/lob_microstructure_ml.py
"""
Limit Order Book (LOB) & Market Microstructure Machine Learning Alpha Engine.
Based on Giacinto Paolo (GP) Saggese's (Teza Capital Management / UMD) Research Methodology:
- "Simple First": Shallow, interpretable tree models (max_depth=3) grounded in market microstructure.
- Microstructure Waves: Predicting 15-30 minute price waves from order book dynamics.
- Causal Features: Order Flow Imbalance (OFI), Microprice Drift, Queue Imbalance, Sweep Velocity.
- Overfitting Prevention: Purged K-Fold Cross Validation with Embargo to eliminate data leakage.
"""

import os
import sys
import joblib
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from lightgbm import LGBMClassifier

try:
    from app.ml.deflated_sharpe_auditor import PurgedKFoldCV
except ImportError:
    try:
        from backend.app.ml.deflated_sharpe_auditor import PurgedKFoldCV
    except ImportError:
        PurgedKFoldCV = None

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
DEFAULT_MODEL_PATH = os.path.join(MODELS_DIR, "microstructure_wave_model.joblib")


class LOBMicrostructureMLEngine:
    """
    Institutional Microstructure ML Alpha Engine processing Order Book & Order Flow dynamics.
    Predicts 15-30 minute forward wave probability and excess return.
    """
    FEATURE_COLS = [
        "feature_ofi",
        "feature_micro_drift",
        "feature_queue_imbalance",
        "feature_sweep_vel",
        "feature_vol_accel",
        "feature_wick_imbalance",
        "feature_hrt_toxic_flow"
    ]

    def __init__(self, target_horizon: int = 4):
        """
        :param target_horizon: Number of bars forward for the wave prediction horizon.
                               On 5-minute bars, horizon=4 corresponds to 20 minutes; horizon=6 is 30 minutes.
        """
        self.target_horizon = target_horizon
        self.model: Optional[LGBMClassifier] = None
        self.is_fitted: bool = False
        self.cv_metrics: Dict[str, float] = {}

    @staticmethod
    def calculate_order_flow_imbalance(df: pd.DataFrame) -> pd.Series:
        """
        Calculates Order Flow Imbalance (OFI):
        OFI = Delta(Bid_Size) - Delta(Ask_Size) conditioned on price tick changes.
        Continuous metric scaled by tanh to [-1.0, +1.0].
        """
        vol_col = "volume" if "volume" in df.columns else ("Volume" if "Volume" in df.columns else None)
        vol_series = df[vol_col] if vol_col else pd.Series(np.ones(len(df)), index=df.index)

        bid_p = df["bid_price"] if "bid_price" in df.columns else df["Close"]
        ask_p = df["ask_price"] if "ask_price" in df.columns else df["Close"] * 1.0005
        bid_v = df["bid_size"] if "bid_size" in df.columns else vol_series * 0.5
        ask_v = df["ask_size"] if "ask_size" in df.columns else vol_series * 0.5

        delta_bid_p = bid_p.diff().fillna(0.0)
        delta_ask_p = ask_p.diff().fillna(0.0)
        delta_bid_v = bid_v.diff().fillna(0.0)
        delta_ask_v = ask_v.diff().fillna(0.0)

        ofi_bid = np.where(delta_bid_p > 0, bid_v, np.where(delta_bid_p == 0, delta_bid_v, 0))
        ofi_ask = np.where(delta_ask_p < 0, ask_v, np.where(delta_ask_p == 0, delta_ask_v, 0))

        raw_ofi = pd.Series(ofi_bid - ofi_ask, index=df.index).fillna(0.0)
        norm_factor = vol_series.rolling(20, min_periods=1).mean() + 1e-6
        ofi_norm = raw_ofi / norm_factor
        return pd.Series(np.tanh(ofi_norm), index=df.index).fillna(0.0)

    @staticmethod
    def calculate_microprice_drift(df: pd.DataFrame, return_bps: bool = False) -> pd.Series:
        """
        Calculates Microprice Drift:
        P_micro = (Ask_Size * Bid_Price + Bid_Size * Ask_Price) / (Bid_Size + Ask_Size)
        Drift = (P_micro - P_mid) / P_mid
        
        When L2 depth (bid_size, ask_size) is present and distinct, computes from book depth.
        When absent (e.g. 5m OHLCV bars), uses institutional intra-bar microstructure estimator
        (Wick absorption + body flow & dynamic spread) grounded in market microstructure theory.
        """
        has_l2_depth = (
            "bid_size" in df.columns and "ask_size" in df.columns and 
            not df["bid_size"].equals(df["ask_size"])
        )
        if has_l2_depth:
            bid_p = df["bid_price"] if "bid_price" in df.columns else df["Close"]
            ask_p = df["ask_price"] if "ask_price" in df.columns else df["Close"] * 1.0005
            bid_v = df["bid_size"]
            ask_v = df["ask_size"]
            tot_v = (bid_v + ask_v).replace(0, 1.0)
            micro_price = (ask_v * bid_p + bid_v * ask_p) / tot_v
            mid_price = (bid_p + ask_p) * 0.5
            drift_relative = (micro_price - mid_price) / (mid_price + 1e-6)
        else:
            high = df["High"] if "High" in df.columns else df["Close"]
            low = df["Low"] if "Low" in df.columns else df["Close"]
            open_p = df["Open"] if "Open" in df.columns else df["Close"]
            close = df["Close"]
            candle_range = (high - low).replace(0, 1e-5)
            upper_wick = (high - np.maximum(open_p, close)) / candle_range
            lower_wick = (np.minimum(open_p, close) - low) / candle_range
            body = (close - open_p) / candle_range
            
            # Buyer support (lower wick) vs seller pressure (upper wick) + body displacement
            synthetic_queue_imb = np.clip((lower_wick - upper_wick) * 0.6 + body * 0.4, -1.0, 1.0)
            
            # Estimate institutional half-spread in relative terms (1 to 20 bps)
            half_spread_rel = np.clip((candle_range / close.replace(0, 1.0)) * 0.08, 0.0001, 0.0020)
            drift_relative = synthetic_queue_imb * half_spread_rel

        # Drift in basis points (1 bps = 0.0001)
        drift_bps = pd.Series(drift_relative * 10000.0, index=df.index).fillna(0.0)
        if return_bps:
            return drift_bps
        return pd.Series(np.tanh(drift_bps / 2.5), index=df.index).fillna(0.0)

    @staticmethod
    def calculate_sweep_velocity(df: pd.DataFrame) -> pd.Series:
        """
        Measures aggressive institutional market order sweep velocity:
        Price delta acceleration multiplied by volume expansion.
        """
        vol_col = "volume" if "volume" in df.columns else ("Volume" if "Volume" in df.columns else None)
        vol_series = df[vol_col] if vol_col else pd.Series(np.ones(len(df)), index=df.index)
        price_diff = df["Close"].diff().fillna(0.0)

        vol_mean = vol_series.rolling(20, min_periods=1).mean() + 1e-6
        vol_accel = vol_series / vol_mean
        sweep_vel = np.sign(price_diff) * np.log1p(np.abs(vol_accel - 1.0))
        return pd.Series(np.tanh(sweep_vel), index=df.index).fillna(0.0)

    def build_microstructure_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Builds complete set of 7 causal microstructure features.
        """
        df_feat = df.copy()
        df_feat["feature_ofi"] = self.calculate_order_flow_imbalance(df)
        df_feat["feature_micro_drift"] = self.calculate_microprice_drift(df, return_bps=False)
        df_feat["feature_micro_drift_bps"] = self.calculate_microprice_drift(df, return_bps=True)
        df_feat["feature_sweep_vel"] = self.calculate_sweep_velocity(df)

        vol_col = "volume" if "volume" in df.columns else ("Volume" if "Volume" in df.columns else None)
        vol_series = df[vol_col] if vol_col else pd.Series(np.ones(len(df)), index=df.index)
        vol_mean = vol_series.rolling(20, min_periods=1).mean() + 1e-6
        df_feat["feature_vol_accel"] = pd.Series(np.clip((vol_series / vol_mean) - 1.0, -2.0, 5.0), index=df.index).fillna(0.0)

        has_l2_depth = (
            "bid_size" in df.columns and "ask_size" in df.columns and 
            not df["bid_size"].equals(df["ask_size"])
        )
        if has_l2_depth:
            bid_v = df["bid_size"]
            ask_v = df["ask_size"]
            df_feat["feature_queue_imbalance"] = pd.Series((bid_v - ask_v) / (bid_v + ask_v + 1e-6), index=df.index).fillna(0.0)
        else:
            high = df["High"] if "High" in df.columns else df["Close"]
            low = df["Low"] if "Low" in df.columns else df["Close"]
            open_p = df["Open"] if "Open" in df.columns else df["Close"]
            close = df["Close"]
            candle_range = (high - low).replace(0, 1e-5)
            upper_wick = (high - np.maximum(open_p, close)) / candle_range
            lower_wick = (np.minimum(open_p, close) - low) / candle_range
            body = (close - open_p) / candle_range
            queue_imb = np.clip((lower_wick - upper_wick) * 0.6 + body * 0.4, -1.0, 1.0)
            df_feat["feature_queue_imbalance"] = pd.Series(queue_imb, index=df.index).fillna(0.0)

        # Candlestick Wick Imbalance (Price Action Counterparty absorption)
        high = df["High"] if "High" in df.columns else df["Close"]
        low = df["Low"] if "Low" in df.columns else df["Close"]
        open_p = df["Open"] if "Open" in df.columns else df["Close"]
        close = df["Close"]
        candle_range = (high - low).replace(0, 1e-5)
        upper_wick = (high - np.maximum(open_p, close)) / candle_range
        lower_wick = (np.minimum(open_p, close) - low) / candle_range
        df_feat["feature_wick_imbalance"] = pd.Series(lower_wick - upper_wick, index=df.index).fillna(0.0)

        # HRT Toxic Flow Signal: Coincidence of large OFI and aggressive Sweep Velocity
        df_feat["feature_hrt_toxic_flow"] = pd.Series(
            np.where(
                (df_feat["feature_ofi"] > 0.35) & (df_feat["feature_sweep_vel"] > 0.2), 1.0,
                np.where((df_feat["feature_ofi"] < -0.35) & (df_feat["feature_sweep_vel"] < -0.2), -1.0, 0.0)
            ),
            index=df.index
        ).fillna(0.0)

        return df_feat

    def fit(self, df: pd.DataFrame, target_horizon: Optional[int] = None) -> 'LOBMicrostructureMLEngine':
        """
        Trains shallow, highly interpretable LightGBM wave predictor (max_depth=3).
        Validates with Purged K-Fold Cross Validation (no future lookahead / overlap leakage).
        """
        if target_horizon is not None:
            self.target_horizon = target_horizon

        df_feat = self.build_microstructure_features(df)
        
        # Calculate forward wave return (15-30 min horizon)
        fwd_ret = (df_feat["Close"].shift(-self.target_horizon) - df_feat["Close"]) / df_feat["Close"]
        
        # Label: 1 if positive return covering transaction friction (> 0.08%), else 0
        df_feat["target_wave"] = (fwd_ret > 0.0008).astype(int)

        # Drop the last horizon rows which lack forward labels
        valid_mask = fwd_ret.notna()
        X = df_feat.loc[valid_mask, self.FEATURE_COLS].fillna(0.0)
        y = df_feat.loc[valid_mask, "target_wave"].values

        if len(X) < 30:
            # Fallback initialization if sample is too small
            self.model = LGBMClassifier(n_estimators=30, max_depth=3, learning_rate=0.03, verbose=-1, random_state=42)
            self.model.fit(X, y)
            self.is_fitted = True
            return self

        # Saggese Anti-Overfitting Protocol: Purged K-Fold Cross-Validation
        if PurgedKFoldCV is not None and len(X) >= 50:
            cv = PurgedKFoldCV(n_splits=5, pct_embargo=0.02)
            fold_accs = []
            for train_idx, val_idx in cv.split(X):
                X_tr, y_tr = X.iloc[train_idx], y[train_idx]
                X_va, y_va = X.iloc[val_idx], y[val_idx]
                clf = LGBMClassifier(n_estimators=50, max_depth=3, learning_rate=0.03, verbose=-1, random_state=42)
                clf.fit(X_tr, y_tr)
                preds = clf.predict(X_va)
                fold_accs.append(float(np.mean(preds == y_va)))
            self.cv_metrics["purged_cv_accuracy"] = round(float(np.mean(fold_accs)), 4)

        # Fit final model on full historical dataset
        self.model = LGBMClassifier(
            n_estimators=60,
            learning_rate=0.03,
            max_depth=3,
            subsample=0.85,
            colsample_bytree=0.85,
            random_state=42,
            verbose=-1
        )
        self.model.fit(X, y)
        self.is_fitted = True
        return self

    def predict_microstructure_alpha(self, df: pd.DataFrame) -> List[float]:
        """
        Batch prediction interface returning win probabilities for all rows in dataframe.
        """
        if df is None or df.empty:
            return []
        df_feat = self.build_microstructure_features(df)
        X = df_feat[self.FEATURE_COLS].fillna(0.0)
        if self.model is None or not self.is_fitted:
            ofi = X["feature_ofi"].values
            micro = X["feature_micro_drift"].values
            queue = X["feature_queue_imbalance"].values
            sweep = X["feature_sweep_vel"].values
            comp = ofi * 0.4 + micro * 0.3 + queue * 0.2 + sweep * 0.1
            probs = np.clip(0.50 + comp * 0.25, 0.0, 1.0)
            return [float(p) for p in probs]
        probs = self.model.predict_proba(X)
        if probs.shape[1] > 1:
            return [float(p) for p in probs[:, 1]]
        return [0.50] * len(df)

    def predict_wave_alpha(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Inference interface returning continuous wave win-rate and expected return.
        """
        if df is None or df.empty:
            return {
                "p_win_long": 0.50,
                "p_win_short": 0.50,
                "expected_wave_return_pct": 0.0,
                "alpha_ofi": 0.0,
                "alpha_micro_drift": 0.0,
                "queue_imbalance": 0.0,
                "sweep_vel": 0.0,
                "toxic_flow": 0.0
            }

        df_feat = self.build_microstructure_features(df)
        latest_row = df_feat.iloc[[-1]][self.FEATURE_COLS].fillna(0.0)

        latest_ofi = float(latest_row["feature_ofi"].iloc[0])
        latest_micro_drift = float(latest_row["feature_micro_drift"].iloc[0])
        latest_queue = float(latest_row["feature_queue_imbalance"].iloc[0])
        latest_sweep = float(latest_row["feature_sweep_vel"].iloc[0])
        latest_toxic = float(latest_row["feature_hrt_toxic_flow"].iloc[0])

        if self.model is None or not self.is_fitted:
            # High-consistency mathematical heuristic fallback if model not yet fitted
            composite_micro = (latest_ofi * 0.40) + (latest_micro_drift * 0.30) + (latest_queue * 0.20) + (latest_sweep * 0.10)
            p_win_long = float(np.clip(0.50 + composite_micro * 0.25, 0.20, 0.80))
        else:
            probs = self.model.predict_proba(latest_row)[0]
            p_win_long = float(probs[1]) if len(probs) > 1 else 0.50

        p_win_short = 1.0 - p_win_long
        atr_pct = float(df.get("ATR", df["Close"] * 0.01).iloc[-1] / df["Close"].iloc[-1] * 100.0) if "Close" in df.columns else 1.0
        expected_wave_ret = (p_win_long - 0.50) * 2.0 * atr_pct * 0.8

        return {
            "p_win_long": round(p_win_long, 4),
            "p_win_short": round(p_win_short, 4),
            "expected_wave_return_pct": round(expected_wave_ret, 3),
            "alpha_ofi": round(latest_ofi, 3),
            "alpha_micro_drift": round(latest_micro_drift, 3),
            "queue_imbalance": round(latest_queue, 3),
            "sweep_vel": round(latest_sweep, 3),
            "toxic_flow": round(latest_toxic, 3)
        }

    def save(self, filepath: str = DEFAULT_MODEL_PATH):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        joblib.dump(self, filepath)
        print(f"✅ MicrostructureWaveAlphaEngine saved to {filepath}")

    @staticmethod
    def load(filepath: str = DEFAULT_MODEL_PATH) -> 'LOBMicrostructureMLEngine':
        if os.path.exists(filepath):
            try:
                engine = joblib.load(filepath)
                return engine
            except Exception as e:
                print(f"⚠️ Failed to load MicrostructureWaveAlphaEngine from {filepath}: {e}")
        engine = LOBMicrostructureMLEngine()
        return engine


# Alias for Saggese naming convention compatibility
MicrostructureWaveAlphaEngine = LOBMicrostructureMLEngine


if __name__ == "__main__":
    print("Testing MicrostructureWaveAlphaEngine...")
    np.random.seed(42)
    n = 200
    df_test = pd.DataFrame({
        "Close": 100.0 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "Open": 100.0 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "High": 100.5 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "Low": 99.5 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "Volume": np.random.uniform(1000, 5000, n),
        "bid_size": np.random.uniform(100, 1000, n),
        "ask_size": np.random.uniform(100, 1000, n)
    })
    engine = MicrostructureWaveAlphaEngine(target_horizon=4)
    engine.fit(df_test)
    print("Purged CV Metrics:", engine.cv_metrics)
    res = engine.predict_wave_alpha(df_test)
    print("Prediction Result:", res)
    engine.save()
