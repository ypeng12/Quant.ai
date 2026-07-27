# backend/app/execution_algo.py

"""
Institutional Algorithmic Execution Engine & Market Microstructure Friction Engine.
Implements:
1. Almgren-Chriss Optimal Execution Model (Trajectory calculation balancing market impact vs inventory risk).
2. Square-Root Market Impact Friction Model (Kyle's Lambda / Almgren et al. empirical impact).
3. Time-Weighted Average Price (TWAP) Slicing Engine.
4. Volume-Weighted Average Price (VWAP) Slicing Engine with intraday volume profile modeling.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple

class ExecutionAlgoEngine:
    def __init__(self, daily_volatility: float = 0.02, avg_daily_volume: float = 1_000_000, permanent_impact_gamma: float = 2.5e-7, temporary_impact_eta: float = 2.5e-6):
        """
        Parameters:
        - daily_volatility (sigma): Asset daily return volatility.
        - avg_daily_volume (V): Average daily volume of the target asset.
        - permanent_impact_gamma: Gamma coefficient for permanent price impact.
        - temporary_impact_eta: Eta coefficient for temporary price impact.
        """
        self.sigma = daily_volatility
        self.V = avg_daily_volume
        self.gamma = permanent_impact_gamma
        self.eta = temporary_impact_eta

    def square_root_market_impact(self, trade_size: int, current_price: float, interval_volume: float = None) -> Tuple[float, float]:
        """
        Calculates market impact using the empirical Square-Root Law:
        Impact_pct = eta * sigma * sqrt(Q / V)
        Returns:
            temp_impact_dollars: float (temporary impact per share)
            perm_impact_dollars: float (permanent impact per share)
        """
        if interval_volume is None or interval_volume <= 0:
            interval_volume = self.V / 390.0 # Default 1-minute volume (390 trading minutes)
        
        participation_rate = trade_size / max(interval_volume, 1.0)
        temp_impact_pct = self.eta * self.sigma * np.sqrt(max(trade_size, 0.0) / max(interval_volume, 1.0))
        perm_impact_pct = self.gamma * (trade_size / max(self.V, 1.0))

        temp_impact_dollars = current_price * temp_impact_pct
        perm_impact_dollars = current_price * perm_impact_pct
        return temp_impact_dollars, perm_impact_dollars

    def generate_twap_schedule(self, total_shares: int, num_slices: int) -> List[int]:
        """
        Splits total_shares evenly across num_slices execution intervals.
        """
        if num_slices <= 0:
            return [total_shares]
        base_slice = total_shares // num_slices
        remainder = total_shares % num_slices
        
        schedule = [base_slice] * num_slices
        for i in range(remainder):
            schedule[i] += 1
        return schedule

    def generate_vwap_schedule(self, total_shares: int, intraday_volume_profile: List[float] = None) -> List[int]:
        """
        Splits total_shares proportional to expected intraday U-shaped volume profile.
        """
        if intraday_volume_profile is None or len(intraday_volume_profile) == 0:
            # Default 13 half-hour buckets U-shaped volume curve for US Equity market (09:30 - 16:00)
            u_shape = np.array([0.18, 0.10, 0.07, 0.05, 0.04, 0.04, 0.04, 0.04, 0.05, 0.06, 0.08, 0.11, 0.14])
            intraday_volume_profile = u_shape / u_shape.sum()

        profile = np.array(intraday_volume_profile)
        profile = profile / profile.sum()
        
        raw_schedule = profile * total_shares
        schedule = np.floor(raw_schedule).astype(int)
        remainder = total_shares - schedule.sum()
        
        # Distribute remainder to highest fractional parts
        fractional = raw_schedule - schedule
        top_indices = np.argsort(fractional)[::-1][:remainder]
        for idx in top_indices:
            schedule[idx] += 1
            
        return schedule.tolist()

    def almgren_chriss_optimal_trajectory(self, total_shares: int, total_time_intervals: int, risk_aversion_lambda: float = 1e-5) -> Tuple[np.ndarray, np.ndarray, float]:
        """
        Computes Almgren-Chriss Optimal Execution Trajectory.
        Solves: min E[Total Cost] + lambda * Var[Total Cost]
        
        Returns:
            x: np.ndarray (inventory schedule remaining at each step)
            n: np.ndarray (trade size executed at each interval)
            expected_total_cost: float
        """
        N = total_time_intervals
        tau = 1.0 / N # normalized interval
        
        # Almgren-Chriss parameters
        # kappa^2 ~ (lambda * sigma^2 / eta) * tau
        kappa_sq = (risk_aversion_lambda * (self.sigma ** 2) / max(self.eta, 1e-9)) * tau
        kappa = np.sqrt(max(kappa_sq, 1e-8))
        
        t = np.arange(N + 1)
        
        # Closed-form Almgren-Chriss inventory trajectory:
        # x_j = sinh(kappa * (T - t_j)) / sinh(kappa * T) * X_0
        T = 1.0 # normalized total time
        t_j = t * tau
        
        sinh_kappa_T = np.sinh(kappa * T)
        if np.isinf(sinh_kappa_T) or sinh_kappa_T == 0:
            # Fallback to linear TWAP if numerical overflow occurs
            x = total_shares * (1.0 - t_j / T)
        else:
            x = total_shares * np.sinh(kappa * (T - t_j)) / sinh_kappa_T
            
        x = np.maximum(x, 0.0)
        x[0] = total_shares
        x[-1] = 0.0
        
        # Trade sizes at each step
        n = -np.diff(x)
        
        # Compute Expected Total Cost (Permanent Impact + Temporary Impact)
        perm_cost = 0.5 * self.gamma * (total_shares ** 2)
        temp_cost = self.eta * np.sum(n ** 2) / tau
        expected_cost = perm_cost + temp_cost
        
        return np.round(x, 2), np.round(n, 2), float(expected_cost)

if __name__ == "__main__":
    print("Testing ExecutionAlgoEngine...")
    algo = ExecutionAlgoEngine(daily_volatility=0.02, avg_daily_volume=5_000_000)
    
    # 1. Market Impact Test
    temp_i, perm_i = algo.square_root_market_impact(trade_size=10_000, current_price=150.0, interval_volume=50_000)
    print(f"Square-Root Impact for 10k shares at $150: Temp = ${temp_i:.4f}/sh, Perm = ${perm_i:.4f}/sh")

    # 2. TWAP / VWAP Slicing Test
    twap = algo.generate_twap_schedule(100_000, 10)
    vwap = algo.generate_vwap_schedule(100_000)
    print(f"TWAP (10 slices): {twap}")
    print(f"VWAP (13 slices): {vwap}")

    # 3. Almgren-Chriss Trajectory Test
    x_traj, n_trades, cost = algo.almgren_chriss_optimal_trajectory(total_shares=100_000, total_time_intervals=10, risk_aversion_lambda=1e-5)
    print(f"Almgren-Chriss Trade Slices: {n_trades}")
    print(f"Expected Implementation Shortfall Cost: ${cost:.2f}")
    print("[+] ExecutionAlgoEngine operational.")
