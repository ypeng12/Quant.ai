# backend/app/ml/monte_carlo_engine.py
"""
Monte Carlo Scenario Stress-Testing & CVaR Tail Risk Engine.
Implements:
1. Block Bootstrap Resampling on real trade records (backend/trade_history.json) & strategy returns.
2. 1,000 parallel universe Equity Curve Cloud simulation under stochastic slippage friction.
3. Quantile Tail Risk Estimation: Value at Risk (VaR 95%), Conditional VaR (CVaR 95%), Max Drawdown distribution.
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional

TRADE_HISTORY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "trade_history.json")

class MonteCarloTailRiskEngine:
    def __init__(self, num_simulations: int = 1000, block_size: int = 10):
        self.num_simulations = num_simulations
        self.block_size = block_size

    def load_historical_trade_returns(self) -> np.ndarray:
        """
        Loads realized trade return percentages from trade_history.json.
        """
        if not os.path.exists(TRADE_HISTORY_PATH):
            # Synthetic default trade returns if trade_history.json is missing
            np.random.seed(42)
            return np.random.normal(loc=0.002, scale=0.015, size=200)

        try:
            with open(TRADE_HISTORY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            trades = data.get("trade_history", [])

            returns = []
            for t in trades:
                pnl = float(t.get("pnl", 0.0))
                shares = float(t.get("shares", 0.0))
                price = float(t.get("price", 1.0))
                cost = max(1.0, shares * price)

                # Return % per trade
                ret_pct = pnl / cost
                if ret_pct != 0.0:
                    returns.append(ret_pct)

            if len(returns) < 10:
                np.random.seed(42)
                return np.random.normal(loc=0.002, scale=0.015, size=200)

            return np.array(returns)
        except Exception:
            np.random.seed(42)
            return np.random.normal(loc=0.002, scale=0.015, size=200)

    def run_monte_carlo_simulation(
        self,
        trade_returns: Optional[np.ndarray] = None,
        initial_capital: float = 100_000.0,
        slippage_penalty_pct: float = 0.0005
    ) -> Dict:
        """
        Runs 1,000 Block-Bootstrap parallel scenario simulations under stochastic execution friction.
        Returns:
            Dict containing equity_clouds (percentiles), max_drawdown_dist, var_95, cvar_95, and ruin_probability.
        """
        if trade_returns is None or len(trade_returns) == 0:
            trade_returns = self.load_historical_trade_returns()

        num_trades = len(trade_returns)
        num_sims = self.num_simulations
        
        simulated_equity_curves = []
        max_drawdowns = []

        np.random.seed(42)

        for _ in range(num_sims):
            # Stationary Block Bootstrap resampling
            sampled_indices = []
            while len(sampled_indices) < num_trades:
                start_idx = np.random.randint(0, max(1, num_trades - self.block_size))
                sampled_indices.extend(range(start_idx, min(num_trades, start_idx + self.block_size)))

            sampled_indices = sampled_indices[:num_trades]
            bootstrapped_rets = trade_returns[sampled_indices].copy()

            # Add stochastic execution slippage friction
            slippage = np.random.exponential(scale=slippage_penalty_pct, size=num_trades)
            net_rets = bootstrapped_rets - slippage

            # Cumulative Equity Curve
            equity_path = initial_capital * np.cumprod(1.0 + net_rets)
            simulated_equity_curves.append(equity_path)

            # Maximum Drawdown calculation
            peak = np.maximum.accumulate(equity_path)
            drawdown = (equity_path - peak) / peak
            max_dd = float(np.min(drawdown)) # Negative number
            max_drawdowns.append(max_dd)

        simulated_equity_matrix = np.array(simulated_equity_curves)
        max_drawdowns = np.array(max_drawdowns)

        final_equities = simulated_equity_matrix[:, -1]
        final_returns = (final_equities - initial_capital) / initial_capital

        # Value at Risk (VaR 95%) & Conditional VaR (CVaR 95% / Expected Shortfall)
        var_95 = float(np.percentile(final_returns, 5))
        cvar_95 = float(np.mean(final_returns[final_returns <= var_95])) if len(final_returns[final_returns <= var_95]) > 0 else var_95

        p50_equity = np.percentile(simulated_equity_matrix, 50, axis=0).tolist()
        p05_equity = np.percentile(simulated_equity_matrix, 5, axis=0).tolist()
        p95_equity = np.percentile(simulated_equity_matrix, 95, axis=0).tolist()

        ruin_count = np.sum(max_drawdowns < -0.20) # Drawdown worse than 20%
        ruin_probability = float(ruin_count / num_sims)

        return {
            "num_trades_per_sim": num_trades,
            "num_simulations": num_sims,
            "initial_capital": initial_capital,
            "mean_final_equity": round(float(np.mean(final_equities)), 2),
            "median_final_equity": round(float(np.median(final_equities)), 2),
            "var_95_pct": round(var_95 * 100.0, 2),
            "cvar_95_pct": round(cvar_95 * 100.0, 2),
            "mean_max_drawdown_pct": round(float(np.mean(max_drawdowns)) * 100.0, 2),
            "p95_max_drawdown_pct": round(float(np.percentile(max_drawdowns, 5)) * 100.0, 2),
            "ruin_probability_pct": round(ruin_probability * 100.0, 2),
            "equity_cloud_summary": {
                "p05_tail": [round(v, 2) for v in p05_equity[::max(1, len(p05_equity)//20)]],
                "p50_median": [round(v, 2) for v in p50_equity[::max(1, len(p50_equity)//20)]],
                "p95_top": [round(v, 2) for v in p95_equity[::max(1, len(p95_equity)//20)]],
            }
        }

if __name__ == "__main__":
    print("Testing MonteCarloTailRiskEngine...")
    mc_engine = MonteCarloTailRiskEngine(num_simulations=1000)
    res = mc_engine.run_monte_carlo_simulation()
    print("=========================================================================")
    print("MONTE CARLO SIMULATION & CVaR TAIL RISK RESULTS (1,000 SCENARIOS)")
    print("=========================================================================")
    print(f"* Realized Trade Log Sample Count  : {res['num_trades_per_sim']:,}")
    print(f"* Median Simulated Final Equity   : ${res['median_final_equity']:,.2f}")
    print(f"* 95% Value at Risk (VaR 95%)     : {res['var_95_pct']:.2f}%")
    print(f"* 95% Conditional VaR (CVaR 95%)  : {res['cvar_95_pct']:.2f}%")
    print(f"* Mean Maximum Drawdown           : {res['mean_max_drawdown_pct']:.2f}%")
    print(f"* 95th Percentile Max Drawdown     : {res['p95_max_drawdown_pct']:.2f}%")
    print(f"* >20% Drawdown Ruin Probability  : {res['ruin_probability_pct']:.2f}%")
    print("=========================================================================")
