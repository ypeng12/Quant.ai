import pandas as pd
import numpy as np
from scipy import stats
from typing import Dict, Any, Tuple, Optional


def calculate_rank_ic(df: pd.DataFrame, pred_col: str, target_col: str, date_col: str = "date") -> pd.DataFrame:
    """
    Computes daily Spearman Rank Information Coefficient (Rank IC):
    Rank IC_t = SpearmanCorr(y_pred_t, y_true_t)
    """
    ic_records = []
    
    for d, group in df.groupby(date_col):
        clean_g = group[[pred_col, target_col]].dropna()
        if len(clean_g) > 3:
            corr, _ = stats.spearmanr(clean_g[pred_col], clean_g[target_col])
            if not np.isnan(corr):
                ic_records.append({"date": d, "rank_ic": corr})

    return pd.DataFrame(ic_records)


def calculate_ic_ir(ic_df: pd.DataFrame) -> Dict[str, float]:
    """
    Computes Mean Rank IC and IC Information Ratio (IC IR):
    IC IR = Mean(IC) / Std(IC)
    """
    if ic_df.empty or "rank_ic" not in ic_df.columns:
        return {"mean_ic": 0.0, "std_ic": 0.0, "ic_ir": 0.0}

    mean_ic = float(ic_df["rank_ic"].mean())
    std_ic = float(ic_df["rank_ic"].std())
    ic_ir = mean_ic / (std_ic + 1e-8)

    return {
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "ic_ir": ic_ir,
        "ann_ic_ir": ic_ir * np.sqrt(52.0), # Assuming weekly rebalancing
    }


def stationary_bootstrap_ci(series: pd.Series, p: float = 0.2, n_bootstrap: int = 1000, ci_level: float = 0.95) -> Tuple[float, float, float]:
    """
    Stationary Bootstrap (Politis & Romano 1994) for Time Series Confidence Intervals:
    Blocks have geometric length distribution with mean 1/p.
    Returns: (point_estimate, ci_lower, ci_upper)
    """
    arr = series.dropna().values
    n = len(arr)
    if n < 10:
        return (float(np.mean(arr)), float(np.mean(arr)), float(np.mean(arr)))

    boot_means = []
    for _ in range(n_bootstrap):
        boot_idx = []
        cur = np.random.randint(0, n)
        while len(boot_idx) < n:
            block_len = np.random.geometric(p)
            for b in range(block_len):
                if len(boot_idx) >= n:
                    break
                boot_idx.append((cur + b) % n)
            cur = np.random.randint(0, n)
        boot_means.append(np.mean(arr[boot_idx]))

    lower = float(np.percentile(boot_means, (1.0 - ci_level) / 2.0 * 100))
    upper = float(np.percentile(boot_means, (1.0 + ci_level) / 2.0 * 100))
    point = float(np.mean(arr))
    return point, lower, upper


def probabilistic_sharpe_ratio(
    observed_sr: float,
    benchmark_sr: float = 0.0,
    n_obs: int = 252,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """
    Probabilistic Sharpe Ratio (PSR) (Bailey & Lopez de Prado 2012):
    PSR(SR*) = Phi( (SR - SR*) * sqrt(N - 1) / sqrt(1 - skew * SR + (kurt - 1) / 4 * SR^2) )
    """
    sr_std = np.sqrt((1.0 - skewness * observed_sr + (kurtosis - 1.0) / 4.0 * (observed_sr ** 2)) / max(1, n_obs - 1))
    z = (observed_sr - benchmark_sr) / (sr_std + 1e-8)
    return float(stats.norm.cdf(z))


def deflated_sharpe_ratio(
    observed_sr: float,
    sharpe_var: float,
    n_trials: int,
    n_obs: int = 252,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """
    Deflated Sharpe Ratio (DSR) (Bailey & Lopez de Prado 2014):
    Adjusts the benchmark Sharpe Ratio for multiple testing across N trial models:
    SR* = sqrt(sharpe_var) * ((1 - euler_mascheroni) * Phi^-1(1 - 1/N) + euler_mascheroni * Phi^-1(1 - 1/(N * e)))
    """
    if n_trials <= 1:
        benchmark_sr = 0.0
    else:
        euler_mascheroni = 0.5772156649
        z1 = stats.norm.ppf(1.0 - 1.0 / n_trials)
        z2 = stats.norm.ppf(1.0 - 1.0 / (n_trials * np.e))
        benchmark_sr = np.sqrt(max(1e-6, sharpe_var)) * ((1.0 - euler_mascheroni) * z1 + euler_mascheroni * z2)

    return probabilistic_sharpe_ratio(observed_sr, benchmark_sr, n_obs, skewness, kurtosis)


def calculate_financial_metrics(
    portfolio_returns: pd.Series,
    benchmark_returns: Optional[pd.Series] = None,
    ann_factor: int = 52, # Weekly frequency default
    rf: float = 0.0,
) -> Dict[str, Any]:
    """
    Computes comprehensive financial performance and risk metrics.
    """
    rets = portfolio_returns.dropna()
    if len(rets) < 5:
        return {}

    cum_rets = (1.0 + rets).cumprod()
    total_ret = cum_rets.iloc[-1] - 1.0
    n_periods = len(rets)
    ann_ret = (1.0 + total_ret) ** (ann_factor / n_periods) - 1.0
    ann_vol = rets.std() * np.sqrt(ann_factor)
    sharpe = (ann_ret - rf) / (ann_vol + 1e-8)

    # Maximum Drawdown
    peak = cum_rets.cummax()
    drawdown = (cum_rets - peak) / peak
    max_dd = float(drawdown.min())
    calmar = ann_ret / (abs(max_dd) + 1e-8)

    # Win Rate & Profit Factor
    pos_rets = rets[rets > 0]
    neg_rets = rets[rets < 0]
    win_rate = float(len(pos_rets) / len(rets))
    profit_factor = float(pos_rets.sum() / (abs(neg_rets.sum()) + 1e-8))

    # Skewness & Kurtosis
    skew = float(stats.skew(rets))
    kurt = float(stats.kurtosis(rets, fisher=False))

    metrics = {
        "total_return": float(total_ret),
        "annualized_return": float(ann_ret),
        "annualized_volatility": float(ann_vol),
        "sharpe_ratio": float(sharpe),
        "max_drawdown": float(max_dd),
        "calmar_ratio": float(calmar),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor),
        "skewness": skew,
        "kurtosis": kurt,
        "psr": probabilistic_sharpe_ratio(sharpe, 0.0, n_periods, skew, kurt),
    }

    if benchmark_returns is not None and not benchmark_returns.dropna().empty:
        b_rets = benchmark_returns.reindex(rets.index).fillna(0.0)
        cov = np.cov(rets, b_rets)[0, 1]
        b_var = b_rets.var()
        beta = float(cov / (b_var + 1e-8))
        alpha = float(ann_ret - beta * ((1.0 + b_rets.mean()) ** ann_factor - 1.0))
        metrics["market_beta"] = beta
        metrics["alpha"] = alpha

    return metrics
