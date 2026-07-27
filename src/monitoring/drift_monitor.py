import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, Any


def calculate_psi(expected: np.ndarray, actual: np.ndarray, num_buckets: int = 10, eps: float = 1e-4) -> float:
    """
    Calculates Population Stability Index (PSI):
    PSI = sum((Actual% - Expected%) * ln(Actual% / Expected%))
    PSI < 0.10: Stable (Green)
    0.10 <= PSI < 0.25: Moderate Drift (Yellow)
    PSI >= 0.25: Significant Drift (Red)
    """
    expected = expected[~np.isnan(expected)]
    actual = actual[~np.isnan(actual)]

    if len(expected) < 20 or len(actual) < 20:
        return 0.0

    percentiles = np.linspace(0, 100, num_buckets + 1)
    buckets = np.percentile(expected, percentiles)
    buckets[0] = -np.inf
    buckets[-1] = np.inf

    exp_counts, _ = np.histogram(expected, bins=buckets)
    act_counts, _ = np.histogram(actual, bins=buckets)

    exp_pct = exp_counts / len(expected)
    act_pct = act_counts / len(actual)

    exp_pct = np.clip(exp_pct, eps, 1.0)
    act_pct = np.clip(act_pct, eps, 1.0)

    psi_val = np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct))
    return float(psi_val)


class FeatureDriftMonitor:
    """
    Monitors feature distribution drift between training reference window and current production window.
    """

    def __init__(self, psi_threshold_warning: float = 0.10, psi_threshold_alert: float = 0.25):
        self.psi_threshold_warning = psi_threshold_warning
        self.psi_threshold_alert = psi_threshold_alert

    def audit_drift(self, ref_df: pd.DataFrame, cur_df: pd.DataFrame, feature_cols: list) -> Dict[str, Any]:
        results = {}
        for col in feature_cols:
            if col in ref_df.columns and col in cur_df.columns:
                ref_vals = ref_df[col].dropna().values
                cur_vals = cur_df[col].dropna().values

                psi_score = calculate_psi(ref_vals, cur_vals)
                ks_stat, p_val = stats.ks_2samp(ref_vals, cur_vals)

                status = "GREEN"
                if psi_score >= self.psi_threshold_alert:
                    status = "RED"
                elif psi_score >= self.psi_threshold_warning:
                    status = "YELLOW"

                results[col] = {
                    "psi": psi_score,
                    "ks_stat": float(ks_stat),
                    "p_value": float(p_val),
                    "status": status,
                }
        return results
