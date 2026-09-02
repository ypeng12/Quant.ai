# backend/data/build_recent_2w_dataset.py
"""
Builds a fresh, leak-free, multi-asset 2-week high-frequency dataset directly from Alpaca IEX,
trains calibrated LightGBM Probability Models (Long & Short),
and exports models to backend/app/ml/models/ for live trading inference.
"""

import os
import sys
import datetime
import pytz
import joblib
import json
import pandas as pd
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss

# Ensure backend root is in sys.path
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
os.makedirs(DATASETS_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

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

def build_and_train_2w_pipeline(tickers=None):
    if tickers is None:
        tickers = ["NVDA", "TSLA", "MSTR", "SNDK"]

    print("=" * 80)
    print("🚀 【QUANT.AI】近 2 周全美股多资产高频真实数据集构建与 ML 模型训练管线")
    print(f"   监控标的: {tickers} | 数据源: Alpaca 官方交易所 IEX 分钟线")
    print("=" * 80)

    # 1. Fetch 2-week 1m bars from Alpaca
    client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    end_dt = datetime.datetime.now(pytz.timezone("America/New_York"))
    start_dt = end_dt - datetime.timedelta(days=14)

    req = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=TimeFrame.Minute,
        start=start_dt,
        end=end_dt,
        feed=DataFeed.IEX
    )
    bars = client.get_stock_bars(req)

    dfs = {}
    for sym in tickers:
        raw_list = bars.data.get(sym, [])
        if not raw_list:
            print(f"⚠️ {sym}: 未抓取到有效数据")
            continue
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
        dfs[sym] = df
        print(f"   ├─ [{sym}] 成功拉取 {len(df)} 根常规交易时段 1分钟 K线 ({df.index[0].strftime('%Y-%m-%d')} 至 {df.index[-1].strftime('%Y-%m-%d')})")

    # 2. Extract Features & Triple-Barrier Labels
    feature_dfs = []
    for sym, df in dfs.items():
        d = df.copy()
        d["ticker"] = sym

        candle_range = np.maximum(1e-5, d["High"] - d["Low"])
        close_loc = (d["Close"] - d["Low"]) / candle_range

        # 1. OFI & RVOL
        vol_mean_20 = d["Volume"].rolling(20).mean().fillna(d["Volume"])
        d["feature_ofi"] = np.clip(np.tanh(((close_loc - 0.5) * 2.0) * (d["Volume"] / vol_mean_20)), -1.0, 1.0)
        d["feature_rvol"] = d["Volume"] / d["Volume"].rolling(30).mean().fillna(1.0)

        # 2. VWAP & EMA trend
        d["feature_vwap_dist_pct"] = (d["Close"] - d["vwap"]) / d["vwap"] * 100.0
        ema9 = d["Close"].ewm(span=9).mean()
        ema21 = d["Close"].ewm(span=21).mean()
        d["feature_ema_diff_pct"] = (ema9 - ema21) / ema21 * 100.0

        # 3. Multi-timeframe Momentum
        d["feature_mom_5m"] = d["Close"].pct_change(5) * 100.0
        d["feature_mom_15m"] = d["Close"].pct_change(15) * 100.0

        # 4. Kaufman Efficiency Ratio (ER)
        net_move = abs(d["Close"] - d["Close"].shift(20))
        total_path = abs(d["Close"].diff()).rolling(20).sum()
        d["feature_er"] = net_move / np.maximum(1e-5, total_path)

        # 5. Volatility ATR %
        tr = np.maximum(d["High"] - d["Low"], np.maximum(abs(d["High"] - d["Close"].shift(1)), abs(d["Low"] - d["Close"].shift(1))))
        d["atr"] = tr.rolling(14).mean()
        d["feature_atr_pct"] = d["atr"] / d["Close"] * 100.0

        # 6. Triple-Barrier Target Label (Forward 30m window)
        indexer = pd.api.indexers.FixedForwardWindowIndexer(window_size=30)
        future_high = d["High"].rolling(window=indexer).max()
        future_low = d["Low"].rolling(window=indexer).min()
        d["target_long_win"] = ((future_high - d["Close"]) >= 1.5 * d["atr"]) & ((d["Close"] - future_low) < 1.0 * d["atr"])
        d["target_short_win"] = ((d["Close"] - future_low) >= 1.5 * d["atr"]) & ((future_high - d["Close"]) < 1.0 * d["atr"])

        clean = d.dropna().copy()
        feature_dfs.append(clean)

    total_df = pd.concat(feature_dfs, ignore_index=True)
    parquet_path = os.path.join(DATASETS_DIR, "recent_2w_multi_asset_dataset.parquet")
    total_df.to_parquet(parquet_path, index=False)
    print(f"\n✅ [1/3] 2周全量数据集已保存至: {parquet_path}")
    print(f"   └─ 样本总量: {len(total_df):,} 行 | 多头正例率: {total_df['target_long_win'].mean()*100:.1f}% | 空头正例率: {total_df['target_short_win'].mean()*100:.1f}%")

    # 3. Train Calibrated LightGBM Models for Long and Short
    print("\n⚡ [2/3] 开始训练与校准新一代 LightGBM 概率预测大脑...")
    X = total_df[FEATURE_COLS]
    y_long = total_df["target_long_win"].astype(int)
    y_short = total_df["target_short_win"].astype(int)

    split_idx = int(len(total_df) * 0.75)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train_l, y_test_l = y_long.iloc[:split_idx], y_long.iloc[split_idx:]
    y_train_s, y_test_s = y_short.iloc[:split_idx], y_short.iloc[split_idx:]

    # Long Model
    base_long = LGBMClassifier(n_estimators=100, learning_rate=0.03, max_depth=4, num_leaves=15, subsample=0.8, colsample_bytree=0.8, random_state=42, verbose=-1)
    calib_long = CalibratedClassifierCV(estimator=base_long, method='sigmoid', cv=3)
    calib_long.fit(X_train, y_train_l)
    pred_test_l = calib_long.predict_proba(X_test)[:, 1]
    auc_l = roc_auc_score(y_test_l, pred_test_l)
    brier_l = brier_score_loss(y_test_l, pred_test_l)

    # Short Model
    base_short = LGBMClassifier(n_estimators=100, learning_rate=0.03, max_depth=4, num_leaves=15, subsample=0.8, colsample_bytree=0.8, random_state=42, verbose=-1)
    calib_short = CalibratedClassifierCV(estimator=base_short, method='sigmoid', cv=3)
    calib_short.fit(X_train, y_train_s)
    pred_test_s = calib_short.predict_proba(X_test)[:, 1]
    auc_s = roc_auc_score(y_test_s, pred_test_s)
    brier_s = brier_score_loss(y_test_s, pred_test_s)

    print(f"   ├─ 做多模型 (Long Model)  : 样本外 AUC = {auc_l:.4f} | Brier Score = {brier_l:.4f}")
    print(f"   └─ 做空模型 (Short Model) : 样本外 AUC = {auc_s:.4f} | Brier Score = {brier_s:.4f}")

    # Final Fit on entire 2-week dataset for maximum production power
    final_long = CalibratedClassifierCV(estimator=base_long, method='sigmoid', cv=3)
    final_long.fit(X, y_long)

    final_short = CalibratedClassifierCV(estimator=base_short, method='sigmoid', cv=3)
    final_short.fit(X, y_short)

    # 4. Save Production Models & Metadata
    long_path = os.path.join(MODELS_DIR, "win_rate_model_long.joblib")
    short_path = os.path.join(MODELS_DIR, "win_rate_model_short.joblib")
    joblib.dump(final_long, long_path)
    joblib.dump(final_short, short_path)

    # Compute Feature Importances from base estimator
    base_long.fit(X, y_long)
    importances = dict(zip(FEATURE_COLS, [int(x) for x in base_long.feature_importances_]))

    meta = {
        "dataset_name": "recent_2w_multi_asset",
        "tickers": tickers,
        "num_samples": len(total_df),
        "feature_cols": FEATURE_COLS,
        "feature_importances": importances,
        "long_model": {
            "model_file": "win_rate_model_long.joblib",
            "test_auc": round(auc_l, 4),
            "test_brier": round(brier_l, 4)
        },
        "short_model": {
            "model_file": "win_rate_model_short.joblib",
            "test_auc": round(auc_s, 4),
            "test_brier": round(brier_s, 4)
        }
    }
    meta_path = os.path.join(MODELS_DIR, "model_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print("\n✅ [3/3] 正式生产模型已成功固化导出至:")
    print(f"   ├─ {long_path}")
    print(f"   ├─ {short_path}")
    print(f"   └─ {meta_path}")
    print("=" * 80)
    return meta

if __name__ == "__main__":
    build_and_train_2w_pipeline()
