import pandas as pd
import numpy as np
from typing import List, Optional


def robust_zscore(series: pd.Series, eps: float = 1e-6) -> pd.Series:
    """
    Calculate Robust Cross-Sectional Z-Score using Median and Median Absolute Deviation (MAD):
    z = 0.6745 * (x - median) / (MAD + eps)
    """
    median = series.median()
    mad = (series - median).abs().median()
    if mad < eps:
        mad = series.std() + eps
    return 0.6745 * (series - median) / (mad + eps)


def sector_neutralize(df: pd.Series, sector_series: pd.Series) -> pd.Series:
    """
    Demean series by sector group to eliminate structural sector biases.
    """
    temp_df = pd.DataFrame({"val": series, "sector": sector_series})
    sector_means = temp_df.groupby("sector")["val"].transform("mean")
    return series - sector_means


def calculate_sortino_momentum(returns_df: pd.DataFrame, window: int = 20, eps: float = 1e-6) -> pd.Series:
    """
    Calculate Sortino (Downside Risk-Adjusted) Momentum over rolling window:
    SortinoMom = Return_20d / (DownsideVol_20d + eps)
    """
    # Calculate daily log returns
    daily_ret = np.log(returns_df / returns_df.shift(1))
    
    # Cumulative return over window
    cum_ret = (returns_df / returns_df.shift(window)) - 1.0

    # Downside volatility: standard deviation of negative returns
    neg_ret = daily_ret.clip(upper=0.0)
    downside_vol = neg_ret.rolling(window, min_periods=10).std() * np.sqrt(252)

    sortino_mom = cum_ret / (downside_vol + eps)
    return sortino_mom


class FeaturePipeline:
    """
    Computes standard and advanced quantitative features for cross-sectional momentum:
    1. Mom_5d, Mom_20d, Mom_60d (Log returns using Adjusted Close)
    2. Vol_20d, Vol_60d (Annualized rolling standard deviation)
    3. VolAdjMom_20d (Return / Volatility)
    4. SortinoMom_20d (Return / Downside Volatility)
    5. Volume_Z_20d (Robust Volume Z-Score)
    6. Dist_52w_High (Distance to 252-day peak)
    """

    def __init__(self, lookback_windows: List[int] = [5, 20, 60]):
        self.lookback_windows = lookback_windows

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

        price_col = "adjusted_close" if "adjusted_close" in df.columns else "close"

        # 1. Base Log Returns & Volatilities
        for w in self.lookback_windows:
            df[f"mom_{w}d"] = df.groupby("symbol")[price_col].transform(lambda p: np.log(p / p.shift(w)))
            df[f"vol_{w}d"] = df.groupby("symbol")[price_col].transform(
                lambda p: np.log(p / p.shift(1)).rolling(w, min_periods=5).std() * np.sqrt(252)
            )
            df[f"vol_adj_mom_{w}d"] = df[f"mom_{w}d"] / (df[f"vol_{w}d"] + 1e-6)

        # 2. Sortino (Downside Volatility Adjusted Momentum)
        def _get_sortino(group):
            ret = np.log(group[price_col] / group[price_col].shift(1))
            cum_ret = np.log(group[price_col] / group[price_col].shift(20))
            neg_ret = ret.clip(upper=0.0)
            dvol = neg_ret.rolling(20, min_periods=10).std() * np.sqrt(252)
            return cum_ret / (dvol + 1e-6)

        df["sortino_mom_20d"] = df.groupby("symbol", group_keys=False).apply(_get_sortino)

        # 3. Volume Microstructure & Z-Score
        df["dollar_volume"] = df[price_col] * df["volume"]
        df["volume_z_20d"] = df.groupby("symbol")["dollar_volume"].transform(
            lambda v: (np.log(v + 1.0) - np.log(v + 1.0).rolling(20, min_periods=10).mean()) /
                      (np.log(v + 1.0).rolling(20, min_periods=10).std() + 1e-6)
        )

        # 4. Distance to 52-Week High
        df["dist_52w_high"] = df.groupby("symbol")[price_col].transform(
            lambda p: p / p.rolling(252, min_periods=60).max() - 1.0
        )

        # 5. Cross-Sectional Standardization (Robust Z-Score per Date)
        feature_cols = [f"mom_{w}d" for w in self.lookback_windows] + \
                       [f"vol_adj_mom_{w}d" for w in self.lookback_windows] + \
                       ["sortino_mom_20d", "volume_z_20d", "dist_52w_high"]

        for col in feature_cols:
            if col in df.columns:
                df[f"cs_z_{col}"] = df.groupby("date")[col].transform(robust_zscore)

        return df
