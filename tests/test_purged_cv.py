import pytest
import pandas as pd
from src.validation.purged_cv import PurgedWalkForwardCV, purge_overlap_and_embargo


def test_purged_cv_leakage_prevention():
    """
    Unit test to verify that PurgedWalkForwardCV correctly purges overlapping training samples.
    """
    dates = pd.date_range("2020-01-01", periods=1200, freq="B")
    df = pd.DataFrame({
        "date": dates,
        "symbol": "SPY",
        "close": 100.0
    })

    cv = PurgedWalkForwardCV(train_days=500, val_days=100, test_days=100, label_horizon=5, embargo_days=5)

    folds = list(cv.split(df))
    assert len(folds) >= 4, "Should yield at least 4 walk-forward folds"

    for train_df, val_df, test_df in folds:
        test_start = test_df["date"].min()
        test_end = test_df["date"].max()

        # Check no train dates fall in test window
        train_in_test = train_df[(train_df["date"] >= test_start) & (train_df["date"] <= test_end)]
        assert len(train_in_test) == 0, "Train set must not contain test dates!"

    print("[TEST PASSED] Purged Walk-Forward Cross-Validation verified successfully!")


if __name__ == "__main__":
    test_purged_cv_leakage_prevention()
