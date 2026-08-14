# backend/app/ml/hierarchical_risk_parity.py
"""
López de Prado (2016) Hierarchical Risk Parity (HRP) Portfolio Optimizer.
Implements:
1. Ledoit-Wolf Covariance Matrix Shrinkage for Noise Reduction.
2. Distance Matrix Calculation & Single-Linkage Hierarchical Clustering.
3. Quasi-Diagonalization for Correlation Matrix Reordering.
4. Recursive Bisection Asset Weight Allocation.

Avoids matrix inversion (Sigma^-1), resulting in superior out-of-sample stability
over classical Markowitz Mean-Variance Optimization.
"""

import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import squareform
from sklearn.covariance import LedoitWolf

class HierarchicalRiskParityOptimizer:
    def __init__(self, use_ledoit_wolf: bool = True):
        self.use_ledoit_wolf = use_ledoit_wolf

    def compute_cov_and_corr(self, returns_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Computes robust covariance and correlation matrices.
        """
        clean_returns = returns_df.dropna().values
        if self.use_ledoit_wolf and len(clean_returns) > 10:
            lw = LedoitWolf()
            cov_arr = lw.fit(clean_returns).covariance_
            cov_df = pd.DataFrame(cov_arr, index=returns_df.columns, columns=returns_df.columns)
        else:
            cov_df = returns_df.cov()

        # Derive correlation matrix from covariance
        std_vec = np.sqrt(np.diag(cov_df.values))
        std_outer = np.outer(std_vec, std_vec)
        corr_arr = cov_df.values / (std_outer + 1e-12)
        corr_df = pd.DataFrame(corr_arr, index=returns_df.columns, columns=returns_df.columns)

        return cov_df, corr_df

    def compute_distance_matrix(self, corr_df: pd.DataFrame) -> np.ndarray:
        """
        Computes distance matrix d_ij = sqrt(0.5 * (1 - rho_ij)).
        """
        dist_arr = np.sqrt(np.clip(0.5 * (1.0 - corr_df.values), 0.0, 1.0))
        np.fill_diagonal(dist_arr, 0.0)
        return dist_arr

    def quasi_diagonalize(self, link_matrix: np.ndarray) -> List[int]:
        """
        Reorders assets based on hierarchical tree structure (Quasi-Diagonalization).
        """
        return list(leaves_list(link_matrix))

    def _get_cluster_var(self, cov_df: pd.DataFrame, cluster_items: List[str]) -> float:
        """
        Computes inverse-variance allocation variance within a cluster.
        """
        cov_sub = cov_df.loc[cluster_items, cluster_items].values
        inv_diag = 1.0 / (np.diag(cov_sub) + 1e-12)
        weights = inv_diag / (np.sum(inv_diag) + 1e-12)
        cluster_var = float(np.dot(np.dot(weights, cov_sub), weights))
        return cluster_var

    def recursive_bisection(self, cov_df: pd.DataFrame, sorted_items: List[str]) -> pd.Series:
        """
        Recursively bisects asset clusters and assigns weights based on inverse cluster variance.
        """
        weights = pd.Series(1.0, index=sorted_items)
        clusters = [sorted_items]

        while len(clusters) > 0:
            new_clusters = []
            for cluster in clusters:
                if len(cluster) > 1:
                    mid = len(cluster) // 2
                    left = cluster[:mid]
                    right = cluster[mid:]

                    var_left = self._get_cluster_var(cov_df, left)
                    var_right = self._get_cluster_var(cov_df, right)

                    alpha = 1.0 - (var_left / (var_left + var_right + 1e-12))
                    weights[left] *= alpha
                    weights[right] *= (1.0 - alpha)

                    if len(left) > 1:
                        new_clusters.append(left)
                    if len(right) > 1:
                        new_clusters.append(right)
            clusters = new_clusters

        return weights

    def fit_predict(self, returns_df: pd.DataFrame) -> Dict[str, float]:
        """
        Runs HRP optimization end-to-end.
        Returns:
            Dict mapping asset names to HRP optimal portfolio weights.
        """
        asset_names = list(returns_df.columns)
        cov_df, corr_df = self.compute_cov_and_corr(returns_df)
        dist_matrix = self.compute_distance_matrix(corr_df)

        # Single linkage clustering
        dist_condensed = squareform(dist_matrix, checks=False)
        link_matrix = linkage(dist_condensed, method="single")

        # Quasi-diagonalization
        sort_idx = self.quasi_diagonalize(link_matrix)
        sorted_assets = [asset_names[i] for i in sort_idx]

        # Recursive Bisection
        hrp_weights = self.recursive_bisection(cov_df, sorted_assets)
        hrp_weights = hrp_weights / hrp_weights.sum()

        result_dict = {asset: round(float(hrp_weights[asset]), 4) for asset in asset_names}
        return result_dict

if __name__ == "__main__":
    print("Testing HierarchicalRiskParityOptimizer...")
    np.random.seed(42)
    n_days = 252
    
    # Synthetic correlated asset returns (5 assets)
    tech1 = np.random.normal(0.001, 0.02, n_days)
    tech2 = tech1 * 0.85 + np.random.normal(0.0, 0.005, n_days)  # Highly correlated to tech1
    bond1 = np.random.normal(0.0002, 0.005, n_days)             # Low volatility bond
    bond2 = bond1 * 0.9 + np.random.normal(0.0, 0.001, n_days)   # Highly correlated to bond1
    gold  = np.random.normal(0.0005, 0.015, n_days)             # Uncorrelated commodity

    df_returns = pd.DataFrame({
        "AAPL_Tech": tech1,
        "MSFT_Tech": tech2,
        "TLT_Bond1": bond1,
        "IEF_Bond2": bond2,
        "GLD_Gold": gold
    })

    hrp_opt = HierarchicalRiskParityOptimizer(use_ledoit_wolf=True)
    weights = hrp_opt.fit_predict(df_returns)

    print("=========================================================================")
    print("HIERARCHICAL RISK PARITY (HRP) PORTFOLIO ALLOCATION WEIGHTS")
    print("=========================================================================")
    for asset, weight in weights.items():
        print(f"  {asset:<16}: {weight * 100.0:>6.2f}%")
    print(f"  Total Allocation   : {sum(weights.values()) * 100.0:>6.2f}%")
    print("=========================================================================")
