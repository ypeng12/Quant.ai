"""
Quant.ai Labels Module
Generates zero-leak forward 1-day and 5-day excess return labels for regression and classification.
"""

from .excess_returns import calculate_forward_excess_returns

__all__ = ["calculate_forward_excess_returns"]
