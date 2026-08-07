# backend/data/build_dataset.py
"""
Single-Stock & Multi-Stock Machine Learning Dataset Generator
Downloads 1-minute historical data, builds normalized feature matrix X,
and generates forward-looking target labels Y (without data leakage).
"""

import os
import sys
import numpy as np
import pandas as pd

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.data_manager import fetch_and_prepare_data

DATASETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "datasets")

def build_stock_dataset(ticker: str = "SNDK", period: str = "7d") -> pd.DataFrame:
    """
    Builds a normalized, leak-free ML dataset for a single stock (e.g. SNDK).
    Features are relative & scale-independent, making the model directly transferable to other stocks.
    """
    print(f"📥 [1/4] 拉取 {ticker} 历史 1 分钟高频 K 线数据 (Period: {period})...")
    df = fetch_and_prepare_data(ticker, period=period, interval="1m")
    if df is None or df.empty or len(df) < 50:
        raise ValueError(f"无法获取 {ticker} 足够的数据，请检查网络或 ticker 拼写")

    print(f"📊 [2/4] 计算无量纲/相对标准化机器学习特征 (Features X)...")
    # Feature 1: Relative Volume Ratio (RVOL)
    df["feature_rvol"] = df["RVOL"].fillna(1.0)
    
    # Feature 2: VWAP Distance % (衡量偏离均价线程度)
    df["feature_vwap_dist_pct"] = ((df["Close"] - df["VWAP"]) / df["VWAP"]) * 100.0
    
    # Feature 3: Short-term Momentum % (3m & 10m 相对斜率)
    df["feature_mom_3_pct"] = df["Close"].pct_change(3) * 100.0
    df["feature_mom_10_pct"] = df["Close"].pct_change(10) * 100.0

    # Feature 4: Normalized ATR % (相对波动率强度)
    df["feature_atr_pct"] = (df["ATR"] / df["Close"]) * 100.0

    # Feature 5: Session Extremes Position (冲高与拉回偏离度)
    session_high = df["High"].expanding().max()
    session_low = df["Low"].expanding().min()
    session_open = df["Open"].iloc[0] if len(df) > 0 else df["Close"].iloc[0]
    
    df["feature_high_to_now_pct"] = ((df["Close"] - session_high) / session_high) * 100.0
    df["feature_low_to_now_pct"] = ((df["Close"] - session_low) / session_low) * 100.0
    df["feature_session_range_pct"] = ((session_high - session_low) / session_open) * 100.0

    print(f"🎯 [3/4] 标注未来 15 分钟无前瞻泄漏盈亏标签 (Labels Y)...")
    # Forward 15-bar window max gain & max drop
    indexer = pd.api.indexers.FixedForwardWindowIndexer(window_size=15)
    future_high_max = df["High"].rolling(window=indexer).max()
    future_low_min = df["Low"].rolling(window=indexer).min()

    df["future_max_up_pct"] = ((future_high_max - df["Close"]) / df["Close"]) * 100.0
    df["future_max_down_pct"] = ((df["Close"] - future_low_min) / df["Close"]) * 100.0

    # Target Label: 1 if future max gain >= 1.5 * ATR_pct within 15 mins (and max drop < 1.0 * ATR_pct), else 0
    target_up = 1.5 * df["feature_atr_pct"]
    stop_down = 1.0 * df["feature_atr_pct"]
    
    df["label_win_long"] = (
        (df["future_max_up_pct"] >= target_up) & (df["future_max_down_pct"] < stop_down)
    ).astype(int)
    
    df["label_win_short"] = (
        (df["future_max_down_pct"] >= target_up) & (df["future_max_up_pct"] < stop_down)
    ).astype(int)

    # Clean missing/NaN rows caused by rolling windows
    dataset = df.dropna().copy()

    os.makedirs(DATASETS_DIR, exist_ok=True)
    parquet_path = os.path.join(DATASETS_DIR, f"{ticker}_ml_dataset.parquet")
    csv_path = os.path.join(DATASETS_DIR, f"{ticker}_ml_dataset.csv")

    dataset.to_parquet(parquet_path)
    dataset.to_csv(csv_path)

    print(f"✅ [4/4] {ticker} 数据集成功生成并存入磁盘！")
    print(f"   └─ 样本数量: {len(dataset)} 行")
    print(f"   └─ Parquet 路径: {parquet_path}")
    print(f"   └─ CSV 路径: {csv_path}")

    return dataset

if __name__ == "__main__":
    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "SNDK"
    build_stock_dataset(ticker_arg)
