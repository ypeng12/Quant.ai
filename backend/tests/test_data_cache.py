"""Exercise cache freshness and corrupt files without starting trading services."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import data_cache


class DataCacheTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        cache_dir = patch.object(data_cache, "CACHE_DIR", directory.name)
        cache_dir.start()
        self.addCleanup(cache_dir.stop)
        self.frame = pd.DataFrame(
            {"Close": [100.25, 101.50], "Volume": [1200, 1800]},
            index=pd.date_range("2026-09-11 09:30", periods=2, freq="5min", tz="America/New_York"),
        )
        data_cache.save_cache("NVDA", "5d", "5m", self.frame)
        key = data_cache._cache_key("NVDA", "5d", "5m")
        self.parquet_path = Path(data_cache._cache_path(key))
        self.meta_path = Path(data_cache._meta_path(key))

    def test_fresh_cache_restores_values_and_market_timestamps(self):
        cached = data_cache.get_cached("nvda", "5d", "5m")
        self.assertIsNotNone(cached)
        pd.testing.assert_frame_equal(cached, self.frame, check_freq=False)

    def test_expired_cache_is_not_read_as_fresh(self):
        # A genuinely old snapshot captured after both fixture bars completed.
        observed = self.frame.index[-1] + pd.Timedelta(minutes=5)
        self.meta_path.write_text(str(observed.timestamp()))
        with patch.object(data_cache.pd, "read_parquet") as read_parquet:
            self.assertIsNone(data_cache.get_cached("NVDA", "5d", "5m"))
            read_parquet.assert_not_called()
        pd.testing.assert_frame_equal(
            data_cache.get_cached_ignore_ttl("NVDA", "5d", "5m"), self.frame, check_freq=False
        )

    def test_corrupt_parquet_is_a_cache_miss(self):
        self.parquet_path.write_bytes(b"interrupted parquet write")
        self.assertIsNone(data_cache.get_cached("NVDA", "5d", "5m"))

    def test_corrupt_or_missing_metadata_is_a_cache_miss(self):
        self.meta_path.write_text("not a timestamp")
        self.assertIsNone(data_cache.get_cached("NVDA", "5d", "5m"))
        self.meta_path.unlink()
        self.assertIsNone(data_cache.get_cached("NVDA", "5d", "5m"))

    def test_five_minute_boundary_requires_a_new_snapshot_even_within_ttl(self):
        observed = pd.Timestamp("2026-10-02 10:04:59", tz="America/New_York")
        self.meta_path.write_text(str(observed.timestamp()))
        with patch.object(data_cache, "datetime") as clock:
            clock.now.return_value = observed + pd.Timedelta(seconds=2)
            self.assertIsNone(data_cache.get_cached("NVDA", "5d", "5m"))

    def test_same_five_minute_bucket_can_use_fresh_cache(self):
        observed = pd.Timestamp("2026-10-02 10:03:00", tz="America/New_York")
        self.meta_path.write_text(str(observed.timestamp()))
        with patch.object(data_cache, "datetime") as clock:
            clock.now.return_value = observed + pd.Timedelta(seconds=30)
            pd.testing.assert_frame_equal(
                data_cache.get_cached("NVDA", "5d", "5m"), self.frame, check_freq=False
            )

    def test_fallback_never_promotes_a_cached_partial_bar_to_completed(self):
        frame = self.frame.copy()
        frame.index = pd.date_range("2026-10-02 09:55", periods=2, freq="5min", tz="America/New_York")
        frame.to_parquet(self.parquet_path)
        self.meta_path.write_text(str(pd.Timestamp("2026-10-02 10:04:59", tz="America/New_York").timestamp()))
        cached = data_cache.get_cached_ignore_ttl("NVDA", "5d", "5m")
        pd.testing.assert_frame_equal(cached, frame.iloc[:1], check_freq=False)

    def test_five_minute_fallback_requires_a_valid_observation_time(self):
        for value in ("nan", "inf", "bad timestamp"):
            self.meta_path.write_text(value)
            self.assertIsNone(data_cache.get_cached_ignore_ttl("NVDA", "5d", "5m"))

    def test_fallback_partial_candle_cannot_enter_completed_bar_execution(self):
        from app.broker.research_execution import closed_bars

        frame = pd.DataFrame(
            {"Open": [100., 101.], "High": [102., 103.], "Low": [99., 100.],
             "Close": [101., 102.], "Volume": [1000., 500.]},
            index=pd.date_range("2026-10-02 09:55", periods=2, freq="5min", tz="America/New_York"),
        )
        frame.to_parquet(self.parquet_path)
        observed = pd.Timestamp("2026-10-02 10:04:59", tz="America/New_York")
        self.meta_path.write_text(str(observed.timestamp()))
        cached = data_cache.get_cached_ignore_ttl("NVDA", "5d", "5m")
        with self.assertRaisesRegex(ValueError, "Stale bars"):
            closed_bars(cached, observed + pd.Timedelta(seconds=2))

    def test_download_start_time_is_retained_when_cache_write_crosses_boundary(self):
        observed = pd.Timestamp("2026-10-02 10:04:59", tz="America/New_York").timestamp()
        with patch.object(data_cache, "datetime") as clock:
            clock.now.return_value = pd.Timestamp("2026-10-02 10:05:02", tz="America/New_York")
            data_cache.save_cache("NVDA", "5d", "5m", self.frame, observed_at=observed)
            self.assertEqual(float(self.meta_path.read_text()), observed)
            self.assertIsNone(data_cache.get_cached("NVDA", "5d", "5m"))


if __name__ == "__main__":
    unittest.main()
