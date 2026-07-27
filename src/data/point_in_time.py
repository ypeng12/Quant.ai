import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional


class PointInTimeUniverseFilter:
    """
    Enforces Point-in-Time Data Hygiene and Universe Selection Rules:
    1. Min Price Threshold: Price > $5.00
    2. Dollar Volume Liquidity Threshold: 20-day Average Dollar Volume (ADV20) > $50M
    3. Asset Age: Minimum 252 trading days history to avoid IPO / new ETF early distortions
    4. Unified Trading Calendar Alignment & Forward Fill (Zero Backfill)
    """

    def __init__(
        self,
        min_price: float = 5.0,
        min_adv20_usd: float = 50_000_000.0,
        min_age_days: int = 252,
    ):
        self.min_price = min_price
        self.min_adv20_usd = min_adv20_usd
        self.min_age_days = min_age_days

    def align_trading_calendar(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Align all assets to a unified trading calendar.
        Missing trading days are forward-filled (FFill) up to 5 days, NEVER backfilled.
        """
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

        # Get full date range
        all_dates = pd.date_range(df["date"].min(), df["date"].max(), freq="B")
        symbols = df["symbol"].unique()

        # Multi-index reindex to guarantee alignment
        full_idx = pd.MultiIndex.from_product([all_dates, symbols], names=["date", "symbol"])
        
        df_indexed = df.set_index(["date", "symbol"])
        df_aligned = df_indexed.reindex(full_idx).groupby("symbol").ffill(limit=5).reset_index()

        return df_aligned

    def filter_universe(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
        """
        Filter df for each trading date t to select eligible tickers.
        Returns cleaned DataFrame and a dictionary mapping `date_str -> list of eligible symbols`.
        """
        df = self.align_trading_calendar(df)
        df["dollar_volume"] = df["close"] * df["volume"]
        
        # Calculate rolling 20-day ADV in USD
        df["adv20"] = (
            df.groupby("symbol")["dollar_volume"]
            .transform(lambda s: s.rolling(20, min_periods=10).mean())
        )

        # Calculate history age per ticker
        df["trading_age"] = df.groupby("symbol")["date"].cumcount() + 1

        # Eligibility condition at timestamp t
        eligible_mask = (
            (df["close"] >= self.min_price) &
            (df["adv20"] >= self.min_adv20_usd) &
            (df["trading_age"] >= self.min_age_days)
        )

        df["is_eligible"] = eligible_mask

        # Build universe dict per date
        universe_by_date = {}
        for d, group in df[df["is_eligible"]].groupby("date"):
            date_str = d.strftime("%Y-%m-%d")
            universe_by_date[date_str] = group["symbol"].tolist()

        return df, universe_by_date

    @staticmethod
    def validate_no_lookahead(df: pd.DataFrame, feature_date_col: str = "date", label_start_col: str = "label_start_date") -> bool:
        """
        Validation assertion to prove zero lookahead leakage:
        Every feature calculated at timestamp t must strictly satisfy t < label_start_date.
        """
        if label_start_col not in df.columns:
            return True
        violating = df[df[feature_date_col] >= df[label_start_col]]
        if len(violating) > 0:
            raise ValueError(f"CRITICAL ERROR: Look-ahead bias detected in {len(violating)} rows!")
        return True
