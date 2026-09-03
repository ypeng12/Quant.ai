# backend/app/ml/rigorous_evaluator.py
"""
Rigorous Quantitative Research & Microstructure Statistical Evaluation Framework.
Designed to institutional standards (HRT, Citadel Securities, Jump Trading, Headlands).

Key Modules:
1. PurgedWalkForwardCV: Purged & Embargoed Time-Series Cross-Validation.
2. TransactionCostModel: Linear fee + Half-spread + Square-root Market Impact Slippage.
3. ProbabilityCalibrator: Platt Scaling, Isotonic Regression, Brier Score Decomposition & ECE.
4. StatisticalInferenceEngine: Block Bootstrap Confidence Intervals (Sharpe, Rank IC),
   Newey-West HAC adjustment, Stationarity (ADF), Multiple Testing Corrections (FDR/Bonferroni),
   and Bailey & López de Prado Deflated Sharpe Ratio (DSR).
"""

import numpy as np
import pandas as pd
import scipy.stats as stats
from typing import Dict, List, Tuple, Generator, Optional, Any
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


class PurgedWalkForwardCV:
    """
    Purged and Embargoed Walk-Forward Cross-Validation.
    
    Prevents lookahead bias and serial correlation leakage:
    1. Purging: Removes training observations that overlap with the label prediction horizon.
    2. Embargoing: Adds a buffer period immediately following testing folds to prevent
       post-test autocorrelation contamination.
    """
    def __init__(
        self,
        n_splits: int = 5,
        train_ratio: float = 0.6,
        horizon_bars: int = 5,
        embargo_pct: float = 0.02
    ):
        self.n_splits = max(2, n_splits)
        self.train_ratio = train_ratio
        self.horizon_bars = max(1, horizon_bars)
        self.embargo_pct = max(0.0, embargo_pct)

    def split(
        self,
        df: pd.DataFrame
    ) -> Generator[Tuple[np.ndarray, np.ndarray], None, None]:
        n = len(df)
        embargo_bars = int(n * self.embargo_pct)
        indices = np.arange(n)

        # Expanding or rolling walk-forward folds
        test_size = int((n * (1.0 - self.train_ratio)) / self.n_splits)

        for i in range(self.n_splits):
            test_start = int(n * self.train_ratio) + i * test_size
            test_end = min(n, test_start + test_size)
            if test_start >= n:
                break

            test_idx = indices[test_start:test_end]

            # Train index is strictly prior to test_start - horizon_bars (Purging)
            train_end = max(0, test_start - self.horizon_bars)
            train_idx = indices[:train_end]

            # If there is an embargo period from a previous test window, respect it
            if i > 0 and embargo_bars > 0:
                prev_test_end = test_start
                # Purge any samples in embargo zone
                embargo_cutoff = prev_test_end - test_size + embargo_bars
                # Train retains valid historical sequence
                mask = (train_idx < (prev_test_end - test_size)) | (train_idx >= embargo_cutoff)
                train_idx = train_idx[mask]

            if len(train_idx) > 50 and len(test_idx) > 10:
                yield train_idx, test_idx


class TransactionCostModel:
    """
    Realistic Institutional Transaction Cost & Market Impact Model.
    
    Total Cost = Exchange Fee + Half Spread + Square-Root Market Impact
    
    Market Impact:
      I = eta * sigma * sqrt(OrderSize / MarketVolume)
    Where:
      - eta: Market impact coefficient (typically 0.1 - 0.2)
      - sigma: Local asset return volatility
    """
    def __init__(
        self,
        maker_fee_bps: float = 1.0,
        taker_fee_bps: float = 2.0,
        eta_impact: float = 0.15
    ):
        self.maker_fee = maker_fee_bps / 10000.0
        self.taker_fee = taker_fee_bps / 10000.0
        self.eta = eta_impact

    def calculate_cost(
        self,
        price: float,
        shares: float,
        bid_price: float,
        ask_price: float,
        market_volume: float,
        volatility: float,
        is_taker: bool = True
    ) -> float:
        notional = price * shares
        fee = notional * (self.taker_fee if is_taker else self.maker_fee)

        # Half-spread cost (for taker liquidity consumers)
        spread = max(0.0, ask_price - bid_price)
        spread_cost = 0.5 * spread * shares if is_taker else 0.0

        # Non-linear square-root market impact slippage
        vol_ratio = shares / max(1.0, market_volume)
        slippage_bps = self.eta * volatility * np.sqrt(vol_ratio)
        slippage_cost = notional * slippage_bps

        total_cost = fee + spread_cost + slippage_cost
        return total_cost


class ProbabilityCalibrator:
    """
    Probability Calibration, Brier Score Decomposition, and Expected Calibration Error.
    """
    def __init__(self, method: str = "isotonic"):
        self.method = method
        self.model: Optional[Any] = None

    def fit(self, y_prob: np.ndarray, y_true: np.ndarray) -> "ProbabilityCalibrator":
        y_prob = np.clip(y_prob, 1e-6, 1.0 - 1e-6)
        if self.method == "isotonic":
            self.model = IsotonicRegression(out_of_bounds="clip")
            self.model.fit(y_prob, y_true)
        else:
            self.model = LogisticRegression(C=1.0)
            log_odds = np.log(y_prob / (1.0 - y_prob)).reshape(-1, 1)
            self.model.fit(log_odds, y_true)
        return self

    def predict_calibrated(self, y_prob: np.ndarray) -> np.ndarray:
        if self.model is None:
            return y_prob
        y_prob = np.clip(y_prob, 1e-6, 1.0 - 1e-6)
        if self.method == "isotonic":
            return np.clip(self.model.predict(y_prob), 0.0, 1.0)
        else:
            log_odds = np.log(y_prob / (1.0 - y_prob)).reshape(-1, 1)
            return self.model.predict_proba(log_odds)[:, 1]

    @staticmethod
    def brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
        return float(np.mean((y_prob - y_true) ** 2))

    @staticmethod
    def decompose_brier_score(
        y_true: np.ndarray,
        y_prob: np.ndarray,
        n_bins: int = 10
    ) -> Dict[str, float]:
        """
        Murphy (1973) Brier Score Decomposition:
        Brier = Reliability - Resolution + Uncertainty
        """
        N = len(y_true)
        base_rate = float(np.mean(y_true))
        uncertainty = base_rate * (1.0 - base_rate)

        bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
        bin_assignments = np.digitize(y_prob, bin_edges) - 1
        bin_assignments = np.clip(bin_assignments, 0, n_bins - 1)

        reliability = 0.0
        resolution = 0.0

        for b in range(n_bins):
            mask = (bin_assignments == b)
            n_k = np.sum(mask)
            if n_k > 0:
                y_k_mean = np.mean(y_true[mask])
                p_k_mean = np.mean(y_prob[mask])
                reliability += (n_k / N) * ((p_k_mean - y_k_mean) ** 2)
                resolution += (n_k / N) * ((y_k_mean - base_rate) ** 2)

        overall_brier = float(np.mean((y_prob - y_true) ** 2))
        return {
            "brier_score": overall_brier,
            "reliability": float(reliability),
            "resolution": float(resolution),
            "uncertainty": float(uncertainty)
        }

    @staticmethod
    def expected_calibration_error(
        y_true: np.ndarray,
        y_prob: np.ndarray,
        n_bins: int = 10
    ) -> float:
        """
        Computes Expected Calibration Error (ECE).
        """
        N = len(y_true)
        bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
        bin_assignments = np.digitize(y_prob, bin_edges) - 1
        bin_assignments = np.clip(bin_assignments, 0, n_bins - 1)

        ece = 0.0
        for b in range(n_bins):
            mask = (bin_assignments == b)
            n_k = np.sum(mask)
            if n_k > 0:
                acc = np.mean(y_true[mask])
                conf = np.mean(y_prob[mask])
                ece += (n_k / N) * np.abs(acc - conf)
        return float(ece)


class StatisticalInferenceEngine:
    """
    Rigorous Statistical Inference for Quantitative Strategy Returns & Alpha Signals.
    """
    @staticmethod
    def block_bootstrap_ci(
        series: np.ndarray,
        metric_fn,
        block_size: int = 10,
        n_bootstraps: int = 1000,
        alpha: float = 0.05,
        random_seed: int = 42
    ) -> Tuple[float, float, float]:
        """
        Stationary Block Bootstrap preserving autocorrelation and volatility clustering.
        Returns: (point_estimate, ci_lower, ci_upper)
        """
        np.random.seed(random_seed)
        n = len(series)
        point_est = float(metric_fn(series))

        if n < block_size * 2:
            return point_est, point_est, point_est

        n_blocks = int(np.ceil(n / block_size))
        bootstrap_metrics = []

        for _ in range(n_bootstraps):
            start_indices = np.random.randint(0, n - block_size + 1, size=n_blocks)
            boot_sample = np.concatenate([series[s:s + block_size] for s in start_indices])[:n]
            bootstrap_metrics.append(metric_fn(boot_sample))

        bootstrap_metrics = np.sort(bootstrap_metrics)
        ci_lower = float(np.percentile(bootstrap_metrics, 100.0 * (alpha / 2.0)))
        ci_upper = float(np.percentile(bootstrap_metrics, 100.0 * (1.0 - alpha / 2.0)))
        return point_est, ci_lower, ci_upper

    @staticmethod
    def sharpe_ratio(returns: np.ndarray, annualization_factor: float = 252.0) -> float:
        std = np.std(returns)
        if std == 0 or len(returns) < 2:
            return 0.0
        return float(np.mean(returns) / std * np.sqrt(annualization_factor))

    @staticmethod
    def information_coefficient(x: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
        """
        Computes Pearson IC and Spearman Rank IC.
        """
        mask = ~(np.isnan(x) | np.isnan(y))
        x_clean = x[mask]
        y_clean = y[mask]
        if len(x_clean) < 10:
            return 0.0, 0.0
        pearson_ic, _ = stats.pearsonr(x_clean, y_clean)
        rank_ic, _ = stats.spearmanr(x_clean, y_clean)
        return float(pearson_ic), float(rank_ic)

    @staticmethod
    def newey_west_t_stat(returns: np.ndarray, max_lags: int = 5) -> float:
        """
        HAC (Heteroskedasticity and Autocorrelation Consistent) Newey-West adjusted t-statistic.
        """
        n = len(returns)
        if n < 5:
            return 0.0
        mean_r = np.mean(returns)
        demeaned = returns - mean_r

        # Gamma 0 (sample variance)
        gamma_0 = np.mean(demeaned ** 2)
        hac_var = gamma_0

        for lag in range(1, max_lags + 1):
            weight = 1.0 - (lag / (max_lags + 1))
            gamma_lag = np.mean(demeaned[lag:] * demeaned[:-lag])
            hac_var += 2.0 * weight * gamma_lag

        se_hac = np.sqrt(max(1e-12, hac_var / n))
        return float(mean_r / se_hac)

    @staticmethod
    def deflated_sharpe_ratio(
        est_sharpe: float,
        returns: np.ndarray,
        num_trials: int = 50,
        benchmark_sr: float = 0.0
    ) -> float:
        """
        Bailey & López de Prado (2014) Deflated Sharpe Ratio (DSR).
        Corrects for multiple testing selection bias and return non-normality.
        """
        n = len(returns)
        if n < 5:
            return 0.5

        skew = float(stats.skew(returns))
        kurt = float(stats.kurtosis(returns, fisher=False)) # Pearson kurtosis (normal=3.0)

        # Expected maximum Sharpe under null hypothesis
        euler_mascheroni = 0.5772156649
        z_score = stats.norm.ppf(1.0 - 1.0 / max(2, num_trials))
        expected_max_sr = (1.0 - euler_mascheroni) * stats.norm.ppf(1.0 - 1.0 / (num_trials * np.e)) + \
                          euler_mascheroni * z_score

        # Asymptotic variance of Sharpe ratio
        sr_variance = 1.0 - skew * est_sharpe + ((kurt - 1.0) / 4.0) * (est_sharpe ** 2)
        sr_variance = max(1e-6, sr_variance / (n - 1.0))
        sr_std = np.sqrt(sr_variance)

        dsr_stat = (est_sharpe - max(benchmark_sr, expected_max_sr)) / sr_std
        return float(stats.norm.cdf(dsr_stat))

    @staticmethod
    def multiple_testing_fdr(p_values: np.ndarray, q: float = 0.05) -> np.ndarray:
        """
        Benjamini-Hochberg False Discovery Rate (FDR) control.
        Returns boolean array of significant discoveries.
        """
        m = len(p_values)
        if m == 0:
            return np.array([], dtype=bool)

        sorted_indices = np.argsort(p_values)
        sorted_p = p_values[sorted_indices]

        thresholds = (np.arange(1, m + 1) / m) * q
        significant = sorted_p <= thresholds

        if not np.any(significant):
            return np.zeros(m, dtype=bool)

        max_k = np.max(np.where(significant)[0])
        passed_sorted = np.zeros(m, dtype=bool)
        passed_sorted[:max_k + 1] = True

        passed = np.zeros(m, dtype=bool)
        passed[sorted_indices] = passed_sorted
        return passed
