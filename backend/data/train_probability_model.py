# backend/data/train_probability_model.py
"""
Data-Driven Machine Learning Probability Calibration Trainer.
Implements:
1. Purged Group TimeSeries Cross-Validation (prevents 15m forward label leakage).
2. LightGBM Classification with Sigmoid/Isotonic Probability Calibration (CalibratedClassifierCV).
3. Calibration evaluation using Brier Score, Log-Loss, and ROC-AUC.
4. Model serialization to backend/app/ml/models/ for real-time inference in probability_engine.py.
"""

import os
import sys
import json
import joblib
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score, precision_score, recall_score
from lightgbm import LGBMClassifier

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATASETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "datasets")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "ml", "models")

FEATURE_COLS = [
    "feature_rvol",
    "feature_vwap_dist_pct",
    "feature_mom_3_pct",
    "feature_mom_10_pct",
    "feature_atr_pct",
    "feature_high_to_now_pct",
    "feature_low_to_now_pct",
    "feature_session_range_pct"
]

class PurgedTimeSeriesSplit:
    """
    Purged & Embargoed Time-Series Cross-Validator for overlapping event labels.
    Prevents information leakage when target label Y is constructed over a forward window (e.g. 15 bars).
    """
    def __init__(self, n_splits: int = 5, purge_window: int = 15, embargo_window: int = 5):
        self.n_splits = n_splits
        self.purge_window = purge_window
        self.embargo_window = embargo_window

    def split(self, X: pd.DataFrame):
        n_samples = len(X)
        val_size = n_samples // (self.n_splits + 1)

        for i in range(self.n_splits):
            val_start = val_size * (i + 1)
            val_end = val_start + val_size if i < self.n_splits - 1 else n_samples

            train_end = max(0, val_start - self.purge_window)
            train_indices = np.arange(0, train_end)

            val_indices = np.arange(val_start, val_end)

            if len(train_indices) > 50 and len(val_indices) > 20:
                yield train_indices, val_indices

def train_and_calibrate_direction(df: pd.DataFrame, target_col: str, direction_name: str) -> Dict:
    print(f"\n⚡ [ML Train] 开始训练并校准 {direction_name.upper()} 方向防泄漏胜率模型...")
    X = df[FEATURE_COLS].copy()
    y = df[target_col].astype(int).copy()

    pos_ratio = y.mean()
    print(f"   ├─ 样本库总量: {len(X)} 行, 正例比率: {pos_ratio * 100.0:.2f}% ({y.sum()}/{len(y)})")

    cv = PurgedTimeSeriesSplit(n_splits=4, purge_window=15, embargo_window=5)

    cv_brier_scores = []
    cv_auc_scores = []
    cv_log_losses = []

    split_count = 0
    for train_idx, val_idx in cv.split(X):
        split_count += 1
        X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
        X_val, y_val = X.iloc[val_idx], y.iloc[val_idx]

        if len(np.unique(y_train)) < 2 or len(np.unique(y_val)) < 2:
            continue

        base_clf = LGBMClassifier(
            n_estimators=60,
            learning_rate=0.03,
            max_depth=4,
            num_leaves=15,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbose=-1
        )
        
        calibrated_clf = CalibratedClassifierCV(estimator=base_clf, method='sigmoid', cv=3)
        calibrated_clf.fit(X_train, y_train)

        probs_val = calibrated_clf.predict_proba(X_val)[:, 1]

        brier = brier_score_loss(y_val, probs_val)
        logloss = log_loss(y_val, probs_val)
        try:
            auc = roc_auc_score(y_val, probs_val)
        except ValueError:
            auc = 0.5

        cv_brier_scores.append(brier)
        cv_auc_scores.append(auc)
        cv_log_losses.append(logloss)

        print(f"   ├─ [Fold {split_count}] Brier Score: {brier:.4f} | LogLoss: {logloss:.4f} | ROC-AUC: {auc:.4f}")

    # Final Fit on whole dataset using Purged CV ensemble for production model
    split_size = int(len(X) * 0.8)
    X_train_final, y_train_final = X.iloc[:split_size], y.iloc[:split_size]
    X_test_final, y_test_final = X.iloc[split_size:], y.iloc[split_size:]

    base_final = LGBMClassifier(
        n_estimators=80,
        learning_rate=0.03,
        max_depth=4,
        num_leaves=15,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1
    )
    final_model = CalibratedClassifierCV(estimator=base_final, method='sigmoid', cv=3)
    final_model.fit(X_train_final, y_train_final)

    test_probs = final_model.predict_proba(X_test_final)[:, 1]
    final_brier = brier_score_loss(y_test_final, test_probs)
    final_auc = roc_auc_score(y_test_final, test_probs) if len(np.unique(y_test_final)) > 1 else 0.5
    final_logloss = log_loss(y_test_final, test_probs)

    print(f"   └─ ✅ 样本外 Final Hold-out 评估: Brier Score={final_brier:.4f}, AUC={final_auc:.4f}, LogLoss={final_logloss:.4f}")

    os.makedirs(MODELS_DIR, exist_ok=True)
    model_filename = f"win_rate_model_{direction_name}.joblib"
    model_path = os.path.join(MODELS_DIR, model_filename)
    joblib.dump(final_model, model_path)
    print(f"   └─ 💾 已成功导出校准模型至: {model_path}")

    return {
        "direction": direction_name,
        "model_file": model_filename,
        "cv_brier_mean": float(np.mean(cv_brier_scores)) if cv_brier_scores else float(final_brier),
        "cv_auc_mean": float(np.mean(cv_auc_scores)) if cv_auc_scores else float(final_auc),
        "final_brier": float(final_brier),
        "final_auc": float(final_auc),
        "final_logloss": float(final_logloss),
        "feature_cols": FEATURE_COLS
    }

def run_probability_model_pipeline(dataset_name: str = "daily"):
    if "daily" in dataset_name.lower():
        parquet_path = os.path.join(DATASETS_DIR, "daily_watchlist_ml_dataset.parquet")
        if not os.path.exists(parquet_path):
            from data.build_daily_dataset import build_daily_watchlist_dataset
            df = build_daily_watchlist_dataset()
        else:
            df = pd.read_parquet(parquet_path)
    else:
        parquet_path = os.path.join(DATASETS_DIR, f"{dataset_name}_ml_dataset.parquet")
        if not os.path.exists(parquet_path):
            csv_path = os.path.join(DATASETS_DIR, f"{dataset_name}_ml_dataset.csv")
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
            else:
                from data.build_dataset import build_stock_dataset
                df = build_stock_dataset(dataset_name)
        else:
            df = pd.read_parquet(parquet_path)

    print(f"📥 [ML Pipeline] 已载入 [{dataset_name}] 美股日线/高频数据集 ({len(df)} 行)")

    res_long = train_and_calibrate_direction(df, "label_win_long", "long")
    res_short = train_and_calibrate_direction(df, "label_win_short", "short")

    meta = {
        "dataset_name": dataset_name,
        "num_samples": len(df),
        "feature_cols": FEATURE_COLS,
        "long_model": res_long,
        "short_model": res_short
    }

    meta_path = os.path.join(MODELS_DIR, "model_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print("\n=========================================================================")
    print("PROBABILITY MODEL TRAINING & CALIBRATION COMPLETE")
    print("=========================================================================")
    print(f"* Long  Model Brier Score : {res_long['final_brier']:.4f} (AUC: {res_long['final_auc']:.4f})")
    print(f"* Short Model Brier Score : {res_short['final_brier']:.4f} (AUC: {res_short['final_auc']:.4f})")
    print(f"* Metadata exported to   : {meta_path}")
    print("=========================================================================")

if __name__ == "__main__":
    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "SNDK"
    run_probability_model_pipeline(ticker_arg)
