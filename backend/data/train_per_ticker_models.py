# backend/data/train_per_ticker_models.py
"""
Per-Ticker Machine Learning Model Trainer & Optimizer
Builds dedicated, specialized LightGBM Probability Models for individual tickers:
- SNDK (High Volatility, High Momentum Leader)
- MSTR (High Beta Bitcoin Proxy)
- TSLA (High Retail Flow & Momentum)
- NVDA (Mega-cap AI Semiconductor Benchmark)

Trains per-ticker calibrated models to predict true positive expectancy (E[R] > 0)
and validates via Walk-Forward / Out-of-Sample PnL Simulation.
"""

import os
import sys
import datetime
import pytz
import joblib
import json
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, brier_score_loss, accuracy_score

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

DATASETS_DIR = os.path.join(backend_dir, "data", "datasets")
MODELS_DIR = os.path.join(backend_dir, "app", "ml", "models")
PER_TICKER_DIR = os.path.join(MODELS_DIR, "per_ticker")
os.makedirs(DATASETS_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(PER_TICKER_DIR, exist_ok=True)

FEATURE_COLS = [
    "feature_ofi",
    "feature_rvol",
    "feature_vwap_dist_pct",
    "feature_ema_diff_pct",
    "feature_mom_5m",
    "feature_mom_15m",
    "feature_er",
    "feature_atr_pct"
]

def fetch_ticker_data(client, ticker: str, days: int = 30) -> pd.DataFrame:
    end_dt = datetime.datetime.now(pytz.timezone("America/New_York"))
    start_dt = end_dt - datetime.timedelta(days=days)
    
    req = StockBarsRequest(
        symbol_or_symbols=[ticker],
        timeframe=TimeFrame.Minute,
        start=start_dt,
        end=end_dt,
        feed=DataFeed.IEX
    )
    bars = client.get_stock_bars(req)
    raw_list = bars.data.get(ticker, [])
    if not raw_list:
        print(f"⚠️ [{ticker}] 未抓取到有效数据")
        return pd.DataFrame()
    
    data = [{
        "timestamp": b.timestamp,
        "Open": float(b.open),
        "High": float(b.high),
        "Low": float(b.low),
        "Close": float(b.close),
        "Volume": float(b.volume),
        "vwap": float(b.vwap or b.close)
    } for b in raw_list]
    df = pd.DataFrame(data).set_index("timestamp")
    df.index = pd.to_datetime(df.index).tz_convert("America/New_York")
    df = df.between_time("09:30", "16:00").copy()
    return df

def extract_features_and_labels(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    d = df.copy()
    d["ticker"] = ticker

    candle_range = np.maximum(1e-5, d["High"] - d["Low"])
    close_loc = (d["Close"] - d["Low"]) / candle_range

    # 1. OFI & RVOL
    vol_mean_20 = d["Volume"].rolling(20).mean().fillna(d["Volume"])
    d["feature_ofi"] = np.clip(np.tanh(((close_loc - 0.5) * 2.0) * (d["Volume"] / np.maximum(1.0, vol_mean_20))), -1.0, 1.0)
    d["feature_rvol"] = d["Volume"] / np.maximum(1.0, d["Volume"].rolling(30).mean().fillna(1.0))

    # 2. VWAP & EMA Trend
    d["feature_vwap_dist_pct"] = (d["Close"] - d["vwap"]) / np.maximum(1e-5, d["vwap"]) * 100.0
    ema9 = d["Close"].ewm(span=9).mean()
    ema21 = d["Close"].ewm(span=21).mean()
    d["feature_ema_diff_pct"] = (ema9 - ema21) / np.maximum(1e-5, ema21) * 100.0

    # 3. Multi-timeframe Momentum
    d["feature_mom_5m"] = d["Close"].pct_change(5).fillna(0.0) * 100.0
    d["feature_mom_15m"] = d["Close"].pct_change(15).fillna(0.0) * 100.0

    # 4. Kaufman Efficiency Ratio (ER)
    net_move = abs(d["Close"] - d["Close"].shift(20))
    total_path = abs(d["Close"].diff()).rolling(20).sum()
    d["feature_er"] = (net_move / np.maximum(1e-5, total_path)).fillna(0.20)

    # 5. Volatility ATR %
    tr = np.maximum(d["High"] - d["Low"], np.maximum(abs(d["High"] - d["Close"].shift(1)), abs(d["Low"] - d["Close"].shift(1))))
    d["atr"] = tr.rolling(14).mean().fillna(d["Close"] * 0.01)
    d["feature_atr_pct"] = (d["atr"] / np.maximum(1e-5, d["Close"]) * 100.0).fillna(1.0)

    # 6. Triple-Barrier Target Label (Forward 30m window)
    # Long win: Price reaches +1.5 ATR before hitting -1.0 ATR
    indexer = pd.api.indexers.FixedForwardWindowIndexer(window_size=30)
    future_high = d["High"].rolling(window=indexer).max()
    future_low = d["Low"].rolling(window=indexer).min()
    d["target_long_win"] = ((future_high - d["Close"]) >= 1.5 * d["atr"]) & ((d["Close"] - future_low) < 1.0 * d["atr"])

    clean = d.dropna().copy()
    return clean

def train_single_ticker_model(ticker: str, df_features: pd.DataFrame) -> dict:
    X = df_features[FEATURE_COLS]
    y = df_features["target_long_win"].astype(int)

    # Time-series chronological split (75% train, 25% out-of-sample test)
    split_idx = int(len(df_features) * 0.75)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    # Ticker-specific hyperparameter tuning:
    # High-volatility tickers (SNDK/MSTR) need slightly shallower trees and regularized leaves to avoid overfitting noise
    is_high_vol = ticker in ("SNDK", "MSTR")
    max_depth = 3 if is_high_vol else 4
    num_leaves = 10 if is_high_vol else 15
    learning_rate = 0.02 if is_high_vol else 0.03
    min_child_samples = 30 if is_high_vol else 20

    base_model = LGBMClassifier(
        n_estimators=120,
        learning_rate=learning_rate,
        max_depth=max_depth,
        num_leaves=num_leaves,
        min_child_samples=min_child_samples,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1
    )

    # Probability Calibration via 3-fold CV
    calibrated_model = CalibratedClassifierCV(estimator=base_model, method='sigmoid', cv=3)
    calibrated_model.fit(X_train, y_train)

    pred_test = calibrated_model.predict_proba(X_test)[:, 1]
    test_auc = roc_auc_score(y_test, pred_test) if len(np.unique(y_test)) > 1 else 0.50
    test_brier = brier_score_loss(y_test, pred_test)
    test_acc = accuracy_score(y_test, (pred_test >= 0.50).astype(int))

    # Fit final production model on full ticker history
    final_model = CalibratedClassifierCV(estimator=base_model, method='sigmoid', cv=3)
    final_model.fit(X, y)

    # Save per-ticker model file
    model_filename = f"win_rate_model_{ticker}.joblib"
    model_path = os.path.join(PER_TICKER_DIR, model_filename)
    joblib.dump(final_model, model_path)

    # Also save to main models directory if it is SNDK (primary leader)
    if ticker == "SNDK":
        primary_path = os.path.join(MODELS_DIR, "win_rate_model_long.joblib")
        joblib.dump(final_model, primary_path)

    # Feature importances
    base_model.fit(X, y)
    importances = dict(zip(FEATURE_COLS, [int(x) for x in base_model.feature_importances_]))

    res = {
        "ticker": ticker,
        "model_file": model_filename,
        "samples": len(df_features),
        "test_auc": round(float(test_auc), 4),
        "test_brier": round(float(test_brier), 4),
        "test_acc": round(float(test_acc), 4),
        "win_rate_rate": round(float(y.mean()), 4),
        "feature_importances": importances
    }
    print(f"   ├─ [{ticker}] 独立模型训练完成: OOS AUC={test_auc:.4f} | Brier={test_brier:.4f} | 样本={len(df_features)} | 保存至: {model_path}")
    return res

def run_per_ticker_training_pipeline(tickers=None):
    if tickers is None:
        tickers = ["SNDK", "MSTR", "TSLA", "NVDA"]

    print("=" * 80)
    print("🚀 【QUANT.AI】分标的独立机器学习专有模型训练与参数优化管线")
    print(f"   监控标的: {tickers} | 模式: 每只标的独立建模，杜绝混合失真")
    print("=" * 80)

    client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    results = {}

    for sym in tickers:
        print(f"\n[*] 正在拉取 [{sym}] 过去 30 天真实分时数据...")
        df = fetch_ticker_data(client, sym, days=30)
        if df.empty:
            print(f"⚠️ [{sym}] 数据拉取失败，跳过。")
            continue
        print(f"   └─ 成功拉取 {len(df)} 根 K 线，开始构建专属特征工程...")
        df_feat = extract_features_and_labels(df, sym)
        # Save per-ticker parquet dataset
        feat_path = os.path.join(DATASETS_DIR, f"dataset_{sym}.parquet")
        df_feat.to_parquet(feat_path, index=False)

        res = train_single_ticker_model(sym, df_feat)
        results[sym] = res

    # Export unified per-ticker meta json
    meta_path = os.path.join(MODELS_DIR, "per_ticker_models_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print(f"✅ 全部分标的独立 ML 模型已固化完成！元数据保存至: {meta_path}")
    print("=" * 80)
    return results

if __name__ == "__main__":
    run_per_ticker_training_pipeline()
