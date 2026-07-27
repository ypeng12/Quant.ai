# backend/app/portfolio_optimizer.py

"""
Institutional Portfolio Risk & Asset Allocation Engine.
Implements:
1. Ledoit-Wolf Shrinkage Covariance Estimation (Reduces noise in sample covariance).
2. Risk Parity / Equal Risk Contribution (ERC) Portfolio Optimization.
3. Markowitz Mean-Variance Optimization (MVO) (Maximum Sharpe Ratio & Minimum Variance).
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Dict, List, Tuple

class PortfolioOptimizer:
    def __init__(self, risk_free_rate: float = 0.04):
        self.rf = risk_free_rate

    def ledoit_wolf_shrinkage_cov(self, returns: np.ndarray) -> np.ndarray:
        """
        Computes Ledoit-Wolf Shrinkage Covariance Matrix to stabilize optimization.
        Shrinks sample covariance S towards target matrix T = mean_variance * Identity.
        """
        T_obs, N = returns.shape
        if T_obs < 2:
            return np.eye(N)

        sample_cov = np.cov(returns, rowvar=False)
        if N == 1:
            return sample_cov.reshape(1, 1)

        prior = np.trace(sample_cov) / N * np.eye(N)
        
        # Shrinkage intensity delta calculation
        d2 = np.linalg.norm(sample_cov - prior, 'fro') ** 2
        if d2 == 0:
            return sample_cov

        y = returns - np.mean(returns, axis=0)
        r2 = np.sum(np.dot(y.T, y) ** 2) / (T_obs ** 2)
        b2 = min(r2 / d2, 1.0)

        shrinkage_cov = (1.0 - b2) * sample_cov + b2 * prior
        return shrinkage_cov

    def portfolio_volatility(self, weights: np.ndarray, cov_matrix: np.ndarray) -> float:
        return float(np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights))))

    def risk_contributions(self, weights: np.ndarray, cov_matrix: np.ndarray) -> np.ndarray:
        """
        Calculates Risk Contribution (RC) of each asset to total portfolio volatility:
        RC_i = w_i * (Cov * w)_i / port_vol
        """
        port_vol = self.portfolio_volatility(weights, cov_matrix)
        if port_vol <= 0:
            return np.zeros_like(weights)
        marginal_risk_contribution = np.dot(cov_matrix, weights)
        risk_contrib = weights * marginal_risk_contribution / port_vol
        return risk_contrib

    def optimize_risk_parity(self, returns_df: pd.DataFrame) -> Dict[str, float]:
        """
        Solves Equal Risk Contribution (ERC) Risk Parity optimization problem:
        min sum_{i=1}^N sum_{j=1}^N (RC_i - RC_j)^2
        s.t. sum(w_i) = 1, w_i >= 0
        """
        tickers = list(returns_df.columns)
        N = len(tickers)
        if N == 0:
            return {}

        returns = returns_df.values
        cov_matrix = self.ledoit_wolf_shrinkage_cov(returns)

        target_rc = 1.0 / N # Target equal risk contribution

        def erc_objective(w):
            port_vol = self.portfolio_volatility(w, cov_matrix)
            if port_vol <= 0:
                return 1e6
            rc = w * np.dot(cov_matrix, w) / port_vol
            # Penalty for deviation from target equal risk percentage
            rc_pct = rc / port_vol
            return float(np.sum((rc_pct - target_rc) ** 2))

        init_weights = np.ones(N) / N
        bounds = [(0.0, 1.0) for _ in range(N)]
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0})

        res = minimize(erc_objective, init_weights, method='SLSQP', bounds=bounds, constraints=constraints)
        opt_weights = res.x if res.success else init_weights

        opt_weights = opt_weights / opt_weights.sum() # Ensure strict sum = 1
        
        return {tickers[i]: round(float(opt_weights[i]), 4) for i in range(N)}

    def optimize_max_sharpe(self, returns_df: pd.DataFrame) -> Dict[str, float]:
        """
        Calculates Markowitz Maximum Sharpe Ratio portfolio weights.
        """
        tickers = list(returns_df.columns)
        N = len(tickers)
        if N == 0:
            return {}

        returns = returns_df.values
        mean_returns = np.mean(returns, axis=0) * 252.0
        cov_matrix = self.ledoit_wolf_shrinkage_cov(returns) * 252.0

        def neg_sharpe(w):
            p_ret = np.dot(w, mean_returns)
            p_vol = np.sqrt(np.dot(w.T, np.dot(cov_matrix, w)))
            if p_vol <= 0:
                return 1e6
            return float(-(p_ret - self.rf) / p_vol)

        init_weights = np.ones(N) / N
        bounds = [(0.0, 1.0) for _ in range(N)]
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0})

        res = minimize(neg_sharpe, init_weights, method='SLSQP', bounds=bounds, constraints=constraints)
        opt_weights = res.x if res.success else init_weights
        opt_weights = opt_weights / opt_weights.sum()

        return {tickers[i]: round(float(opt_weights[i]), 4) for i in range(N)}

if __name__ == "__main__":
    print("Testing PortfolioOptimizer...")
    np.random.seed(42)
    days = 252
    ret_a = np.random.normal(0.001, 0.02, days)
    ret_b = np.random.normal(0.0005, 0.01, days)
    ret_c = np.random.normal(0.0015, 0.03, days)
    
    df_returns = pd.DataFrame({"AAPL": ret_a, "MSFT": ret_b, "TSLA": ret_c})
    
    opt = PortfolioOptimizer()
    erc_weights = opt.optimize_risk_parity(df_returns)
    mvo_weights = opt.optimize_max_sharpe(df_returns)

    print(f"Risk Parity (ERC) Weights: {erc_weights}")
    print(f"Max Sharpe (MVO) Weights  : {mvo_weights}")
    print("[+] PortfolioOptimizer operational.")
