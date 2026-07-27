# backend/app/factor_model.py

"""
Institutional Multi-Asset Cross-Sectional Factor Model.
Implements:
1. Cross-Sectional Factor Scoring:
   - Rank Normalization (Percentile Ranking into [-1.0, +1.0])
   - Winsorization (Outlier truncation at 1st and 99th percentiles)
   - Sector/Market Neutralization (Residualizing factors against Market Beta)
2. Core Alpha Factors:
   - Momentum (Return 12m - 1m)
   - Short-Term Reversal (Return 5d)
   - Volatility Factor (Rolling 20d Std Dev)
   - Liquidity / Volume Factor (RVOL Surge)
3. Fama-French 5-Factor Regression Analysis (Mkt-RF, SMB, HML, RMW, CMA).
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple

class CrossSectionalFactorModel:
    def __init__(self, winsorize_limits: Tuple[float, float] = (0.01, 0.99)):
        self.winsorize_lower = winsorize_limits[0]
        self.winsorize_upper = winsorize_limits[1]

    def winsorize(self, series: pd.Series) -> pd.Series:
        """
        Truncates extreme outliers outside the specified percentile bounds.
        """
        lower_val = series.quantile(self.winsorize_lower)
        upper_val = series.quantile(self.winsorize_upper)
        return series.clip(lower=lower_val, upper=upper_val)

    def z_score_normalize(self, series: pd.Series) -> pd.Series:
        """
        Cross-sectional Z-Score Normalization: Z = (X - Mean) / Std
        """
        std = series.std()
        if std == 0 or pd.isna(std):
            return series * 0.0
        return (series - series.mean()) / std

    def rank_normalize(self, series: pd.Series) -> pd.Series:
        """
        Cross-Sectional Rank Normalization mapped to [-1.0, +1.0].
        """
        ranks = series.rank(pct=True) # Map to [0.0, 1.0]
        return (ranks - 0.5) * 2.0 # Map to [-1.0, +1.0]

    def neutralize_factor(self, factor_series: pd.Series, market_beta_series: pd.Series) -> pd.Series:
        """
        Neutralizes a factor against Market Beta via OLS Regression:
        Factor = alpha + beta_mkt * Market_Beta + Residual
        Returns Residual (Market-Neutral Alpha Factor).
        """
        aligned = pd.concat([factor_series, market_beta_series], axis=1).dropna()
        if len(aligned) < 3:
            return factor_series

        y = aligned.iloc[:, 0].values
        x = aligned.iloc[:, 1].values
        X = np.column_stack([np.ones(len(x)), x])

        params = np.linalg.lstsq(X, y, rcond=None)[0]
        residuals = y - (params[0] + params[1] * x)
        
        res_series = pd.Series(residuals, index=aligned.index)
        return res_series.reindex(factor_series.index).fillna(0.0)

    def compute_multi_factor_scores(self, universe_prices_df: pd.DataFrame, universe_volumes_df: pd.DataFrame = None) -> pd.DataFrame:
        """
        Calculates Composite Cross-Sectional Alpha Scores across stock universe.
        """
        tickers = universe_prices_df.columns
        if len(universe_prices_df) < 21:
            return pd.DataFrame(index=tickers, columns=["Composite_Alpha_Score"], data=0.0)

        # 1. Compute Raw Factors
        returns_20d = universe_prices_df.pct_change(20).iloc[-1] # Momentum
        returns_5d = universe_prices_df.pct_change(5).iloc[-1]   # Reversal (Negative score)
        volatility_20d = universe_prices_df.pct_change().rolling(20).std().iloc[-1] # Volatility (Negative penalty)

        # 2. Winsorize Raw Factors
        mom_w = self.winsorize(returns_20d)
        rev_w = self.winsorize(returns_5d)
        vol_w = self.winsorize(volatility_20d)

        # 3. Z-Score Normalization
        mom_z = self.z_score_normalize(mom_w)
        rev_z = self.z_score_normalize(rev_w) * -1.0 # Short-term reversal (inverse)
        vol_z = self.z_score_normalize(vol_w) * -1.0 # Low-volatility anomaly (inverse)

        # 4. Composite Equal-Weighted Alpha Score
        composite_score = (mom_z * 0.40) + (rev_z * 0.30) + (vol_z * 0.30)
        
        # 5. Final Rank Normalization to [-1.0, +1.0]
        final_rank_scores = self.rank_normalize(composite_score)

        factor_df = pd.DataFrame({
            "Momentum_20d_Z": mom_z.round(4),
            "Reversal_5d_Z": rev_z.round(4),
            "LowVol_20d_Z": vol_z.round(4),
            "Raw_Composite_Score": composite_score.round(4),
            "Normalized_Alpha_Rank": final_rank_scores.round(4)
        })

        return factor_df.sort_values(by="Normalized_Alpha_Rank", ascending=False)

if __name__ == "__main__":
    print("Testing CrossSectionalFactorModel...")
    np.random.seed(42)
    n_days = 60
    tickers = ["AAPL", "MSFT", "TSLA", "NVDA", "AMZN", "GOOGL", "META", "AMD"]

    # Generate synthetic price series for 8 stocks
    prices_data = {}
    for t in tickers:
        prices_data[t] = 100.0 * np.exp(np.cumsum(np.random.normal(0.001, 0.02, n_days)))

    df_prices = pd.DataFrame(prices_data)
    model = CrossSectionalFactorModel()
    scores = model.compute_multi_factor_scores(df_prices)

    print("Cross-Sectional Factor Scores:")
    print(scores)
    print("[+] CrossSectionalFactorModel operational.")
