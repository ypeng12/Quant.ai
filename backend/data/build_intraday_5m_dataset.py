# backend/data/build_intraday_5m_dataset.py
"""
Intraday 5-Minute High-Granularity T+0 Machine Learning Dataset Generator.
Fetches 1-2 weeks (10 trading days) of 5-minute intraday K-line history,
engineers scale-independent intraday features X, and generates forward 15-minute target labels Y.
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
os.makedirs(DATASETS_DIR, exist_ok=True)

DEFAULT_TICKERS = ["TSLA", "NVDA", "AAPL", "MSFT", "AMD", "SNDK", "MU", "AMZN", "META", "GOOGL", "QQQ", "SPY"]

def build_intraday_5m_watchlist_dataset(tickers: List[str] = None, period: str = "5d") -> pd.DataFrame:
    if not tickers:
        tickers = list(set(WATCHLIST + DEFAULT_TICKERS))

    print(f"📥 [1/4] 开始抓取监控池 {len(tickers)} 支股票最近 1~2 周美股 5分钟 K 线数据 (Period: {period}, Interval: 5m)...")
    
    all_dfs = []
    
    for ticker in tickers:
        try:
            print(f"   ├─ 正在处理 {ticker} 5分钟 K 线特征与 15分钟前向 Label...")
            df = fetch_and_prepare_data(ticker, period=period, interval="5m")
            if df is None or df.empty or len(df) < 30:
                print(f"   ⚠️ 跳过 {ticker}: 5m 数据不足 30 行")
                continue
            
            df = df.copy()
            df["ticker"] = ticker

            # 1. Microstructure Scale-Independent Features X_t
            vol_ma_20 = df["Volume"].rolling(window=20, min_periods=5).mean()
            df["feature_rvol_5m"] = np.where(vol_ma_20 > 0, df["Volume"] / vol_ma_20, 1.0)
            df["feature_vwap_dist_pct"] = np.where(df["VWAP"] > 0, ((df["Close"] - df["VWAP"]) / df["VWAP"]) * 100.0, 0.0)

            df["feature_mom_5m_pct"] = df["Close"].pct_change(1) * 100.0
            df["feature_mom_15m_pct"] = df["Close"].pct_change(3) * 100.0

            df["feature_atr_pct"] = np.where(df["Close"] > 0, (df["ATR"] / df["Close"]) * 100.0, 1.0)
            candle_range = df["High"] - df["Low"]
            df["feature_range_to_atr"] = np.where(df["ATR"] > 0, candle_range / df["ATR"], 1.0)

            denom = np.where(candle_range == 0, 1e-8, candle_range)
            df["feature_body_ratio"] = np.abs(df["Close"] - df["Open"]) / denom
            df["feature_upper_shadow_ratio"] = (df["High"] - np.maximum(df["Close"], df["Open"])) / denom
            df["feature_lower_shadow_ratio"] = (np.minimum(df["Close"], df["Open"]) - df["Low"]) / denom

            high_session = df.groupby("Date")["High"].cummax()
            low_session = df.groupby("Date")["Low"].cummin()
            df["feature_high_dist_session"] = np.where(high_session > 0, ((df["Close"] - high_session) / high_session) * 100.0, 0.0)
            df["feature_low_dist_session"] = np.where(low_session > 0, ((df["Close"] - low_session) / low_session) * 100.0, 0.0)

            pdh = df.get("PDH", df["High"])
            pdl = df.get("PDL", df["Low"])
            df["feature_pdh_dist_pct"] = np.where(pdh > 0, ((df["Close"] - pdh) / pdh) * 100.0, 0.0)
            df["feature_pdl_dist_pct"] = np.where(pdl > 0, ((df["Close"] - pdl) / pdl) * 100.0, 0.0)

            # 2. Forward 15-Minute Target Labels Y_15m (Next 3 x 5m bars)
            # Max high and min low in the next 15 minutes
            future_high_3 = df["High"].shift(-3).rolling(window=3, min_periods=1).max()
            future_low_3 = df["Low"].shift(-3).rolling(window=3, min_periods=1).min()

            target_gain = df["Close"] + 1.2 * df["ATR"]
            stop_loss = df["Close"] - 0.8 * df["ATR"]

            df["label_win_daytrade_long"] = (
                (future_high_3 >= target_gain) & (future_low_3 > stop_loss)
            ).astype(int)

            clean_df = df.dropna(subset=[
                "feature_rvol_5m", "feature_vwap_dist_pct", "feature_mom_5m_pct",
                "feature_mom_15m_pct", "feature_atr_pct", "feature_body_ratio",
                "label_win_daytrade_long"
            ]).copy()

            all_dfs.append(clean_df)

        except Exception as e:
            print(f"   ⚠️ 处理 {ticker} 5m 数据失败: {e}")

    if not all_dfs:
        raise ValueError("未能获取任何有效的 5分钟 股票数据！")

    dataset = pd.concat(all_dfs, ignore_index=True)
    
    parquet_path = os.path.join(DATASETS_DIR, "intraday_5m_watchlist_dataset.parquet")
    dataset.to_parquet(parquet_path, index=False)
    print(f"✅ [2/4] 日内 5分钟 T+0 ML 数据集构建成功！已保存至: {parquet_path}")
    print(f"📊 数据集总行数: {len(dataset)} 行, 正样本率: {dataset['label_win_daytrade_long'].mean()*100:.1f}%")
    return dataset

if __name__ == "__main__":
    build_intraday_5m_watchlist_dataset()
