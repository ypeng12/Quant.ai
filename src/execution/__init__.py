"""
Quant.ai Execution Module
Implements Transaction Cost Modeling, Slippage, and Implementation Shortfall (IS) decomposition.
"""

from .implementation_shortfall import TransactionCostModel, ImplementationShortfallDecomposer

__all__ = ["TransactionCostModel", "ImplementationShortfallDecomposer"]
