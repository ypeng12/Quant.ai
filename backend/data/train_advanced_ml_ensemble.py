# backend/data/train_advanced_ml_ensemble.py
"""
Advanced Multi-Horizon Machine Learning Alpha Ensemble & Profit Expectancy Engine
Trains a dual-head quantitative model (Probability Classifier + Return/Risk Regressors):
1. Calibrated Win Rate Probability P_win (First-passage triple barrier)
2. Expected Maximum Favorable Excursion E[MFE] (Profit Magnitude Predictor)
3. Expected Maximum Adverse Excursion E[MAE] (Downside Risk Predictor)
4. Net Mathematical Expectancy E[Edge] = P_win * E[MFE] - (1 - P_win) * E[MAE]

Applies to ANY leader stock (SNDK, TSLA, NVDA, MSTR, etc.) to accurately detect
explosive trend continuation and protect against chop.
"""

import os
import sys
import datetime
import pytz
import joblib
import json
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import roc_auc_score, brier_score_loss, mean_squared_error, r2_score

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
UNIVERSAL_DIR = os.path.join(MODELS_DIR, "universal")
os.makedirs(DATASETS_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(PER_TICKER_DIR, exist_ok=True)
os.makedirs(UNIVERSAL_DIR, exist_ok=True)

ADVANCED_FEATURE_COLS = [
    "feature_ofi",
    "feature_ofi_slope",
    "feature_rvol",
    "feature_vol_accel",
    "feature_dollar_vol_log",
    "feature_bar_close_loc",
    "feature_upper_wick_ratio",
    "feature_mom_1m",
    "feature_mom_3m",
    "feature_mom_5m",
    "feature_mom_15m",
    "feature_mom_accel",
    "feature_vwap_dist_pct",
    "feature_vwap_slope",
    "feature_vwap_zscore",
    "feature_ema_diff_pct",
    "feature_ema9_slope",
    "feature_atr_pct",
    "feature_atr_expansion",
    "feature_er",
    "feature_donchian_breakout",
    "feature_session_range_pct",
    "feature_high_dist_pct",
    "feature_minutes_from_open"
]

def fetch_intraday_data(client, ticker: str, days: int = 40) -> pd.DataFrame:
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

def compute_advanced_features_and_targets(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    d = df.copy()
    d["ticker"] = ticker
    d["date"] = d.index.date

    # 1. Bar geometry & Microstructure
    candle_range = np.maximum(1e-5, d["High"] - d["Low"])
    d["feature_bar_close_loc"] = (d["Close"] - d["Low"]) / candle_range
    body_high = np.maximum(d["Open"], d["Close"])
    d["feature_upper_wick_ratio"] = (d["High"] - body_high) / candle_range

    # 2. OFI & Order Flow Dynamics
    vol_mean_20 = d["Volume"].rolling(20).mean().fillna(d["Volume"])
    d["feature_ofi"] = np.clip(np.tanh(((d["feature_bar_close_loc"] - 0.5) * 2.0) * (d["Volume"] / np.maximum(1.0, vol_mean_20))), -1.0, 1.0)
    d["feature_ofi_slope"] = (d["feature_ofi"] - d["feature_ofi"].shift(3)).fillna(0.0)
    d["feature_rvol"] = (d["Volume"] / np.maximum(1.0, vol_mean_20)).fillna(1.0)
    d["feature_vol_accel"] = (d["Volume"] / np.maximum(1.0, d["Volume"].shift(1))).clip(0.1, 10.0)
    d["feature_dollar_vol_log"] = np.log(np.maximum(1.0, d["Close"] * d["Volume"]))

    # 3. Multi-horizon momentum & acceleration
    d["feature_mom_1m"] = d["Close"].pct_change(1).fillna(0.0) * 100.0
    d["feature_mom_3m"] = d["Close"].pct_change(3).fillna(0.0) * 100.0
    d["feature_mom_5m"] = d["Close"].pct_change(5).fillna(0.0) * 100.0
    d["feature_mom_15m"] = d["Close"].pct_change(15).fillna(0.0) * 100.0
    d["feature_mom_accel"] = d["feature_mom_3m"] - d["feature_mom_15m"]

    # 4. VWAP & Moving Averages
    d["feature_vwap_dist_pct"] = (d["Close"] - d["vwap"]) / np.maximum(1e-5, d["vwap"]) * 100.0
    d["feature_vwap_slope"] = (d["vwap"] - d["vwap"].shift(5)) / np.maximum(1e-5, d["vwap"].shift(5)) * 100.0
    vwap_std = (d["Close"] - d["vwap"]).rolling(30).std().fillna(1.0)
    d["feature_vwap_zscore"] = ((d["Close"] - d["vwap"]) / np.maximum(1e-5, vwap_std)).clip(-3.0, 3.0)

    ema9 = d["Close"].ewm(span=9).mean()
    ema21 = d["Close"].ewm(span=21).mean()
    d["feature_ema_diff_pct"] = (ema9 - ema21) / np.maximum(1e-5, ema21) * 100.0
    d["feature_ema9_slope"] = (ema9 - ema9.shift(3)) / np.maximum(1e-5, ema9.shift(3)) * 100.0

    # 5. Volatility & Breakout structure
    tr = np.maximum(d["High"] - d["Low"], np.maximum(abs(d["High"] - d["Close"].shift(1)), abs(d["Low"] - d["Close"].shift(1))))
    d["atr"] = tr.rolling(14).mean().fillna(d["Close"] * 0.01)
    atr_long = tr.rolling(60).mean().fillna(d["atr"])
    d["feature_atr_pct"] = (d["atr"] / np.maximum(1e-5, d["Close"]) * 100.0).fillna(1.0)
    d["feature_atr_expansion"] = (d["atr"] / np.maximum(1e-5, atr_long)).clip(0.5, 3.0)

    # Kaufman Efficiency Ratio
    net_move = abs(d["Close"] - d["Close"].shift(20))
    total_path = abs(d["Close"].diff()).rolling(20).sum()
    d["feature_er"] = (net_move / np.maximum(1e-5, total_path)).fillna(0.20)

    # Donchian channel breakout
    roll_high_20 = d["High"].rolling(20).max()
    d["feature_donchian_breakout"] = ((d["Close"] - roll_high_20) / np.maximum(1e-5, d["atr"])).clip(-3.0, 3.0)

    # Session range metrics
    session_open = d.groupby("date")["Open"].transform("first")
    session_high = d.groupby("date")["High"].transform("cummax")
    session_low = d.groupby("date")["Low"].transform("cummin")
    d["feature_session_range_pct"] = ((session_high - session_low) / np.maximum(1e-5, session_open) * 100.0).fillna(1.0)
    d["feature_high_dist_pct"] = ((d["Close"] - session_high) / np.maximum(1e-5, session_high) * 100.0).fillna(0.0)

    # Time of Day (minutes from 9:30 AM)
    minutes = (d.index.hour - 9) * 60 + (d.index.minute - 30)
    d["feature_minutes_from_open"] = np.clip(minutes / 390.0, 0.0, 1.0)

    # ─── Multi-Horizon Ground Truth Targets (30m Forward Window) ─────────────
    # Exact sequential first-passage calculation:
    window = 30
    n = len(d)
    highs = d["High"].values
    lows = d["Low"].values
    closes = d["Close"].values
    atrs = d["atr"].values

    target_win = np.zeros(n, dtype=int)
    target_mfe = np.zeros(n, dtype=float)
    target_mae = np.zeros(n, dtype=float)

    for i in range(n):
        end_idx = min(n, i + window + 1)
        if end_idx <= i + 1:
            continue
        c = closes[i]
        a = atrs[i]
        up_barrier = c + 1.5 * a
        dn_barrier = c - 1.0 * a

        f_highs = highs[i+1:end_idx]
        f_lows = lows[i+1:end_idx]

        mfe = (np.max(f_highs) - c) / c * 100.0
        mae = (c - np.min(f_lows)) / c * 100.0
        target_mfe[i] = max(0.0, mfe)
        target_mae[i] = max(0.0, mae)

        # First passage check
        first_win = False
        for j in range(len(f_highs)):
            if f_highs[j] >= up_barrier:
                first_win = True
                break
            if f_lows[j] <= dn_barrier:
                break
        target_win[i] = 1 if first_win else 0

    d["target_long_win"] = target_win
    d["target_mfe_pct"] = target_mfe
    d["target_mae_pct"] = target_mae
    d["target_net_edge_pct"] = target_mfe - target_mae
    d["target_explosive_win"] = ((target_mfe >= 2.0) & (target_win == 1)).astype(int)

    clean = d.dropna().iloc[:-window].copy()
    return clean

def train_ticker_advanced_suite(ticker: str, df: pd.DataFrame) -> dict:
    X = df[ADVANCED_FEATURE_COLS]
    y_win = df["target_long_win"]
    y_mfe = df["target_mfe_pct"]
    y_mae = df["target_mae_pct"]

    split_idx = int(len(df) * 0.75)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_win_train, y_win_test = y_win.iloc[:split_idx], y_win.iloc[split_idx:]
    y_mfe_train, y_mfe_test = y_mfe.iloc[:split_idx], y_mfe.iloc[split_idx:]
    y_mae_train, y_mae_test = y_mae.iloc[:split_idx], y_mae.iloc[split_idx:]

    # 1. Calibrated Classifier for Win Probability
    base_clf = LGBMClassifier(
        n_estimators=100,
        learning_rate=0.03,
        max_depth=4,
        num_leaves=15,
        min_child_samples=25,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1
    )
    calibrated_clf = CalibratedClassifierCV(estimator=base_clf, method='sigmoid', cv=3)
    calibrated_clf.fit(X_train, y_win_train)

    pred_prob_test = calibrated_clf.predict_proba(X_test)[:, 1]
    test_auc = roc_auc_score(y_win_test, pred_prob_test) if len(np.unique(y_win_test)) > 1 else 0.50
    test_brier = brier_score_loss(y_win_test, pred_prob_test)

    # 2. Regressor for Expected Maximum Profit (MFE %)
    reg_mfe = LGBMRegressor(
        objective="huber",
        n_estimators=100,
        learning_rate=0.03,
        max_depth=4,
        num_leaves=15,
        min_child_samples=25,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1
    )
    reg_mfe.fit(X_train, y_mfe_train)
    pred_mfe_test = reg_mfe.predict(X_test)
    mfe_mse = mean_squared_error(y_mfe_test, pred_mfe_test)
    mfe_r2 = r2_score(y_mfe_test, pred_mfe_test)

    # 3. Regressor for Expected Maximum Drawdown (MAE %)
    reg_mae = LGBMRegressor(
        objective="huber",
        n_estimators=100,
        learning_rate=0.03,
        max_depth=4,
        num_leaves=15,
        min_child_samples=25,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1
    )
    reg_mae.fit(X_train, y_mae_train)
    pred_mae_test = reg_mae.predict(X_test)
    mae_mse = mean_squared_error(y_mae_test, pred_mae_test)

    # Fit final production models on full history
    calibrated_clf.fit(X, y_win)
    reg_mfe.fit(X, y_mfe)
    reg_mae.fit(X, y_mae)

    # Save dedicated bundle
    bundle = {
        "ticker": ticker,
        "features": ADVANCED_FEATURE_COLS,
        "classifier": calibrated_clf,
        "regressor_mfe": reg_mfe,
        "regressor_mae": reg_mae,
        "base_rate_p0": float(y_win.mean()),
        "avg_mfe": float(y_mfe.mean()),
        "avg_mae": float(y_mae.mean()),
        "trained_at": datetime.datetime.now().isoformat()
    }
    bundle_path = os.path.join(PER_TICKER_DIR, f"advanced_ml_bundle_{ticker}.joblib")
    joblib.dump(bundle, bundle_path)

    # Also save the calibrated classifier as standard win rate model
    legacy_path = os.path.join(PER_TICKER_DIR, f"win_rate_model_{ticker}.joblib")
    joblib.dump(calibrated_clf, legacy_path)

    print(f"   ├─ [{ticker}] 高维 ML 复合套件训练完成:")
    print(f"      • 胜率分类器 OOS AUC: {test_auc:.4f} | Brier: {test_brier:.4f} | 基准先验 P0: {y_win.mean()*100:.1f}%")
    print(f"      • 最大盈利 MFE 回归器: R2={mfe_r2:.3f} | 平均涨幅预估: {y_mfe.mean():.2f}%")
    print(f"      • 最大回撤 MAE 回归器: 平均风险预估: {y_mae.mean():.2f}%")
    print(f"      • 保存至: {bundle_path}")

    return {
        "ticker": ticker,
        "samples": len(df),
        "test_auc": round(float(test_auc), 4),
        "test_brier": round(float(test_brier), 4),
        "mfe_r2": round(float(mfe_r2), 4),
        "base_rate_p0": round(float(y_win.mean()), 4),
        "avg_mfe": round(float(y_mfe.mean()), 4),
        "avg_mae": round(float(y_mae.mean()), 4)
    }

def train_universal_market_model(all_dfs: list) -> dict:
    combined_df = pd.concat(all_dfs, ignore_index=True)
    print(f"\n[*] 正在训练跨标的全市场通用【龙头突破与收益预估模型】 (总样本: {len(combined_df)} 根 K 线)...")
    
    X = combined_df[ADVANCED_FEATURE_COLS]
    y_win = combined_df["target_long_win"]
    y_mfe = combined_df["target_mfe_pct"]
    y_mae = combined_df["target_mae_pct"]

    split_idx = int(len(combined_df) * 0.80)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_win_train, y_win_test = y_win.iloc[:split_idx], y_win.iloc[split_idx:]
    y_mfe_train, y_mfe_test = y_mfe.iloc[:split_idx], y_mfe.iloc[split_idx:]

    # Universal Classifier
    base_clf = LGBMClassifier(
        n_estimators=150,
        learning_rate=0.03,
        max_depth=5,
        num_leaves=20,
        min_child_samples=40,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1
    )
    universal_clf = CalibratedClassifierCV(estimator=base_clf, method='sigmoid', cv=3)
    universal_clf.fit(X_train, y_win_train)

    pred_prob_test = universal_clf.predict_proba(X_test)[:, 1]
    test_auc = roc_auc_score(y_win_test, pred_prob_test)

    # Universal Regressors
    universal_reg_mfe = LGBMRegressor(
        objective="huber",
        n_estimators=120,
        learning_rate=0.03,
        max_depth=5,
        num_leaves=20,
        min_child_samples=40,
        random_state=42,
        verbose=-1
    )
    universal_reg_mfe.fit(X_train, y_mfe_train)

    universal_reg_mae = LGBMRegressor(
        objective="huber",
        n_estimators=120,
        learning_rate=0.03,
        max_depth=5,
        num_leaves=20,
        min_child_samples=40,
        random_state=42,
        verbose=-1
    )
    universal_reg_mae.fit(combined_df[ADVANCED_FEATURE_COLS], combined_df["target_mae_pct"])

    # Full fit
    universal_clf.fit(X, y_win)
    universal_reg_mfe.fit(X, y_mfe)

    universal_bundle = {
        "features": ADVANCED_FEATURE_COLS,
        "classifier": universal_clf,
        "regressor_mfe": universal_reg_mfe,
        "regressor_mae": universal_reg_mae,
        "base_rate_p0": float(y_win.mean()),
        "avg_mfe": float(y_mfe.mean()),
        "avg_mae": float(y_mae.mean()),
        "trained_at": datetime.datetime.now().isoformat()
    }
    u_path = os.path.join(UNIVERSAL_DIR, "universal_ml_bundle.joblib")
    joblib.dump(universal_bundle, u_path)
    print(f"   └─ 全市场通用 ML 套件固化完成: OOS AUC={test_auc:.4f} | 样本={len(combined_df)} | 保存至: {u_path}")

    return {
        "samples": len(combined_df),
        "test_auc": round(float(test_auc), 4),
        "base_rate_p0": round(float(y_win.mean()), 4),
        "avg_mfe": round(float(y_mfe.mean()), 4),
        "avg_mae": round(float(y_mae.mean()), 4)
    }

def run_advanced_training_pipeline(tickers=None):
    if tickers is None:
        tickers = ["SNDK", "TSLA", "NVDA", "MSTR"]

    print("=" * 80)
    print("🚀 【QUANT.AI】高维多目标机器学习 Alpha 收益预估与胜率期望引擎训练")
    print(f"   核心目标: 解决无论哪只龙头股均能精确预测收益与胜率，赚取数千至数万美元波段")
    print(f"   监控标的: {tickers}")
    print("=" * 80)

    client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    results = {}
    all_clean_dfs = []

    for sym in tickers:
        print(f"\n[*] 正在从 Alpaca 拉取 [{sym}] 过去 45 天 1 分钟真实行情...")
        df = fetch_intraday_data(client, sym, days=45)
        if df.empty:
            print(f"⚠️ [{sym}] 未获取到数据，跳过。")
            continue
        print(f"   └─ 成功拉取 {len(df)} 根 K 线，开始构建 22 维高阶微观结构特征工程与前向三屏障收益标签...")
        df_feat = compute_advanced_features_and_targets(df, sym)
        # Save parquet with index preserved
        feat_path = os.path.join(DATASETS_DIR, f"advanced_dataset_{sym}.parquet")
        df_feat.to_parquet(feat_path)
        all_clean_dfs.append(df_feat)

        res = train_ticker_advanced_suite(sym, df_feat)
        results[sym] = res

    if all_clean_dfs:
        res_universal = train_universal_market_model(all_clean_dfs)
        results["UNIVERSAL"] = res_universal

    meta_path = os.path.join(MODELS_DIR, "advanced_ensemble_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print(f"✅ 全部分标的及全市场通用高阶 ML 收益套件训练固化完毕！元数据保存至: {meta_path}")
    print("=" * 80)
    return results

if __name__ == "__main__":
    run_advanced_training_pipeline()
