import pandas as pd
import numpy as np
from typing import Dict, List, Tuple


def calculate_turnover(prev_weights: Dict[str, float], cur_weights: Dict[str, float]) -> float:
    """
    Calculates Portfolio Turnover between consecutive rebalance periods:
    Turnover = 0.5 * sum(|w_i,t - w_i,t-1|)
    """
    all_symbols = set(prev_weights.keys()).union(set(cur_weights.keys()))
    sum_diff = 0.0
    for s in all_symbols:
        w_prev = prev_weights.get(s, 0.0)
        w_cur = cur_weights.get(s, 0.0)
        sum_diff += abs(w_cur - w_prev)
    return 0.5 * sum_diff


class RiskParityPortfolioManager:
    """
    Constructs Portfolio Weights based on predicted Alpha Scores and Risk Parity:
    1. Select Top Quantile (Top 20%) highest predicted score assets.
    2. Allocate Inverse Volatility Weights w_i propto 1 / sigma_i.
    3. Apply max asset limit (max_asset_weight = 0.20) and normalize.
    """

    def __init__(
        self,
        top_quantile: float = 0.20,
        max_asset_weight: float = 0.20,
        long_only: bool = True,
    ):
        self.top_quantile = top_quantile
        self.max_asset_weight = max_asset_weight
        self.long_only = long_only

    def construct_portfolio(self, df_date: pd.DataFrame, score_col: str = "pred_score", vol_col: str = "vol_20d") -> Dict[str, float]:
        """
        Given a single rebalance date DataFrame, outputs dict of symbol -> target_weight.
        """
        clean_df = df_date.dropna(subset=[score_col]).copy()
        if len(clean_df) == 0:
            return {}

        n_assets = len(clean_df)
        n_select = max(1, int(n_assets * self.top_quantile))

        # Select Top N by predicted score
        top_assets = clean_df.sort_values(score_col, ascending=False).head(n_select).copy()

        # Volatility inverse weighting
        if vol_col in top_assets.columns:
            vols = top_assets[vol_col].clip(lower=0.05).fillna(0.20)
            inv_vols = 1.0 / vols
            raw_weights = inv_vols / inv_vols.sum()
        else:
            raw_weights = pd.Series(1.0 / n_select, index=top_assets.index)

        # Cap max weight per asset
        raw_weights = raw_weights.clip(upper=self.max_asset_weight)
        final_weights = raw_weights / raw_weights.sum()

        target_dict = dict(zip(top_assets["symbol"], final_weights))
        return target_dict
