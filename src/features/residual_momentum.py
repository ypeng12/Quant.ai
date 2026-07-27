import pandas as pd
import numpy as np


def calculate_residual_momentum(
    df: pd.DataFrame,
    benchmark_symbol: str = "SPY",
    window_reg: int = 60,
    window_mom: int = 20,
) -> pd.DataFrame:
    """
    Calculate Residual Momentum by stripping Market (SPY) Beta exposure:
    1. Rolling 60-day OLS: R_i(t) = alpha + beta * R_benchmark(t) + eps_i(t)
    2. Residual Momentum = sum_{t-19}^t eps_i(t)
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    price_col = "adjusted_close" if "adjusted_close" in df.columns else "close"

    # Daily log returns
    df["ret"] = df.groupby("symbol")[price_col].transform(lambda p: np.log(p / p.shift(1)))

    # Pivot return matrix: dates x symbols
    ret_pivot = df.pivot(index="date", columns="symbol", values="ret")

    if benchmark_symbol not in ret_pivot.columns:
        # Fallback to universe cross-sectional mean if SPY is absent
        benchmark_ret = ret_pivot.mean(axis=1)
    else:
        benchmark_ret = ret_pivot[benchmark_symbol]

    residual_matrix = pd.DataFrame(index=ret_pivot.index, columns=ret_pivot.columns, dtype=float)

    # Vectorized / rolling covariance calculation for Alpha & Beta
    var_bench = benchmark_ret.rolling(window_reg, min_periods=30).var()

    for col in ret_pivot.columns:
        cov = ret_pivot[col].rolling(window_reg, min_periods=30).cov(benchmark_ret)
        beta = cov / (var_bench + 1e-8)
        alpha = ret_pivot[col].rolling(window_reg, min_periods=30).mean() - beta * benchmark_ret.rolling(window_reg, min_periods=30).mean()
        
        expected_ret = alpha + beta * benchmark_ret
        eps = ret_pivot[col] - expected_ret
        
        # Sum 20-day residual return
        residual_matrix[col] = eps.rolling(window_mom, min_periods=10).sum()

    # Melt back into long format
    res_long = residual_matrix.stack().reset_index()
    res_long.columns = ["date", "symbol", "residual_mom_20d"]

    df = pd.merge(df, res_long, on=["date", "symbol"], how="left")
    return df
