import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from sklearn.linear_model import Ridge, LogisticRegression


class RawMomentumBaseline:
    """Baseline 1: Standard 20-day return cross-sectional ranking."""

    def __init__(self, lookback_col: str = "mom_20d"):
        self.lookback_col = lookback_col

    def fit(self, df: pd.DataFrame, target_col: str):
        pass

    def predict(self, df: pd.DataFrame) -> pd.Series:
        if self.lookback_col in df.columns:
            return df[self.lookback_col].fillna(0.0)
        return df["adjusted_close"].pct_change(20).fillna(0.0)


class VolAdjMomentumBaseline:
    """Baseline 2: Volatility-Adjusted Cross-Sectional Momentum (Return_20d / Vol_20d)."""

    def __init__(self, feature_col: str = "vol_adj_mom_20d"):
        self.feature_col = feature_col

    def fit(self, df: pd.DataFrame, target_col: str):
        pass

    def predict(self, df: pd.DataFrame) -> pd.Series:
        if self.feature_col in df.columns:
            return df[self.feature_col].fillna(0.0)
        return df["adjusted_close"].pct_change(20) / (df["adjusted_close"].pct_change(1).std() * np.sqrt(252) + 1e-6)


class LinearRidgeModel:
    """Linear Model 1: Ridge Regression with L2 Regularization."""

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.model = Ridge(alpha=alpha)

    def fit(self, df: pd.DataFrame, feature_cols: list, target_col: str):
        clean_df = df[feature_cols + [target_col]].dropna()
        if len(clean_df) > 10:
            self.model.fit(clean_df[feature_cols], clean_df[target_col])

    def predict(self, df: pd.DataFrame, feature_cols: list) -> pd.Series:
        X = df[feature_cols].fillna(0.0)
        return pd.Series(self.model.predict(X), index=df.index)


class LogisticClassificationModel:
    """Linear Model 2: L2 Regularized Logistic Regression for Top Quantile Classification."""

    def __init__(self, C: float = 1.0):
        self.C = C
        self.model = LogisticRegression(C=C, max_iter=500)

    def fit(self, df: pd.DataFrame, feature_cols: list, target_col: str):
        clean_df = df[feature_cols + [target_col]].dropna()
        if len(clean_df) > 10:
            self.model.fit(clean_df[feature_cols], clean_df[target_col])

    def predict(self, df: pd.DataFrame, feature_cols: list) -> pd.Series:
        X = df[feature_cols].fillna(0.0)
        probs = self.model.predict_proba(X)[:, 1]
        return pd.Series(probs, index=df.index)
