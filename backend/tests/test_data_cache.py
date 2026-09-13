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
        self.meta_path.write_text("0")
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


if __name__ == "__main__":
    unittest.main()
