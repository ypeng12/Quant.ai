import os
import urllib.request
import pandas as pd
import numpy as np
from typing import List, Optional, Tuple

class HuggingFaceETFLoader:
    """
    Data Loader for ETF price data (Hugging Face / yfinance fallback).
    Downloads and caches parquet files locally in `data/raw/` for offline reproducibility.
    """

    DEFAULT_UNIVERSE = [
        "SPY", "QQQ", "IWM", "MDY",
        "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLC", "XLRE",
        "SMH", "XBI", "KRE", "ITB",
        "TLT", "IEF", "SHY", "LQD", "HYG", "TIP",
        "GLD", "SLV", "USO", "DBA",
        "EEM", "EFA", "FXI", "EWJ",
        "MTUM", "USMV", "QUAL", "IWD", "IWF"
    ]

    def __init__(self, cache_dir: str = "data/raw"):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def load_prices(self, tickers: Optional[List[str]] = None) -> pd.DataFrame:
        """Load ETF prices DataFrame. Uses cached parquet if available, otherwise downloads via yfinance."""
        local_path = os.path.join(self.cache_dir, "hf_prices.parquet")
        
        if os.path.exists(local_path):
            print(f"[ETFLoader] Reading cached dataset from {local_path}...")
            df = pd.read_parquet(local_path)
            df["date"] = pd.to_datetime(df["date"])
            return df
        
        return self._fetch_yfinance_prices(tickers)

    def _fetch_yfinance_prices(self, tickers: Optional[List[str]] = None) -> pd.DataFrame:
        """Fetch daily OHLCV dataset using yfinance and save to local parquet cache."""
        import yfinance as yf
        tickers = tickers or self.DEFAULT_UNIVERSE
        print(f"[ETFLoader] Fetching {len(tickers)} tickers via yfinance...")
        
        try:
            data = yf.download(tickers, start="2014-01-01", end="2024-01-01", group_by="ticker", auto_adjust=False, progress=False)
            records = []
            
            for t in tickers:
                if t in data.columns.levels[0]:
                    sub = data[t].dropna(how="all").reset_index()
                    if len(sub) > 0:
                        sub["symbol"] = t
                        sub.rename(columns={
                            "Date": "date", "Open": "open", "High": "high", "Low": "low",
                            "Close": "close", "Adj Close": "adjusted_close", "Volume": "volume"
                        }, inplace=True)
                        records.append(sub)
            
            if records:
                df_res = pd.concat(records, ignore_index=True)
                df_res["date"] = pd.to_datetime(df_res["date"])
                if "adjusted_close" not in df_res.columns:
                    df_res["adjusted_close"] = df_res["close"]
                
                # Save cache
                df_res.to_parquet(os.path.join(self.cache_dir, "hf_prices.parquet"))
                print(f"[ETFLoader] Cached {len(df_res)} price rows to {self.cache_dir}/hf_prices.parquet")
                return df_res
        except Exception as e:
            print(f"[ETFLoader] Remote download failed: {e}")

        # Fallback to synthetic offline dataset generator
        return self.generate_synthetic_prices(tickers)

    @staticmethod
    def generate_synthetic_prices(tickers: List[str], num_days: int = 1000) -> pd.DataFrame:
        """Generate realistic synthetic OHLCV data for offline CI / local smoke tests."""
        print("[ETFLoader] Generating synthetic price data for offline testing...")
        dates = pd.date_range("2020-01-01", periods=num_days, freq="B")
        records = []
        np.random.seed(42)
        
        for t in tickers:
            price = 100.0 + np.random.uniform(-10, 10)
            volatility = 0.015 + np.random.uniform(0.005, 0.01)
            prices = [price]
            
            for _ in range(num_days - 1):
                ret = np.random.normal(0.0004, volatility)
                price *= np.exp(ret)
                prices.append(price)
            
            df_t = pd.DataFrame({
                "date": dates,
                "symbol": t,
                "open": prices,
                "high": [p * (1 + abs(np.random.normal(0, 0.005))) for p in prices],
                "low": [p * (1 - abs(np.random.normal(0, 0.005))) for p in prices],
                "close": prices,
                "adjusted_close": prices,
                "volume": np.random.uniform(1e6, 1e7, size=num_days)
            })
            records.append(df_t)
            
        return pd.concat(records, ignore_index=True)
