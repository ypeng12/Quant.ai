# backend/data/train_daytrade_model.py
"""
Train & Calibrate Day Trading 5-Minute Intraday Win Probability Model.
Trains LightGBM Classifier with Platt Scaling (CalibratedClassifierCV) on 5m intraday features,
saving the calibrated model to backend/app/ml/models/daytrade_win_rate_model.joblib.
"""

import os
import sys
import joblib
import pandas as pd
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.metrics import brier_score_loss, roc_auc_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "ml", "models")
DATASETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets")
os.makedirs(MODELS_DIR, exist_ok=True)

FEATURE_COLS_5M = [
    "feature_rvol_5m",
    "feature_vwap_dist_pct",
    "feature_mom_5m_pct",
    "feature_mom_15m_pct",
    "feature_atr_pct",
    "feature_range_to_atr",
    "feature_body_ratio",
    "feature_upper_shadow_ratio",
    "feature_lower_shadow_ratio",
    "feature_high_dist_session",
    "feature_low_dist_session",
    "feature_pdh_dist_pct",
    "feature_pdl_dist_pct"
]

def train_daytrade_model():
    print("=========================================================================")
    print("TRAINING & CALIBRATING 5M INTRADAY DAY TRADING ML WIN RATE MODEL")
    print("=========================================================================")
    
    dataset_path = os.path.join(DATASETS_DIR, "intraday_5m_watchlist_dataset.parquet")
    if not os.path.exists(dataset_path):
        from build_intraday_5m_dataset import build_intraday_5m_watchlist_dataset
        df = build_intraday_5m_watchlist_dataset()
    else:
        df = pd.read_parquet(dataset_path)

    print(f"[*] Total 5m Intraday Samples: {len(df)} rows")
    X = df[FEATURE_COLS_5M].fillna(0.0)
    y = df["label_win_daytrade_long"].astype(int)

    base_lgbm = LGBMClassifier(
        n_estimators=100,
        learning_rate=0.03,
        max_depth=4,
        num_leaves=15,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=-1
    )

    print("[*] Performing Platt Scaling Probability Calibration (Sigmoid Cross-Validation)...")
    calibrated_clf = CalibratedClassifierCV(estimator=base_lgbm, method="sigmoid", cv=5)
    calibrated_clf.fit(X, y)

    # Evaluate Calibration & Brier Score
    probs = calibrated_clf.predict_proba(X)[:, 1]
    brier = brier_score_loss(y, probs)
    try:
        auc = roc_auc_score(y, probs)
    except Exception:
        auc = 0.5

    print(f"✅ Calibration Completed: Brier Score = {brier:.4f} (Ideal < 0.15), AUC = {auc:.4f}")

    model_save_path = os.path.join(MODELS_DIR, "daytrade_win_rate_model.joblib")
    joblib.dump(calibrated_clf, model_save_path)
    print(f"✅ Model saved to: {model_save_path}")
    print("=========================================================================")

if __name__ == "__main__":
    train_daytrade_model()
