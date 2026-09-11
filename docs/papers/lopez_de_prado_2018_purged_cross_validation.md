# Cross-Validation in Finance: Purging and Embargoing

- **Author**: Marcos López de Prado
- **Book**: *Advances in Financial Machine Learning*, Chapter 7 (Wiley, 2018)
- **Local Path**: `papers/lopez_de_prado_2018_purged_cross_validation.md`

---

## 1. Executive Summary

Standard Machine Learning cross-validation techniques (such as K-Fold or Stratified K-Fold) assume that observations are **Independent and Identically Distributed (IID)**. Financial time series violate the IID assumption in two critical ways:

1. **Overlapping Labels**: If a model predicts 5-day forward excess returns, observation $t$ and observation $t+2$ share 3 days of identical market price action.
2. **Serial Correlation**: Financial features (e.g. moving averages, volatility estimators) possess long memory, causing features in the training set to leak information about test set targets.

When standard K-Fold CV is used in finance, backtest performance is vastly overestimated due to **Information Leakage**. López de Prado introduced **Purging** and **Embargoing** to solve this fundamental problem.

---

## 2. Core Concepts & Algorithmic Design

### 2.1 Purging
Purging removes any observation from the **training dataset** whose evaluation window overlaps with the **test dataset**. 

Let $T_{i,\text{start}}$ and $T_{i,\text{end}}$ be the start and end timestamps for label $i$. Observation $i$ in the training set is **purged** if:

$$\text{Overlap}(i, \text{Test}) = [T_{i,\text{start}}, T_{i,\text{end}}] \cap [T_{\text{test},\text{start}}, T_{\text{test},\text{end}}] \neq \emptyset$$

### 2.2 Embargoing
Even after purging overlapping labels, serial correlation in feature data can cause leakage immediately after a test fold. **Embargoing** drops a buffer period (typically 1% to 5% of total dataset length) from the training set immediately following the end of the test fold:

$$\text{Train}_{\text{valid}} = \text{Train} \setminus [T_{\text{test},\text{end}}, T_{\text{test},\text{end}} + h_{\text{embargo}}]$$

---

## 3. Python Implementation (PurgedGroupTimeSeriesSplit)

```python
import numpy as np
import pandas as pd

class PurgedGroupTimeSeriesSplit:
    """
    Purged & Embargoed Cross-Validation Generator for Financial Datasets
    """
    def __init__(self, n_splits=5, pct_embargo=0.01):
        self.n_splits = n_splits
        self.pct_embargo = pct_embargo

    def split(self, X, y=None, pred_times=None, eval_times=None):
        """
        Yields (train_indices, test_indices) with purging and embargoing.
        pred_times: Series of timestamps when feature was generated.
        eval_times: Series of timestamps when label was evaluated (e.g. t + 5 days).
        """
        n_samples = len(X)
        embargo_size = int(n_samples * self.pct_embargo)
        fold_size = n_samples // self.n_splits

        indices = np.arange(n_samples)

        for i in range(self.n_splits):
            test_start = i * fold_size
            test_end = (i + 1) * fold_size if i < self.n_splits - 1 else n_samples
            test_idx = indices[test_start:test_end]

            test_eval_max = eval_times.iloc[test_idx].max()
            test_pred_min = pred_times.iloc[test_idx].min()

            # Purge training indices that overlap with test evaluation window
            train_mask = (eval_times < test_pred_min) | (pred_times > test_eval_max)
            
            # Embargo training indices immediately after test set
            embargo_offset = test_end + embargo_size
            embargo_mask = (indices < test_start) | (indices >= embargo_offset)

            final_train_mask = train_mask & embargo_mask
            train_idx = indices[final_train_mask]

            yield train_idx, test_idx
```
