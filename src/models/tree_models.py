import pandas as pd
import numpy as np
from typing import List, Optional, Dict, Any


class LightGBMModel:
    """
    Tree Model 1: LightGBM Regressor / Ranker with constrained depth to prevent overfitting.
    Falls back gracefully to sklearn HistGradientBoostingRegressor if lightgbm is not installed.
    """

    def __init__(
        self,
        max_depth: int = 3,
        num_leaves: int = 7,
        learning_rate: float = 0.01,
        n_estimators: int = 500,
        mode: str = "regressor",
    ):
        self.max_depth = max_depth
        self.num_leaves = num_leaves
        self.learning_rate = learning_rate
        self.n_estimators = n_estimators
        self.mode = mode
        self.model = None

    def fit(self, df: pd.DataFrame, feature_cols: List[str], target_col: str):
        clean_df = df[feature_cols + [target_col, "date"]].dropna()
        if len(clean_df) < 50:
            return

        X = clean_df[feature_cols]
        y = clean_df[target_col]

        try:
            import lightgbm as lgb
            if self.mode == "ranker":
                clean_df = clean_df.sort_values("date")
                group_sizes = clean_df.groupby("date").size().values
                y_quant = clean_df.groupby("date")[target_col].transform(
                    lambda s: pd.qcut(s.rank(method="first"), 5, labels=False)
                )

                self.model = lgb.LGBMRanker(
                    max_depth=self.max_depth,
                    num_leaves=self.num_leaves,
                    learning_rate=self.learning_rate,
                    n_estimators=self.n_estimators,
                    subsample=0.7,
                    colsample_bytree=0.7,
                    random_state=42,
                    verbosity=-1,
                )
                self.model.fit(clean_df[feature_cols], y_quant, group=group_sizes)
            else:
                self.model = lgb.LGBMRegressor(
                    max_depth=self.max_depth,
                    num_leaves=self.num_leaves,
                    learning_rate=self.learning_rate,
                    n_estimators=self.n_estimators,
                    subsample=0.7,
                    colsample_bytree=0.7,
                    random_state=42,
                    verbosity=-1,
                )
                self.model.fit(X, y)
        except ImportError:
            # Fallback to sklearn HistGradientBoostingRegressor
            from sklearn.ensemble import HistGradientBoostingRegressor
            self.model = HistGradientBoostingRegressor(
                max_depth=self.max_depth,
                learning_rate=self.learning_rate,
                max_iter=min(200, self.n_estimators),
                random_state=42,
            )
            self.model.fit(X, y)

    def predict(self, df: pd.DataFrame, feature_cols: List[str]) -> pd.Series:
        if self.model is None:
            return pd.Series(0.0, index=df.index)

        X = df[feature_cols].fillna(0.0)
        preds = self.model.predict(X)
        return pd.Series(preds, index=df.index)

    def feature_importances(self, feature_cols: List[str]) -> Dict[str, float]:
        if self.model is None:
            return {}
        if hasattr(self.model, "feature_importances_"):
            imp = self.model.feature_importances_
            total = float(imp.sum()) + 1e-8
            return {f: float(i / total) for f, i in zip(feature_cols, imp)}
        return {f: 1.0 / len(feature_cols) for f in feature_cols}


class XGBoostModel:
    """
    Tree Model 2: XGBoost Regressor with L2 regularization.
    Falls back gracefully to sklearn GradientBoostingRegressor if xgboost is not installed.
    """

    def __init__(
        self,
        max_depth: int = 3,
        learning_rate: float = 0.01,
        n_estimators: int = 500,
        reg_lambda: float = 1.0,
    ):
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.n_estimators = n_estimators
        self.reg_lambda = reg_lambda
        self.model = None

    def fit(self, df: pd.DataFrame, feature_cols: List[str], target_col: str):
        clean_df = df[feature_cols + [target_col]].dropna()
        if len(clean_df) < 50:
            return

        X = clean_df[feature_cols]
        y = clean_df[target_col]

        try:
            import xgboost as xgb
            self.model = xgb.XGBRegressor(
                max_depth=self.max_depth,
                learning_rate=self.learning_rate,
                n_estimators=self.n_estimators,
                reg_lambda=self.reg_lambda,
                subsample=0.7,
                colsample_bytree=0.7,
                random_state=42,
                verbosity=0,
            )
            self.model.fit(X, y)
        except ImportError:
            from sklearn.ensemble import GradientBoostingRegressor
            self.model = GradientBoostingRegressor(
                max_depth=self.max_depth,
                learning_rate=self.learning_rate,
                n_estimators=min(200, self.n_estimators),
                subsample=0.7,
                random_state=42,
            )
            self.model.fit(X, y)

    def predict(self, df: pd.DataFrame, feature_cols: List[str]) -> pd.Series:
        if self.model is None:
            return pd.Series(0.0, index=df.index)

        X = df[feature_cols].fillna(0.0)
        preds = self.model.predict(X)
        return pd.Series(preds, index=df.index)
