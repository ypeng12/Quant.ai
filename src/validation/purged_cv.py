import pandas as pd
import numpy as np
from typing import List, Tuple, Generator


def purge_overlap_and_embargo(
    train_dates: pd.DatetimeIndex,
    test_dates: pd.DatetimeIndex,
    label_horizon: int = 5,
    embargo_days: int = 5
) -> pd.DatetimeIndex:
    """
    Purges training dates whose forward labels overlap with the test set,
    and applies embargo after the test set to eliminate autocorrelation leakage.
    """
    if len(train_dates) == 0 or len(test_dates) == 0:
        return train_dates

    test_start = test_dates.min()
    test_end = test_dates.max()

    # Purge: remove training dates t where t + horizon >= test_start
    purge_cutoff_start = test_start - pd.Timedelta(days=label_horizon * 2)
    
    # Embargo: remove training dates falling in (test_end, test_end + embargo_days]
    embargo_end = test_end + pd.Timedelta(days=embargo_days * 2)

    clean_train_mask = (
        (train_dates < purge_cutoff_start) | (train_dates > embargo_end)
    )

    return train_dates[clean_train_mask]


class PurgedWalkForwardCV:
    """
    Purged Walk-Forward Cross Validation Generator for Financial Time Series:
    - Train Window: e.g. 3 Years (756 trading days)
    - Validation Window: e.g. 6 Months (126 trading days)
    - Test Window: e.g. 6 Months (126 trading days)
    - Step Size: 6 Months (126 trading days)
    - Embargo: 5 trading days
    """

    def __init__(
        self,
        train_days: int = 756,
        val_days: int = 126,
        test_days: int = 126,
        label_horizon: int = 5,
        embargo_days: int = 5,
    ):
        self.train_days = train_days
        self.val_days = val_days
        self.test_days = test_days
        self.label_horizon = label_horizon
        self.embargo_days = embargo_days

    def split(self, df: pd.DataFrame) -> Generator[Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], None, None]:
        """
        Yields (train_df, val_df, test_df) tuples for each walk-forward fold.
        """
        unique_dates = pd.DatetimeIndex(sorted(df["date"].unique()))
        total_dates = len(unique_dates)

        start = 0
        fold_idx = 0

        while start + self.train_days + self.val_days + self.test_days <= total_dates:
            raw_train_dates = unique_dates[start : start + self.train_days]
            val_dates = unique_dates[start + self.train_days : start + self.train_days + self.val_days]
            test_dates = unique_dates[
                start + self.train_days + self.val_days : start + self.train_days + self.val_days + self.test_days
            ]

            # Purge & Embargo train dates relative to test dates
            clean_train_dates = purge_overlap_and_embargo(
                raw_train_dates, test_dates, label_horizon=self.label_horizon, embargo_days=self.embargo_days
            )

            train_df = df[df["date"].isin(clean_train_dates)].copy()
            val_df = df[df["date"].isin(val_dates)].copy()
            test_df = df[df["date"].isin(test_dates)].copy()

            fold_idx += 1
            yield train_df, val_df, test_df

            start += self.test_days
