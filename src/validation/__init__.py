"""
Quant.ai Validation Module
Implements Purged Walk-Forward Cross Validation with Embargo, Rank IC, Stationary Bootstrap CIs, and Deflated Sharpe Ratio (DSR).
"""

from .purged_cv import PurgedWalkForwardCV, purge_overlap_and_embargo
from .metrics import (
    calculate_rank_ic,
    calculate_ic_ir,
    stationary_bootstrap_ci,
    probabilistic_sharpe_ratio,
    deflated_sharpe_ratio,
    calculate_financial_metrics,
)

__all__ = [
    "PurgedWalkForwardCV",
    "purge_overlap_and_embargo",
    "calculate_rank_ic",
    "calculate_ic_ir",
    "stationary_bootstrap_ci",
    "probabilistic_sharpe_ratio",
    "deflated_sharpe_ratio",
    "calculate_financial_metrics",
]
