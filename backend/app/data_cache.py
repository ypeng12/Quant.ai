# backend/app/data_cache.py
"""
本地 Parquet 数据缓存层 — 减少 yfinance 重复下载，提升回测响应速度
"""
import os
import pandas as pd
import hashlib
from datetime import datetime, timedelta

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# 缓存 TTL 配置（秒）
CACHE_TTL = {
    "1m": 60 * 30,      # 30分钟
    "5m": 60 * 60,      # 1小时
    "15m": 60 * 60 * 2, # 2小时
    "30m": 60 * 60 * 4, # 4小时
    "1h": 60 * 60 * 8,  # 8小时
    "1d": 60 * 60 * 24, # 24小时
}

def _cache_key(ticker: str, period: str, interval: str) -> str:
    raw = f"{ticker}_{period}_{interval}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]

def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.parquet")

def _meta_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.meta")

def get_cached(ticker: str, period: str, interval: str):
    """读取缓存，过期或不存在返回 None"""
    key = _cache_key(ticker, period, interval)
    parquet_file = _cache_path(key)
    meta_file = _meta_path(key)
    
    if not os.path.exists(parquet_file) or not os.path.exists(meta_file):
        return None
    
    # 检查过期时间
    try:
        with open(meta_file, 'r') as f:
            saved_time = float(f.read().strip())
    except Exception:
        return None
    
    ttl = CACHE_TTL.get(interval, 3600)
    if datetime.now().timestamp() - saved_time > ttl:
        return None  # 已过期
    
    try:
        df = pd.read_parquet(parquet_file)
        return df
    except Exception:
        return None

def save_cache(ticker: str, period: str, interval: str, df: pd.DataFrame):
    """保存数据到 Parquet 缓存"""
    if df is None or df.empty:
        return
    key = _cache_key(ticker, period, interval)
    try:
        df.to_parquet(_cache_path(key))
        with open(_meta_path(key), 'w') as f:
            f.write(str(datetime.now().timestamp()))
    except Exception as e:
        print(f"缓存写入失败: {e}")

def invalidate_cache(ticker: str = None):
    """清除缓存，ticker=None 时清除全部"""
    for fname in os.listdir(CACHE_DIR):
        fpath = os.path.join(CACHE_DIR, fname)
        try:
            os.remove(fpath)
        except Exception:
            pass

def get_cache_stats() -> dict:
    """返回缓存使用统计"""
    try:
        files = [f for f in os.listdir(CACHE_DIR) if f.endswith('.parquet')]
        total_size = sum(os.path.getsize(os.path.join(CACHE_DIR, f)) for f in os.listdir(CACHE_DIR))
    except Exception:
        files = []
        total_size = 0
    return {
        "cached_datasets": len(files),
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "cache_dir": CACHE_DIR
    }
