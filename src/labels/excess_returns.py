import pandas as pd
import numpy as np


def calculate_forward_excess_returns(
    df: pd.DataFrame,
    horizons: list = [1, 5],
    quantile_top: float = 0.20
) -> pd.DataFrame:
    """
    Computes Forward Excess Return Labels starting strictly at t+1:
    1. Forward Return R_{i, t+1 -> t+h} = P_{t+h} / P_{t+1} - 1
    2. Excess Return = R_{i, t+1 -> t+h} - Mean_universe(R_{t+1 -> t+h})
    3. Classification Label = 1 if Excess Return in Top Quantile (Top 20%), else 0
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    price_col = "adjusted_close" if "adjusted_close" in df.columns else "close"

    for h in horizons:
        # Shift forward to get t+1 price and t+h price
        p_t1 = df.groupby("symbol")[price_col].shift(-1)
        p_th = df.groupby("symbol")[price_col].shift(-(1 + h))
        
        # Raw forward return from t+1 to t+1+h
        fwd_ret = (p_th / (p_t1 + 1e-8)) - 1.0
        df[f"fwd_ret_{h}d"] = fwd_ret

        # Excess return relative to cross-sectional mean at date t
        cs_mean_fwd_ret = df.groupby("date")[f"fwd_ret_{h}d"].transform("mean")
        df[f"label_excess_ret_{h}d"] = df[f"fwd_ret_{h}d"] - cs_mean_fwd_ret

        # Binary classification label: Top quantile
        def _top_quantile_label(series):
            if series.dropna().empty:
                return pd.Series(np.nan, index=series.index)
            cutoff = series.quantile(1.0 - quantile_top)
            return (series >= cutoff).astype(float)

        df[f"label_top_quantile_{h}d"] = df.groupby("date")[f"label_excess_ret_{h}d"].transform(_top_quantile_label)

    return df
