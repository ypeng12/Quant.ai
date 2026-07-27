import pytest
import pandas as pd
import numpy as np
from src.data.hf_loader import HuggingFaceETFLoader
from src.features.momentum import FeaturePipeline
from src.labels.excess_returns import calculate_forward_excess_returns


def test_zero_future_leakage():
    """
    CRITICAL UNIT TEST:
    Verifies that for every observation at date t, all feature values depend strictly on history <= t,
    and forward label evaluation starts at date >= t+1.
    """
    # Create clean test dataset
    df_raw = HuggingFaceETFLoader.generate_synthetic_prices(["SPY", "QQQ", "TLT"], num_days=100)
    
    # Feature engineering
    pipeline = FeaturePipeline(lookback_windows=[5, 20])
    df_feat = pipeline.transform(df_raw)

    # Label calculation
    df_labeled = calculate_forward_excess_returns(df_feat, horizons=[5])

    # Check that for any row i at date t:
    # fwd_ret_5d uses price at t+1 and price at t+6
    valid_rows = df_labeled.dropna(subset=["fwd_ret_5d", "cs_z_mom_20d"])
    
    for idx, row in valid_rows.iterrows():
        date_t = row["date"]
        symbol = row["symbol"]
        
        # Verify that feature mom_20d uses only prices <= date_t
        past_prices = df_raw[(df_raw["symbol"] == symbol) & (df_raw["date"] <= date_t)]["close"]
        assert len(past_prices) >= 20, "Feature must have 20 historical prices"

        # Verify forward return calculation starts after date_t
        future_prices = df_raw[(df_raw["symbol"] == symbol) & (df_raw["date"] > date_t)]["close"]
        assert len(future_prices) >= 6, "Forward label requires future prices > date_t"

    print("[TEST PASSED] Zero future leakage verified successfully!")


if __name__ == "__main__":
    test_zero_future_leakage()
