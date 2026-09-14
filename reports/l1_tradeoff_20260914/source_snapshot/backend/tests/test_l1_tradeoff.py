"""Synthetic contract tests; fixture outputs are never evidence of alpha."""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.alpha.paper_l1_alpha import quote_states
from app.research.l1_tradeoff import (CANDIDATES, chronological_splits, decision_dataset,
                                      evaluate_dataset, prediction_metrics, run_l1_tradeoff)


def quotes(n=1800, freq="s"):
    index = pd.date_range("2026-09-11 09:30", periods=n, freq=freq, tz="America/New_York")
    t = np.arange(n)
    mid = 100 + np.sin(t/13)*.03 + t*.00001
    size = np.resize([2., 4., 7., 8., 3.], n)
    return pd.DataFrame(dict(schema_version=1, event_type="quote", source="alpaca_stock_historical",
                             symbol="AAA", feed="iex", market_depth="L1", quote_size_unit="round_lots",
                             bid_price=mid-.005, ask_price=mid+.005, bid_size=size, ask_size=10-size), index=index)


def test_grid_labels_use_decision_time_not_last_quote_time():
    raw = quotes(20)
    raw.index = raw.index+pd.Timedelta("400ms")
    q = quote_states(raw)
    dataset = decision_dataset(q, horizons=["1s"], decision_interval="5s")["1s"]
    t = pd.Timestamp("2026-09-11 09:30:05", tz="America/New_York")
    assert dataset.loc[t, "quote_time"] == t-pd.Timedelta("600ms")
    assert dataset.loc[t, "label_end"] == t+pd.Timedelta("1400ms")
    assert dataset.loc[t, "target"] == pytest.approx(q.mid.iloc[6]/q.mid.iloc[4]-1)
    assert dataset.index[0].strftime("%H:%M:%S") == "09:30:00"
    assert dataset.index.to_series().diff().dropna().eq(pd.Timedelta("5s")).all()
    assert (dataset.label_end.dropna() > dataset.index[dataset.label_end.notna()]).all()


def test_grid_staleness_and_invalid_quote_never_resurrect_old_book():
    raw = quotes(10)
    raw.loc[raw.index[4:7], "ask_price"] = raw.loc[raw.index[4:7], "bid_price"]
    q = quote_states(raw)
    invalid = raw.index[raw.ask_price.eq(raw.bid_price)]
    dataset = decision_dataset(q, horizons=["1s"], max_quote_age="10s", invalid_times=invalid)["1s"]
    assert not dataset.decision_valid.iloc[1]
    assert np.isnan(dataset.target.iloc[1])
    stale = decision_dataset(q, horizons=["1s"], max_quote_age="100ms")["1s"]
    assert not stale.decision_valid.iloc[2]


def test_newly_arrived_stale_exchange_quote_is_not_fresh():
    raw = quotes(20)
    raw["source"] = "alpaca_stock_websocket"
    raw["received_at"] = (raw.index+pd.Timedelta("10s")).astype(str)
    q = quote_states(raw)
    dataset = decision_dataset(q, horizons=["1s"], max_quote_age="1s")["1s"]
    t = pd.Timestamp("2026-09-11 09:30:15", tz="America/New_York")
    assert dataset.loc[t, "quote_age_seconds"] == 0
    assert dataset.loc[t, "quote_exchange_age_seconds"] == 10
    assert not dataset.loc[t, "decision_valid"]
    assert pd.isna(dataset.loc[t, "target"])


@pytest.mark.parametrize("boundary", ["connection_id", "capture_session_id"])
def test_no_labels_or_past_mid_cross_capture_boundary(boundary):
    raw = quotes(30)
    raw[boundary] = ["a"]*8+["b"]*22
    dataset = decision_dataset(quote_states(raw), horizons=["5s"])["5s"]
    assert np.isnan(dataset.target.iloc[1])
    assert np.isnan(dataset.past_mid_return.iloc[2])
    assert pd.notna(dataset.target.iloc[2])


def test_rolling_ofi_is_all_updates_and_not_just_final_event():
    q = quote_states(quotes(30))
    dataset = decision_dataset(q, horizons=["1s"], ofi_window="5s")["1s"]
    expected = q.ofi.iloc[1:6].sum()/(q.depth.iloc[1:6].mean()/2)
    assert dataset.ofi_depth.iloc[1] == pytest.approx(expected)


def test_training_mature_labels_and_future_perturbation_invariance():
    raw = quotes()
    cutoff = pd.Timestamp("2026-09-11 09:45", tz="America/New_York")
    data = decision_dataset(quote_states(raw), horizons=["30s"])["30s"]
    models, predictions, splits = evaluate_dataset(data, intraday_cut="09:45")
    assert len(models) == len(CANDIDATES)
    assert pd.Timestamp(splits[0]["last_train_label_end"]) < cutoff
    assert splits[0]["kind"] == "intraday_diagnostic"
    assert predictions.index.min() >= cutoff
    assert len({m["test_rows"] for m in models}) == 1
    raw.loc[raw.index >= cutoff, ["bid_price", "ask_price"]] *= 2
    altered = decision_dataset(quote_states(raw), horizons=["30s"])["30s"]
    after, _, after_splits = evaluate_dataset(altered, intraday_cut="09:45")
    assert after_splits[0]["train_data_sha256"] == splits[0]["train_data_sha256"]
    assert after_splits[0]["test_data_sha256"] != splits[0]["test_data_sha256"]
    for before, changed in zip(models, after):
        assert before["artifact"] == changed["artifact"]
        assert before["selected_for_live"] is None


def test_multiday_uses_only_prior_dates_and_rejects_overnight_labels():
    raw = quotes(60)
    tomorrow = raw.copy()
    tomorrow.index += pd.Timedelta("3D")  # Monday after Friday
    dataset = decision_dataset(quote_states(pd.concat([raw, tomorrow])), horizons=["5s"])["5s"]
    splits = chronological_splits(dataset)
    assert len(splits) == 1
    assert splits[0]["kind"] == "walk_forward_sessions"
    assert set(dataset.loc[splits[0]["train"]].session) == {"2026-09-11"}
    assert set(dataset.loc[splits[0]["test"]].session) == {"2026-09-14"}
    midnight = pd.Timestamp("2026-09-14 09:30", tz="America/New_York")
    assert np.isnan(dataset.loc[midnight, "past_mid_return"])


def test_zero_direction_denominators_and_constant_correlation():
    metrics = prediction_metrics([0., .01, -.01], [0., 0., 0.])
    assert metrics["target_zero_fraction"] == pytest.approx(1/3)
    assert metrics["directional_rows"] == 0
    assert metrics["direction_accuracy_nonzero"] is None
    assert metrics["forecast_direction_coverage"] == 0
    assert metrics["ic"] is None
    assert metrics["rank_ic"] is None
    assert metrics["sign_match_including_zeros"] == pytest.approx(1/3)


def test_file_report_hashes_predictions_and_no_live_selection(tmp_path):
    raw = quotes()
    path = tmp_path/"input/2026-09-11/AAA.jsonl"
    path.parent.mkdir(parents=True)
    with path.open("w") as handle:
        for timestamp, row in raw.iterrows():
            handle.write(json.dumps(dict(row.to_dict(), timestamp=timestamp.isoformat()))+"\n")
    output = tmp_path/"report"
    registry = run_l1_tradeoff([tmp_path/"input"], ["AAA"], output, horizons=["5s"], intraday_cut="09:45")
    assert registry["status"] == "complete"
    assert registry["evaluated_candidates"] == 5
    assert registry["evaluation_kinds"] == ["intraday_diagnostic"]
    assert registry["selected_for_live"] is None
    assert registry["performance_verified"] is False
    assert len(registry["source_files"][0]["sha256"]) == 64
    assert len(registry["dependency_sha256"]["alpha/paper_l1_alpha.py"]) == 64
    forecasts = pd.read_csv(next(output.glob("predictions_*.csv")))
    assert {"decision_time", "model_trained_before", "baseline_prediction", "label_end", "source", "clock", "horizon", "target"}.issubset(forecasts)
    assert forecasts.baseline_prediction.notna().all()
    assert registry == json.loads((output/"registry.json").read_text())
    assert all(m["cost_scenarios"][1]["round_trip_hurdle_bps"] == 10 for m in registry["models"])


def test_missing_requested_session_is_partial(tmp_path):
    raw = quotes()
    path = tmp_path/"input/2026-09-11/AAA.jsonl"
    path.parent.mkdir(parents=True)
    with path.open("w") as handle:
        for timestamp, row in raw.iterrows():
            handle.write(json.dumps(dict(row.to_dict(), timestamp=timestamp.isoformat()))+"\n")
    registry = run_l1_tradeoff([tmp_path/"input"], ["AAA"], tmp_path/"report", horizons=["5s"],
                              intraday_cut="09:45", session_dates=["2026-09-11", "2026-09-14"])
    assert registry["status"] == "partial"
    assert registry["missing_requested_sessions"][0]["sessions"] == ["2026-09-14"]


def test_no_data_and_proxy_fail_without_fake_metrics(tmp_path):
    registry = run_l1_tradeoff([tmp_path/"absent"], ["AAA"], tmp_path/"report")
    assert registry["status"] == "unavailable"
    assert registry["evaluated_candidates"] == 0
    assert registry["models"] == []
    raw = quotes()
    raw["source"] = "ohlcv_proxy"
    with pytest.raises(ValueError, match="proxy"):
        quote_states(raw)
