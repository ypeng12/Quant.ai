"""
Quant.ai Features Module
Implements Risk-Adjusted Momentum, Downside Sortino Momentum, Residual Momentum, and Robust Cross-Sectional Normalization.
"""

from .momentum import FeaturePipeline, calculate_sortino_momentum, robust_zscore, sector_neutralize
from .residual_momentum import calculate_residual_momentum

__all__ = [
    "FeaturePipeline",
    "calculate_sortino_momentum",
    "robust_zscore",
    "sector_neutralize",
    "calculate_residual_momentum",
]
