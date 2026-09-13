"""Local-only refresh checks: frozen spec, exclusive cutoff, honest freshness."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.quant_policy import PolicyModel, PolicySpec
from backend.app.research.causal_week_replay import regular_index
from scripts.update_policy_artifact import refresh_policy


def fixture(tmp_path: Path):
    dates = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27"]
    frames = {}
    for symbol, initial in (("A", 100.0), ("B", 200.0)):
        parts = []
        for j, day in enumerate(dates):
            opening = initial + j + np.arange(78) * (0.02 if j % 2 == 0 else -0.01)
            close = opening + 0.005
            parts.append(pd.DataFrame({
                "Open": opening, "High": close + 0.01, "Low": opening - 0.01,
                "Close": close, "Volume": np.arange(78) + 1000,
            }, index=regular_index(day)))
        frames[symbol] = pd.concat(parts)
    source = tmp_path / "source.json"
    spec = PolicySpec("frozen_candidate", feature_set="price_volume", horizon_bars=3,
                      ridge_alpha=10, risk_aversion=50, cost_bps=2)
    PolicyModel.fit(frames, train_before="2026-08-26", spec=spec).save(source)
    bars_dir = tmp_path / "bars"
    bars_dir.mkdir()
    for symbol, frame in frames.items():
        frame.to_parquet(bars_dir / f"{symbol}.parquet")
    return source, bars_dir, frames


def test_refit_preserves_frozen_spec_and_filters_cutoff_before_future_validation(tmp_path):
    source, bars_dir, frames = fixture(tmp_path)
    original_source = source.read_bytes()
    first = tmp_path / "first.json"
    metadata = refresh_policy(source, bars_dir, "2026-08-27", first)
    assert metadata["status"] == "refit_with_new_complete_sessions_for_all_symbols"
    assert metadata["latest_complete_session_by_symbol"] == {"A": "2026-08-26", "B": "2026-08-26"}
    for symbol, frame in frames.items():
        future = frame.index.strftime("%Y-%m-%d") >= "2026-08-27"
        frame.loc[future, "High"] = -100  # Invalid future OHLCV must not affect past fitting.
        frame.to_parquet(bars_dir / f"{symbol}.parquet")
    second = tmp_path / "second.json"
    changed = refresh_policy(source, bars_dir, "2026-08-27", second)
    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text())["spec"] == json.loads(source.read_text())["spec"]
    assert changed["inputs"]["A"]["rows_ignored_on_or_after_cutoff"] == 78
    assert source.read_bytes() == original_source
    assert first.with_suffix(".json.metadata.json").exists()


def test_later_cutoff_without_later_data_does_not_claim_data_refresh(tmp_path):
    source, bars_dir, frames = fixture(tmp_path)
    for symbol, frame in frames.items():
        frame.loc[frame.index.strftime("%Y-%m-%d") < "2026-08-26"].to_parquet(bars_dir / f"{symbol}.parquet")
    metadata = refresh_policy(source, bars_dir, "2026-09-01", tmp_path / "stale_refit.json")
    assert metadata["status"] == "refit_without_new_complete_sessions"
    assert metadata["trained_last_session"] == "2026-08-25"
    assert metadata["data_advanced_by_symbol"] == {"A": False, "B": False}
    assert metadata["parameter_selection_performed"] is False
    assert metadata["broker_or_live_configuration_changed"] is False


def test_refit_rejects_existing_output_source_overwrite_and_ambiguous_cutoff(tmp_path):
    source, bars_dir, _ = fixture(tmp_path)
    original_source = source.read_bytes()
    with pytest.raises(FileExistsError, match="new output path"):
        refresh_policy(source, bars_dir, "2026-08-27", source)
    existing = tmp_path / "existing.json"
    existing.write_text("user file")
    with pytest.raises(FileExistsError, match="new output path"):
        refresh_policy(source, bars_dir, "2026-08-27", existing)
    with pytest.raises(ValueError, match="explicit YYYY-MM-DD"):
        refresh_policy(source, bars_dir, "2026-8-27", tmp_path / "unused.json")
    assert source.read_bytes() == original_source
    assert existing.read_text() == "user file"
