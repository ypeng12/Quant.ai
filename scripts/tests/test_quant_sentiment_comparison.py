"""Offline pipeline tests using synthetic prices only, never broker services."""
import importlib.util
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("quant_comparison_review", ROOT / "scripts/run_quant_sentiment_comparison.py")
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


def session(day, seed):
    rng = np.random.default_rng(seed)
    # A synthetic drift makes the pipeline exercise actual fills/fees, not just
    # the all-cash branch. These rows never enter research or public artifacts.
    opens = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.0007, 78)))
    closes = opens * np.exp(rng.normal(0.0004, 0.0006, 78))
    return pd.DataFrame({"open": opens, "close": closes,
                         "high": np.maximum(opens, closes) * 1.001,
                         "low": np.minimum(opens, closes) * 0.999,
                         "volume": rng.integers(1000, 5000, 78)},
                        index=pd.date_range(f"{day} 09:30", periods=78, freq="5min", tz="America/New_York"))


@pytest.fixture(scope="module")
def histories():
    dates = comparison.calendar_dates("2026-08-10", "2026-09-15")
    return {symbol: pd.concat([session(day, offset * 1000 + i) for i, day in enumerate(dates)])
            for offset, symbol in enumerate(comparison.INPUTS)}


def test_merge_source_precedence_never_backfills_missing_new_capture_bars(tmp_path):
    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir(); new_dir.mkdir()
    for symbol in comparison.INPUTS:
        old = pd.concat([session("2026-09-11", 1), session("2026-09-14", 2)])
        new = session("2026-09-14", 3).drop(session("2026-09-14", 3).index[20])
        old.to_parquet(old_dir / f"{symbol}.parquet")
        new.to_parquet(new_dir / f"{symbol}.parquet")
    merged, evidence = comparison.merge_prices(old_dir, new_dir)
    assert all(len(frame.loc["2026-09-14"]) == 77 for frame in merged.values())
    assert evidence[comparison.INPUTS[0]]["revised_overlap_rows"] > 0
    with pytest.raises(ValueError, match="missing/incomplete"):
        comparison.complete_universe(merged, ["2026-09-14"])


def test_old_A_training_cutoff_blocks_run_before_data_access(tmp_path, monkeypatch):
    monkeypatch.setattr(comparison.PolicyModel, "load", lambda path: SimpleNamespace(trained_before="2026-09-12"))
    def forbidden(*args, **kwargs):
        raise AssertionError("Price/archive data accessed before A training cutoff check")
    monkeypatch.setattr(comparison, "merge_prices", forbidden)
    monkeypatch.setattr(comparison, "load_default_archives", forbidden)
    args = SimpleNamespace(output=str(tmp_path / "invalid"), model="unused", start="2026-09-11")
    with pytest.raises(ValueError, match="fit contains"):
        comparison.run(args)
    assert not (Path(args.output) / "registry.json").exists()


def test_registered_pipeline_no_text_B_equals_C_and_public_curve_reconciles(tmp_path, monkeypatch, histories):
    warmup, capture = tmp_path / "warmup", tmp_path / "capture"
    warmup.mkdir(); capture.mkdir()
    for symbol, frame in histories.items():
        frame.loc[:"2026-09-11"].to_parquet(warmup / f"{symbol}.parquet")
        frame.loc["2026-09-14":].to_parquet(capture / f"{symbol}.parquet")
    from app.quant_policy import PolicySpec
    old = comparison.PolicyModel.fit(histories, "2026-09-12", PolicySpec(
        name="synthetic_pipeline_A", feature_set="price_volume", horizon_bars=1,
        risk_aversion=50.0, ridge_alpha=10.0, cost_bps=2.0, gross_limit=.95, symbol_limit=.70))
    model = tmp_path / "synthetic_A.json"
    old.save(model)
    out = tmp_path / "result"
    original_fit = comparison.PriceCandidate.fit
    fitted_days = []
    def checked_fit(*args, **kwargs):
        registration = json.loads((out / "preregistration.json").read_text())
        assert registration["status"] == "registered"
        assert "results" not in registration
        assert not (out / "registry.json").exists()
        fitted_days.append(args[1])
        return original_fit(*args, **kwargs)
    monkeypatch.setattr(comparison.PriceCandidate, "fit", checked_fit)
    original_calibrate = comparison.fit_residual_calibration
    calibration_sizes = []
    def checked_calibration(examples, cutoff, **kwargs):
        calibration_sizes.append(len(examples))
        for example in examples:
            start, end = pd.Timestamp(example["label_start_at"]), pd.Timestamp(example["label_end_at"])
            assert end - start == pd.Timedelta(minutes=30)
            assert end < pd.Timestamp(cutoff)
            assert end.tz_convert("America/New_York").strftime("%H:%M") <= "15:55"
            assert start == pd.Timestamp(example["snapshot"]["decision_at"])
        return original_calibrate(examples, cutoff, **kwargs)
    monkeypatch.setattr(comparison, "fit_residual_calibration", checked_calibration)
    monkeypatch.setattr(comparison, "load_default_archives", lambda root: ([], {"mode": "synthetic_no_text_test_fixture"}))
    original_write = comparison.write
    public_destination = ROOT / "reports/financial_sentiment_strategy_comparison.json"
    def isolated_write(path, value):
        return original_write(tmp_path / "global_public.json" if Path(path) == public_destination else path, value)
    monkeypatch.setattr(comparison, "write", isolated_write)
    comparison.run(SimpleNamespace(output=str(out), model=str(model), warmup=str(warmup), capture=str(capture),
                                   start="2026-09-14", end="2026-09-15", capital=50_000.0))
    registry = json.loads((out / "registry.json").read_text())
    public = json.loads((out / "public_comparison.json").read_text())
    assert fitted_days == ["2026-09-14", "2026-09-15"]
    assert calibration_sizes[0] == 0 < calibration_sizes[1]
    assert registry["text"]["usable_decisions"] == registry["text"]["changed_decisions"] == 0
    for cost in ("2bps", "5bps"):
        assert registry["results"][cost + "_B"] == registry["results"][cost + "_C"]
        for kind in ("daily", "fills", "marks"):
            with gzip.open(out / f"cost_{cost}" / "B" / f"{kind}.csv.gz", "rt") as stream:
                left = stream.read()
            with gzip.open(out / f"cost_{cost}" / "C" / f"{kind}.csv.gz", "rt") as stream:
                right = stream.read()
            assert left == right
        assert registry["results"][cost + "_C"]["fill_count"] > 0
        assert registry["results"][cost + "_C"]["costs"] > 0
    assert public == json.loads((tmp_path / "global_public.json").read_text())
    assert public["starting_capital"] == 50_000.0
    for model_info in public["models"]:
        name = model_info["id"]
        ending = public["curves"][-1][name]
        result = registry["results"]["2bps_" + name]
        assert ending == pytest.approx(50_000.0 + model_info["net_pnl"])
        assert ending / 50_000.0 - 1 == pytest.approx(model_info["net_return"])
        assert ending == pytest.approx(result["ending_equity"])
    receipts = json.loads((out / "training.json").read_text())
    for receipt in receipts:
        assert receipt["price"]["calibration_days"][-1] < receipt["date"]
        assert receipt["price"]["base_last_training_session"] < receipt["price"]["calibration_days"][0]

