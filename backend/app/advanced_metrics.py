# backend/app/advanced_metrics.py

"""
Institutional Anti-Overfitting & Advanced Risk Metrics Engine.
Based on Marcos López de Prado's Quantitative Research Framework:
1. Probabilistic Sharpe Ratio (PSR):
   Calculates probability that the true Sharpe Ratio exceeds a benchmark target SR_0 given skewness and kurtosis.
2. Deflated Sharpe Ratio (DSR):
   Adjusts Sharpe Ratio for non-normality (skewness, kurtosis) and multiple testing trials (N).
   Calculates the p-value that a backtested strategy Sharpe Ratio is a result of backtest overfitting.
"""

import numpy as np
import scipy.stats as ss
from typing import Dict, List, Tuple

class AdvancedMetricsEngine:
    def __init__(self, risk_free_rate: float = 0.04):
        self.rf = risk_free_rate

    def compute_moments(self, returns: np.ndarray) -> Tuple[float, float, float, float]:
        """
        Computes Mean, Volatility, Skewness, and Excess Kurtosis of returns.
        """
        mean = float(np.mean(returns))
        std = float(np.std(returns, ddof=1))
        skew = float(ss.skew(returns)) if len(returns) > 2 else 0.0
        kurt = float(ss.kurtosis(returns)) if len(returns) > 3 else 0.0 # excess kurtosis (normal = 0)
        return mean, std, skew, kurt

    def probabilistic_sharpe_ratio(self, returns: np.ndarray, sr_benchmark: float = 0.0, annualize_factor: float = 252.0) -> float:
        """
        Calculates Probabilistic Sharpe Ratio (PSR):
        PSR = Z[ (SR_hat - SR_benchmark) * sqrt(T - 1) / sqrt(1 - skew * SR_hat + (kurt - 1)/4 * SR_hat^2) ]
        """
        T = len(returns)
        if T < 5:
            return 0.5

        mean, std, skew, kurt = self.compute_moments(returns)
        if std <= 1e-8:
            return 0.5

        sr_hat = (mean / std) * np.sqrt(annualize_factor)
        sr_bench_ann = sr_benchmark

        # Adjust for return frequency
        sr_hat_period = mean / std
        sr_bench_period = sr_benchmark / np.sqrt(annualize_factor)

        denom_sq = 1.0 - skew * sr_hat_period + ((kurt + 3.0 - 1.0) / 4.0) * (sr_hat_period ** 2)
        denom = np.sqrt(max(denom_sq, 1e-8))

        z_stat = (sr_hat_period - sr_bench_period) * np.sqrt(T - 1.0) / denom
        psr = float(ss.norm.cdf(z_stat))
        return psr

    def deflated_sharpe_ratio(self, returns: np.ndarray, num_trials: int = 100, variance_trials: float = 0.5, annualize_factor: float = 252.0) -> Dict[str, float]:
        """
        Calculates Deflated Sharpe Ratio (DSR) (Marcos López de Prado):
        Adjusts expected max Sharpe ratio under N independent trials:
        E[max_N {SR}] ~ (1 - Euler-Mascheroni * gamma) * Z^(-1)[1 - 1/N] + gamma * Z^(-1)[1 - 1/(N*e)]
        
        Returns:
            dsr_p_value: Probability that observed SR is due to backtest overfitting (p-value < 0.05 indicates genuine alpha).
            psr: Probabilistic Sharpe Ratio.
            observed_sr: Annualized Sharpe Ratio.
            expected_max_sr: Expected maximum Sharpe ratio from N random trials.
        """
        T = len(returns)
        if T < 5:
            return {"dsr_p_value": 1.0, "is_statistically_significant": False}

        mean, std, skew, kurt = self.compute_moments(returns)
        if std <= 1e-8:
            return {"dsr_p_value": 1.0, "is_statistically_significant": False}

        sr_hat = (mean / std) * np.sqrt(annualize_factor)

        # Estimate expected max SR under N trials (Euler-Mascheroni approximation)
        euler_gamma = 0.5772156649
        N = max(num_trials, 1)
        
        if N == 1:
            expected_max_sr_ann = 0.0
        else:
            z1 = ss.norm.ppf(1.0 - 1.0 / N)
            z2 = ss.norm.ppf(1.0 - 1.0 / (N * np.e))
            expected_max_sr_ann = np.sqrt(variance_trials) * ((1.0 - euler_gamma) * z1 + euler_gamma * z2)

        psr = self.probabilistic_sharpe_ratio(returns, sr_benchmark=expected_max_sr_ann, annualize_factor=annualize_factor)
        dsr_p_value = 1.0 - psr

        return {
            "observed_annualized_sr": round(sr_hat, 4),
            "expected_max_sr_trials": round(expected_max_sr_ann, 4),
            "num_testing_trials": N,
            "psr_confidence": round(psr * 100, 2),
            "dsr_p_value": round(dsr_p_value, 4),
            "is_statistically_significant": bool(dsr_p_value < 0.05)
        }

if __name__ == "__main__":
    print("Testing AdvancedMetricsEngine...")
    np.random.seed(42)
    # Generate 500 daily returns with positive drift
    returns = np.random.normal(0.0008, 0.015, 500)
    
    engine = AdvancedMetricsEngine()
    psr = engine.probabilistic_sharpe_ratio(returns, sr_benchmark=0.0)
    dsr_res = engine.deflated_sharpe_ratio(returns, num_trials=50)

    print(f"Observed Sharpe Ratio: {dsr_res['observed_annualized_sr']}")
    print(f"PSR Confidence       : {psr * 100:.2f}%")
    print(f"Deflated SR p-value  : {dsr_res['dsr_p_value']} (Significant: {dsr_res['is_statistically_significant']})")
    print("[+] AdvancedMetricsEngine operational.")
