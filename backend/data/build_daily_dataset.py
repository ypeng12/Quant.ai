# backend/data/build_daily_dataset.py
"""
Daily-Bar Scale-Independent Multi-Stock Machine Learning Dataset Generator.
Fetches daily K-line history (interval='1d') for active watchlist stocks,
builds scale-independent relative features X, and generates forward-looking target labels Y.
"""

import os
import sys
import pandas as pd
import numpy as np
from typing import List, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.data_manager import fetch_and_prepare_data
from app.config import WATCHLIST

DATASETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "datasets")

DEFAULT_TICKERS = ["TSLA", "NVDA", "AAPL", "MSFT", "AMD", "SNDK", "MU", "AMZN", "META", "GOOGL", "QQQ", "SPY"]

def build_daily_watchlist_dataset(tickers: List[str] = None, period: str = "1mo") -> pd.DataFrame:
    if not tickers:
        tickers = list(set(WATCHLIST + DEFAULT_TICKERS))

    print(f"📥 [1/4] 开始抓取监控池 {len(tickers)} 支股票最近 2~3 周的美股日线 K 线数据 (Period: {period}, Interval: 1d)...")
    
    all_dfs = []
    
    for ticker in tickers:
        try:
            print(f"   ├─ 正在处理 {ticker} 日线数据...")
            df = fetch_and_prepare_data(ticker, period=period, interval="1d")
            if df is None or df.empty or len(df) < 15:
                print(f"   ⚠️ 跳过 {ticker}: 数据行数不足 15 行")
                continue
            
            df = df.copy()
            df["ticker"] = ticker

            # --- Feature Matrix X (Scale-Independent Relative Features) ---
            df["feature_rvol"] = df["RVOL"].fillna(1.0)
            
            vwap_val = df["VWAP"] if "VWAP" in df.columns else df["EMA_21"]
            df["feature_vwap_dist_pct"] = ((df["Close"] - vwap_val) / vwap_val) * 100.0
            
            df["feature_mom_3_pct"] = df["Close"].pct_change(3) * 100.0
            df["feature_mom_10_pct"] = df["Close"].pct_change(10) * 100.0

            df["feature_atr_pct"] = (df["ATR"] / df["Close"]) * 100.0

            high_20 = df["High"].rolling(window=20, min_periods=5).max()
            low_20 = df["Low"].rolling(window=20, min_periods=5).min()

            df["feature_high_to_now_pct"] = ((df["Close"] - high_20) / high_20) * 100.0
            df["feature_low_to_now_pct"] = ((df["Close"] - low_20) / low_20) * 100.0
            df["feature_session_range_pct"] = ((df["High"] - df["Low"]) / df["Open"]) * 100.0

            # --- Target Labels Y (Forward 1-Day & 5-Day Window) ---
            # Forward 1-day gain & drop
            df["future_close_1d"] = df["Close"].shift(-1)
            df["future_ret_1d_pct"] = ((df["future_close_1d"] - df["Close"]) / df["Close"]) * 100.0

            # Label 1: Next-day return exceeds 1.2 * ATR_pct for Long
            target_gain_pct = 1.0 * df["feature_atr_pct"]
            stop_loss_pct = 0.8 * df["feature_atr_pct"]

            df["label_win_long"] = (
                (df["future_ret_1d_pct"] >= target_gain_pct)
            ).astype(int)

            df["label_win_short"] = (
                (df["future_ret_1d_pct"] <= -target_gain_pct)
            ).astype(int)

            clean_df = df.dropna(subset=[
                "feature_rvol", "feature_vwap_dist_pct", "feature_mom_3_pct",
                "feature_mom_10_pct", "feature_atr_pct", "label_win_long", "label_win_short"
            ]).copy()

            all_dfs.append(clean_df)

        except Exception as e:
            print(f"   ⚠️ 处理 {ticker} 失败: {e}")

    if not all_dfs:
        raise ValueError("未能获取任何有效的日线股票数据！")

    dataset = pd.concat(all_dfs, ignore_index=True)
    
    os.makedirs(DATASETS_DIR, exist_ok=True)
    parquet_path = os.path.join(DATASETS_DIR, "daily_watchlist_ml_dataset.parquet")
    csv_path = os.path.join(DATASETS_DIR, "daily_watchlist_ml_dataset.csv")

    dataset.to_parquet(parquet_path)
    dataset.to_csv(csv_path)

    print(f"✅ [4/4] 美股日线机器学习数据集构建成功！")
    print(f"   ├─ 涵盖股票数量: {len(all_dfs)} 支")
    print(f"   ├─ 总有效样本行数: {len(dataset)} 行")
    print(f"   ├─ Parquet 格式存储: {parquet_path}")
    print(f"   └─ CSV 格式存储: {csv_path}")

    return dataset

if __name__ == "__main__":
    build_daily_watchlist_dataset()
