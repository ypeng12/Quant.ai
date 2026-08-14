# backend/app/ml/almgren_chriss_execution.py
"""
Almgren-Chriss (2000) Optimal Order Execution Framework.
Solves the mean-variance optimal liquidation problem for large institutional trades.

Computes:
1. Optimal discrete trading trajectory x_k (shares remaining at step k).
2. Trade execution schedule v_k (shares traded per interval).
3. Expected total execution cost E[x] and variance V[x] under market impact parameters.
4. Stochastic price trajectory simulation.
"""

import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional

class AlmgrenChrissSchedule:
    def __init__(
        self,
        time_steps: np.ndarray,
        trajectory_x: np.ndarray,
        trade_sizes_v: np.ndarray,
        expected_cost_ex: float,
        variance_vx: float,
        half_life_hours: float
    ):
        self.time_steps = time_steps
        self.trajectory_x = trajectory_x
        self.trade_sizes_v = trade_sizes_v
        self.expected_cost_ex = expected_cost_ex
        self.variance_vx = variance_vx
        self.half_life_hours = half_life_hours

class AlmgrenChrissExecutionEngine:
    def __init__(
        self,
        total_shares: float = 100000.0,
        total_time_hours: float = 1.0,
        num_steps: int = 10,
        initial_price: float = 100.0
    ):
        self.X0 = total_shares
        self.T = total_time_hours
        self.N = num_steps
        self.tau = self.T / self.N
        self.S0 = initial_price

    def compute_optimal_schedule(
        self,
        risk_aversion: float = 1e-5,
        volatility: float = 0.02,
        eta: float = 1e-6,
        gamma: float = 2.5e-7
    ) -> AlmgrenChrissSchedule:
        """
        Computes the analytical Almgren-Chriss optimal liquidation schedule.
        Params:
            risk_aversion (lambda): Investor risk aversion coefficient (>0).
            volatility (sigma): Asset price volatility per hour.
            eta: Temporary market impact coefficient (price change per share/hr).
            gamma: Permanent market impact coefficient (permanent price shift).
        """
        # Calculate kappa: kappa^2 = (lambda * sigma^2) / eta_hat
        # eta_hat = eta * (1 - 0.5 * gamma * tau / eta)
        eta_hat = eta * (1.0 - 0.5 * (gamma * self.tau / (eta + 1e-12)))
        eta_hat = max(1e-12, eta_hat)

        kappa2 = (risk_aversion * (volatility ** 2)) / eta_hat
        kappa = np.sqrt(max(1e-12, kappa2))

        # Time steps t_k
        t_k = np.linspace(0, self.T, self.N + 1)
        
        # Hyperbolic sine closed-form trajectory x_k
        sinh_kappa_T = np.sinh(kappa * self.T) + 1e-12
        x_k = (np.sinh(kappa * (self.T - t_k)) / sinh_kappa_T) * self.X0
        x_k[-1] = 0.0  # Force complete liquidation at final step

        # Trade sizes v_k = x_{k-1} - x_k
        v_k = x_k[:-1] - x_k[1:]

        # Expected Cost E[x] = 0.5 * gamma * X0^2 + (eta_hat / tau) * sum(v_k^2)
        expected_cost_ex = 0.5 * gamma * (self.X0 ** 2) + (eta_hat / self.tau) * np.sum(v_k ** 2)

        # Cost Variance V[x] = sigma^2 * sum(tau * x_k^2)
        variance_vx = (volatility ** 2) * self.tau * np.sum(x_k[:-1] ** 2)

        half_life = np.log(2.0) / (kappa + 1e-12)

        return AlmgrenChrissSchedule(
            time_steps=t_k,
            trajectory_x=x_k,
            trade_sizes_v=v_k,
            expected_cost_ex=float(expected_cost_ex),
            variance_vx=float(variance_vx),
            half_life_hours=float(half_life)
        )

    def simulate_execution_path(
        self,
        schedule: AlmgrenChrissSchedule,
        volatility: float = 0.02,
        eta: float = 1e-6,
        gamma: float = 2.5e-7,
        random_seed: int = 42
    ) -> Dict:
        """
        Simulates a stochastic price trajectory under the computed execution schedule.
        """
        np.random.seed(random_seed)
        prices = [self.S0]
        exec_prices = []
        realized_costs = []

        current_price = self.S0
        for k in range(self.N):
            v_k = schedule.trade_sizes_v[k]
            # Price change: permanent impact + random Brownian drift
            dW = np.random.normal(0.0, np.sqrt(self.tau))
            price_drop_perm = gamma * v_k
            current_price = current_price - price_drop_perm + volatility * current_price * dW
            
            # Temporary impact on actual execution price
            exec_price = current_price - eta * (v_k / self.tau)
            exec_prices.append(exec_price)
            prices.append(current_price)

            # Cost per share relative to initial S0
            realized_costs.append(v_k * (self.S0 - exec_price))

        total_realized_cost = sum(realized_costs)
        vwap_price = sum([schedule.trade_sizes_v[i] * exec_prices[i] for i in range(self.N)]) / self.X0

        return {
            "initial_price": self.S0,
            "simulated_final_price": round(prices[-1], 2),
            "executed_vwap": round(vwap_price, 2),
            "total_realized_cost": round(total_realized_cost, 2),
            "implementation_shortfall_bps": round(((self.S0 - vwap_price) / self.S0) * 10000.0, 2)
        }

if __name__ == "__main__":
    print("Testing AlmgrenChrissExecutionEngine...")
    engine = AlmgrenChrissExecutionEngine(total_shares=100000.0, total_time_hours=1.0, num_steps=10, initial_price=150.0)
    
    # 1. Conservative execution (High Risk Aversion)
    schedule_cons = engine.compute_optimal_schedule(risk_aversion=1e-4)
    sim_cons = engine.simulate_execution_path(schedule_cons)

    print("=========================================================================")
    print("ALMGREN-CHRISS OPTIMAL EXECUTION SCHEDULE")
    print("=========================================================================")
    print(f"  Total Order Size       : 100,000 shares over 1.0 hr ({engine.N} steps)")
    print(f"  Expected Cost E[x]    : ${schedule_cons.expected_cost_ex:,.2f}")
    print(f"  Cost StdDev sqrt(V[x]): ${np.sqrt(schedule_cons.variance_vx):,.2f}")
    print(f"  Half-Life of Trajectory: {schedule_cons.half_life_hours:.3f} hrs")
    print(f"  Simulated VWAP Price   : ${sim_cons['executed_vwap']}")
    print(f"  Implementation Shortfall: {sim_cons['implementation_shortfall_bps']} bps")
    print("=========================================================================")
