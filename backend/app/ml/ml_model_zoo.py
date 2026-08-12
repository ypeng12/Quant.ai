# backend/app/ml/ml_model_zoo.py
"""
Multi-Paradigm ML Model Zoo & Ensemble Framework for Systematic Quant Alpha & Ranking.
Implements:
1. Ridge Regression Baseline (Linear Alpha Return Predictor)
2. Calibrated LightGBM Classifier (Probability P_win Estimation)
3. LGBMRanker (LambdaMART Cross-Sectional Top-Decile Ranking Model)
4. Joint Inference Engine providing predictions y_hat and uncertainty std_dev.
"""

import os
import sys
import joblib
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from sklearn.linear_model import Ridge
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, roc_auc_score
from lightgbm import LGBMClassifier, LGBMRanker

MODELS_DIR = os.path.dirname(os.path.abspath(__file__))

FEATURE_COLS = [
    "feature_rvol",
    "feature_vwap_dist_pct",
    "feature_mom_3_pct",
    "feature_mom_10_pct",
    "feature_atr_pct",
    "feature_high_to_now_pct",
    "feature_low_to_now_pct",
    "feature_session_range_pct",
    "feature_upper_wick_ratio",
    "feature_lower_wick_ratio",
    "feature_mom_decay",
    "feature_vwap_overextension"
]

class QuantMLModelZoo:
    def __init__(self):
        self.ridge_model: Optional[Ridge] = None
        self.lgbm_classifier: Optional[CalibratedClassifierCV] = None
        self.lgbm_ranker: Optional[LGBMRanker] = None
        self.feature_cols = FEATURE_COLS

    def fit_ridge_baseline(self, df: pd.DataFrame, target_col: str = "future_ret_1d_pct"):
        """Fits Ridge Linear Regression for continuous return prediction."""
        X = df[self.feature_cols].fillna(0.0)
        y = df[target_col].fillna(0.0)

        self.ridge_model = Ridge(alpha=10.0)
        self.ridge_model.fit(X, y)
        return self.ridge_model

    def fit_lgbm_classifier(self, df: pd.DataFrame, target_col: str = "label_win_long"):
        """Fits LightGBM Classifier with Sigmoid Probability Calibration."""
        X = df[self.feature_cols].fillna(0.0)
        y = df[target_col].astype(int)

        base_clf = LGBMClassifier(
            n_estimators=80,
            learning_rate=0.03,
            max_depth=4,
            num_leaves=15,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbose=-1
        )
        calibrated_clf = CalibratedClassifierCV(estimator=base_clf, method='sigmoid', cv=3)
        calibrated_clf.fit(X, y)

        self.lgbm_classifier = calibrated_clf
        return self.lgbm_classifier

    def fit_lgbm_ranker(self, df: pd.DataFrame, target_col: str = "label_win_long", group_col: str = "date"):
        """
        Fits LGBMRanker (LambdaMART) for cross-sectional ranking across daily query groups.
        """
        X = df[self.feature_cols].fillna(0.0)
        y = df[target_col].astype(int)

        if group_col in df.columns:
            group_counts = df.groupby(group_col).size().values
        else:
            group_counts = np.array([len(df)])

        ranker = LGBMRanker(
            objective="lambdarank",
            metric="ndcg",
            n_estimators=60,
            learning_rate=0.03,
            max_depth=4,
            num_leaves=15,
            random_state=42,
            verbose=-1
        )
        ranker.fit(X, y, group=group_counts)
        self.lgbm_ranker = ranker
        return self.lgbm_ranker

    def predict_joint(self, feature_df: pd.DataFrame) -> Dict:
        """
        Runs joint inference across Model Zoo.
        Returns:
            Dict containing P_win (probability), return_pred, rank_score, and prediction uncertainty (std_dev).
        """
        X = feature_df[self.feature_cols].fillna(0.0)

        # 1. Classifier P_win
        if self.lgbm_classifier is not None:
            p_win = float(self.lgbm_classifier.predict_proba(X)[0, 1])
            # Estimate prediction uncertainty std_dev across underlying estimators
            if hasattr(self.lgbm_classifier, "calibrated_classifiers_"):
                sub_preds = [c.predict_proba(X)[0, 1] for c in self.lgbm_classifier.calibrated_classifiers_]
                p_std = float(np.std(sub_preds))
            else:
                p_std = 0.05
        else:
            p_win = 0.50
            p_std = 0.10

        # 2. Ridge Continuous Return
        ret_pred = float(self.ridge_model.predict(X)[0]) if self.ridge_model is not None else 0.0

        # 3. LGBMRanker Score
        rank_score = float(self.lgbm_ranker.predict(X)[0]) if self.lgbm_ranker is not None else p_win

        return {
            "p_win": p_win,
            "p_std": round(p_std, 4),
            "return_pred_pct": round(ret_pred, 3),
            "rank_score": round(rank_score, 4)
        }

    def save_zoo(self, filepath: str = None):
        if filepath is None:
            filepath = os.path.join(MODELS_DIR, "models", "quant_ml_zoo.joblib")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        joblib.dump(self, filepath)
        print(f"✅ QuantMLModelZoo successfully exported to {filepath}")

    @staticmethod
    def load_zoo(filepath: str = None) -> 'QuantMLModelZoo':
        if filepath is None:
            filepath = os.path.join(MODELS_DIR, "models", "quant_ml_zoo.joblib")
        if os.path.exists(filepath):
            return joblib.load(filepath)
        return QuantMLModelZoo()

if __name__ == "__main__":
    print("Testing QuantMLModelZoo...")
    np.random.seed(42)
    n_samples = 200
    dates = pd.date_range("2026-08-01", periods=10, freq="D").repeat(20)

    synthetic_data = {
        "date": dates,
        "feature_rvol": np.random.uniform(0.5, 3.0, n_samples),
        "feature_vwap_dist_pct": np.random.normal(0, 1.5, n_samples),
        "feature_mom_3_pct": np.random.normal(0, 2.0, n_samples),
        "feature_mom_10_pct": np.random.normal(0, 4.0, n_samples),
        "feature_atr_pct": np.random.uniform(1.0, 3.5, n_samples),
        "feature_high_to_now_pct": np.random.uniform(-3.0, 0.0, n_samples),
        "feature_low_to_now_pct": np.random.uniform(0.0, 3.0, n_samples),
        "feature_session_range_pct": np.random.uniform(1.0, 4.0, n_samples),
        "future_ret_1d_pct": np.random.normal(0.1, 1.2, n_samples),
        "label_win_long": np.random.choice([0, 1], size=n_samples, p=[0.7, 0.3])
    }
    df_test = pd.DataFrame(synthetic_data)

    zoo = QuantMLModelZoo()
    zoo.fit_ridge_baseline(df_test)
    zoo.fit_lgbm_classifier(df_test)
    zoo.fit_lgbm_ranker(df_test)

    sample_feat = df_test.iloc[[0]][FEATURE_COLS]
    res = zoo.predict_joint(sample_feat)
    print("Joint Model Zoo Predictions:", res)
    zoo.save_zoo()
