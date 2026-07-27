import pandas as pd
import numpy as np
from typing import Dict, Any


class TransactionCostModel:
    """
    Simulates Transaction Costs and Slippage:
    - Base Fee: bps (default 2 bps)
    - Bid-Ask Spread & Slippage: bps (default 3 bps) -> Total Baseline Friction: 5 bps (0.05%)
    - Support for Sensitivity Matrices [2 bps, 5 bps, 10 bps, 15 bps]
    """

    def __init__(self, cost_bps: float = 5.0, slippage_bps: float = 2.0):
        self.cost_bps = cost_bps
        self.slippage_bps = slippage_bps
        self.total_bps = cost_bps + slippage_bps

    def apply_cost_to_return(self, gross_return: float, turnover: float) -> float:
        """
        Subtracts transaction costs from gross rebalance return:
        Net Return = Gross Return - Turnover * Total_BPS / 10000
        """
        cost = turnover * (self.total_bps / 10_000.0)
        return gross_return - cost


class ImplementationShortfallDecomposer:
    """
    Implementation Shortfall (Perold 1988):
    IS = side * (P_fill - P_decision) / P_decision + Fees
    Decomposed into:
    1. Delay Cost: (P_submission - P_decision) / P_decision
    2. Execution Cost: (P_fill - P_submission) / P_decision
    3. Fee / Slippage Cost
    """

    def __init__(self, fee_bps: float = 2.0):
        self.fee_bps = fee_bps

    def decompose(
        self,
        side: int, # +1 for Buy, -1 for Sell
        p_decision: float,
        p_submission: float,
        p_fill: float,
        quantity: float,
    ) -> Dict[str, float]:
        if p_decision <= 0:
            return {}

        delay_cost = side * (p_submission - p_decision) / p_decision
        execution_cost = side * (p_fill - p_submission) / p_decision
        fee_cost = self.fee_bps / 10_000.0
        total_is = delay_cost + execution_cost + fee_cost

        return {
            "side": side,
            "quantity": quantity,
            "p_decision": p_decision,
            "p_submission": p_submission,
            "p_fill": p_fill,
            "delay_cost_bps": delay_cost * 10_000.0,
            "execution_cost_bps": execution_cost * 10_000.0,
            "fee_cost_bps": fee_cost * 10_000.0,
            "total_is_bps": total_is * 10_000.0,
        }
