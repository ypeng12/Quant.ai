"""Synthetic unit fixtures verify causality/contracts, never trading results."""
import json
from pathlib import Path
import shutil
import sys
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.alpha.l1_ridge import L1Ridge
from app.alpha.l1_state_models import QueueImbalanceModel, TransitionMicroprice
from app.alpha.paper_l1_alpha import (enhanced_l1_features, forward_mid_labels,
                                     next_move_labels, observed_events, quote_states)
from app.research.real_l1_research import run_real_l1_research


def quotes(n=800):
    index = pd.date_range("2026-09-01 09:30", periods=n, freq="s", tz="America/New_York")
    mid = np.resize([100., 100., 100.01, 100.01, 100., 100., 100.01, 100.01], n)
    size = np.resize([8, 8, 2, 2, 6, 6, 4, 4], n)
    return pd.DataFrame(dict(schema_version=1, event_type="quote", source="alpaca_stock_historical",
                             symbol="AAA", feed="iex", market_depth="L1", quote_size_unit="round_lots",
                             bid_price=mid-.005, ask_price=mid+.005, bid_size=size, ask_size=10-size), index=index)


def save_events(root, frame, date="2026-09-01"):
    path = root / date / "AAA.jsonl"
    path.parent.mkdir(parents=True)
    with path.open("w") as handle:
        for timestamp, row in frame.iterrows():
            handle.write(json.dumps(dict(row.to_dict(), timestamp=timestamp.isoformat())) + "\n")


def test_future_labels_hand_calculation_and_no_gap_or_tie_lookahead():
    frame = quotes(8)
    labels = next_move_labels(quote_states(frame))
    assert labels.target.tolist()[:6] == [1, 1, 0, 0, 1, 1]
    assert labels.label_end.iloc[0] == frame.index[2]
    future = forward_mid_labels(quote_states(frame), "2s", "0s")
    assert future.target.iloc[0] == pytest.approx(.01/100)
    frame.index = frame.index[:4].append(frame.index[4:]+pd.Timedelta("2h"))
    assert next_move_labels(quote_states(frame)).target.iloc[2:4].isna().all()
    frame = quotes(8)
    frame.index = pd.DatetimeIndex([frame.index[2]]*3+list(frame.index[3:]))
    assert next_move_labels(quote_states(frame)).target.iloc[:2].isna().all()


def test_arrival_clock_requires_received_at_and_keeps_independent_channels():
    frame = quotes(8)
    frame["source"] = "alpaca_stock_websocket"
    with pytest.raises(ValueError, match="received_at"):
        observed_events(frame)
    frame["received_at"] = (frame.index+pd.Timedelta("2s")).astype(str)
    assert len(observed_events(frame, as_of=frame.index[4])) == 2
    frame.iloc[0, frame.columns.get_loc("received_at")] = (frame.index[7]+pd.Timedelta("2s")).isoformat()
    assert observed_events(frame).attrs["late_events_excluded"] == 1
    frame = quotes(2)
    frame["source"] = "alpaca_stock_websocket"
    frame["received_at"] = ["2026-09-01T13:30:01Z", "2026-09-01T13:30:04Z"]
    trade = frame.iloc[[0]].copy()
    trade.index = pd.DatetimeIndex([frame.index[1]+pd.Timedelta("1s")])
    trade["event_type"] = "trade"
    trade["received_at"] = "2026-09-01T13:30:03Z"
    observed = observed_events(pd.concat([frame, trade]))
    assert observed.attrs["late_events_excluded"] == 0
    assert len(observed) == 3


def test_enhanced_ofi_uses_real_depth_and_respects_completed_bucket():
    raw = quotes(20)
    q = quote_states(raw)
    features = enhanced_l1_features(raw, "10s", as_of=raw.index[15])
    assert len(features) == 1
    assert features.l1_ofi_raw.iloc[0] == pytest.approx(q.ofi.iloc[:10].sum())
    assert features.l1_ofi_depth.iloc[0] == pytest.approx(q.ofi.iloc[:10].sum()/5)
    assert np.isnan(features.l1_signed_trade_imbalance.iloc[0])
    raw["source"] = "ohlcv_proxy"
    with pytest.raises(ValueError, match="proxy"):
        quote_states(raw)


@pytest.mark.parametrize("model_type", [QueueImbalanceModel, TransitionMicroprice, L1Ridge])
def test_model_serialization_maturity_training_mask_and_future_invariance(tmp_path, model_type):
    raw = quotes()
    before = raw.index[400]
    model = model_type().fit(raw, before=before)
    assert pd.Timestamp(model.artifact["last_label_end"]) < before
    assert model.artifact["performance_verified"] is False
    assert model.artifact["deployment"] == "research_only"
    assert model.artifact["target_feed"] == "iex"
    path = tmp_path/"model.json"
    model.save(path)
    loaded = model_type.load(path)
    predicted = model.predict(raw)
    if isinstance(predicted, pd.DataFrame):
        pd.testing.assert_frame_equal(predicted, loaded.predict(raw))
        assert predicted.transition_microprice.iloc[:400].isna().all()
        assert predicted.transition_microprice.iloc[400:].notna().any()
    else:
        pd.testing.assert_series_equal(predicted, loaded.predict(raw))
        assert predicted.iloc[:400].isna().all()
        assert predicted.iloc[400:].notna().all()
    changed = raw.copy()
    changed.loc[changed.index >= before, ["bid_price", "ask_price"]] *= 3
    assert model_type().fit(changed, before=before).artifact == model.artifact
    changed["feed"] = "sip"
    with pytest.raises(ValueError, match="contract"):
        loaded.predict(changed)


def test_transition_equations_and_unidentified_state_rejection():
    raw = quotes()
    artifact = TransitionMicroprice().fit(raw, before=raw.index[400]).artifact
    Q, R = np.array(artifact["Q"]), np.array(artifact["R"])
    np.testing.assert_allclose((np.eye(len(Q))-Q) @ artifact["first_move_correction"], artifact["immediate_reward"], atol=1e-12)
    np.testing.assert_allclose((np.eye(len(Q))-Q) @ artifact["B"], R, atol=1e-12)
    np.testing.assert_allclose((Q+R).sum(axis=1), 1)
    raw[["bid_price", "ask_price"]] = [99.995, 100.005]
    with pytest.raises(ValueError, match="Non-absorbing"):
        TransitionMicroprice().fit(raw, before=raw.index[-1])


def test_missing_capture_writes_honest_unavailable_registry(tmp_path):
    output = tmp_path/"research"
    result = run_real_l1_research([tmp_path/"absent"], ["TSLA"], output)
    assert result["status"] == "unavailable"
    assert result["trained_models"] == 0
    assert result["unavailable_models"] == 7
    assert result["source_files"] == []
    assert result["performance_verified"] is False
    assert result["selected_for_live"] is None
    assert json.loads((output/"registry.json").read_text()) == result


def test_split_quote_trade_roots_record_source_hashes(tmp_path):
    raw = quotes()
    save_events(tmp_path/"quotes", raw)
    trades = raw.iloc[::20].copy()
    trades["event_type"], trades["market_depth"] = "trade", "trade_print"
    trades["price"], trades["size"] = trades.ask_price, 100
    save_events(tmp_path/"trades", trades)
    result = run_real_l1_research([tmp_path/"quotes", tmp_path/"trades"], ["AAA"], tmp_path/"report")
    assert result["status"] == "complete"
    assert result["trained_models"] == 7
    assert len(result["datasets"]) == 1
    assert result["datasets"][0]["trades"] == len(trades)
    assert result["datasets"][0]["clock"] == "historical_exchange_latency_unverified"
    assert result["datasets"][0]["sessions"] == ["2026-09-01"]
    assert len(result["source_files"]) == 2
    assert all(len(row["sha256"]) == 64 for row in result["source_files"])
    assert all(item["status"] == "trained_unvalidated" for item in result["models"])
    assert "accuracy" not in json.dumps(result)


def test_corrupt_manifest_never_becomes_successful_training(tmp_path):
    root = tmp_path/"input"
    save_events(root, quotes())
    (root/"manifest.json").write_text(json.dumps(dict(status="complete", normalized_files=[
        dict(path="2026-09-01/AAA.jsonl", sha256="incorrect")
    ])))
    result = run_real_l1_research([root], ["AAA"], tmp_path/"report")
    assert result["status"] == "invalid"
    assert result["trained_models"] == 0
    assert "integrity" in result["input_errors"][0]["reason"]


def test_explicit_session_window_does_not_load_other_sessions(tmp_path):
    root = tmp_path/"input"
    save_events(root, quotes())
    later = root/"2026-09-02/AAA.jsonl"
    later.parent.mkdir()
    later.write_text("unread corrupt file outside requested window\n")
    result = run_real_l1_research([root], ["AAA"], tmp_path/"report", session_dates=["2026-09-01"])
    assert result["trained_models"] == 7
    assert result["requested_sessions"] == ["2026-09-01"]
    assert len(result["source_files"]) == 1


def test_feeds_are_separate_contracts(tmp_path):
    raw = quotes()
    save_events(tmp_path/"iex", raw)
    raw["feed"] = "sip"
    save_events(tmp_path/"sip", raw)
    result = run_real_l1_research([tmp_path/"iex", tmp_path/"sip"], ["AAA"], tmp_path/"report")
    assert result["trained_models"] == 14
    assert {dataset["feed"] for dataset in result["datasets"]} == {"iex", "sip"}
    assert len({model["path"] for model in result["models"]}) == 14


def test_copied_files_cannot_double_count(tmp_path):
    save_events(tmp_path/"original", quotes())
    shutil.copytree(tmp_path/"original", tmp_path/"copy")
    result = run_real_l1_research([tmp_path/"original", tmp_path/"copy"], ["AAA"], tmp_path/"report")
    assert result["status"] == "invalid"
    assert result["trained_models"] == 0
    assert "double-count" in result["input_errors"][0]["reason"]


@pytest.mark.parametrize("boundary", ["capture_session_id", "connection_id"])
def test_ofi_and_labels_never_cross_recorded_connection_boundaries(boundary):
    raw = quotes(8)
    raw[boundary] = ["first"]*4+["second"]*4
    q = quote_states(raw)
    assert q.ofi.iloc[4] == 0
    assert q.segment.iloc[3] != q.segment.iloc[4]
    assert next_move_labels(q).target.iloc[2:4].isna().all()
    assert forward_mid_labels(q, "2s").target.iloc[2:4].isna().all()
    features = enhanced_l1_features(raw, "10s")
    assert features.l1_ofi_normalized.iloc[0] == pytest.approx(q.ofi.sum()/q.depth.median())


def test_reconnected_socket_can_start_with_an_older_exchange_timestamp():
    raw = quotes(2)
    raw["source"] = "alpaca_stock_websocket"
    raw["connection_id"] = ["new", "old"]
    raw["received_at"] = ["2026-09-01T13:30:03Z", "2026-09-01T13:30:02Z"]
    observed = observed_events(raw)
    assert len(observed) == 2
    assert observed.attrs["late_events_excluded"] == 0


def test_signed_trades_only_match_quotes_from_same_connection():
    raw = quotes(4)
    raw["connection_id"] = ["first", "second", "second", "second"]
    raw["event_type"] = ["quote", "trade", "quote", "trade"]
    raw["price"] = [np.nan, 99., np.nan, 101.]
    raw["size"] = [np.nan, 10000., np.nan, 1.]
    features = enhanced_l1_features(raw, "10s")
    assert features.l1_signed_trade_imbalance.iloc[0] == 1


def test_wide_spread_bins_are_fitted_on_training_only_and_frozen():
    raw = quotes()
    mids = (raw.bid_price+raw.ask_price)/2
    spread = np.resize([1., 2., 4., 8.], len(raw))
    raw["bid_price"], raw["ask_price"] = mids-spread/2, mids+spread/2
    before = raw.index[400]
    with pytest.raises(ValueError, match="No observed microprice state"):
        TransitionMicroprice().fit(raw, before=before, spread_ticks=(1, 2, 3, 4, 5))
    model = TransitionMicroprice().fit(raw, before=before)
    assert model.artifact["spread_state_kind"] == "training_quantile_bins"
    assert model.artifact["spread_training_range_ticks"] == [100., 800.]
    changed = raw.copy()
    changed.loc[changed.index >= before, "bid_price"] = mids[changed.index >= before]-50
    changed.loc[changed.index >= before, "ask_price"] = mids[changed.index >= before]+50
    assert TransitionMicroprice().fit(changed, before=before).artifact == model.artifact
    assert model.predict(changed).transition_microprice.iloc[400:].isna().all()


def test_future_late_events_do_not_change_cutoff_statistics():
    raw = quotes(8)
    raw["source"] = "alpaca_stock_websocket"
    raw["received_at"] = (raw.index+pd.Timedelta("1s")).astype(str)
    raw.iloc[0, raw.columns.get_loc("received_at")] = (raw.index[-1]+pd.Timedelta("1s")).isoformat()
    assert observed_events(raw, as_of=raw.index[5]).attrs["late_events_excluded"] == 0
    assert observed_events(raw).attrs["late_events_excluded"] == 1


def test_regular_session_default_excludes_premarket_and_close_boundary(tmp_path):
    raw = quotes()
    before_open = raw.iloc[[0]].copy()
    before_open.index = pd.DatetimeIndex(["2026-09-01 09:29:59"], tz="America/New_York")
    at_close = raw.iloc[[0]].copy()
    at_close.index = pd.DatetimeIndex(["2026-09-01 16:00:00"], tz="America/New_York")
    save_events(tmp_path/"input", pd.concat([before_open, raw, at_close]))
    regular = run_real_l1_research([tmp_path/"input"], ["AAA"], tmp_path/"regular")
    assert regular["datasets"][0]["quotes"] == len(raw)
    assert regular["datasets"][0]["out_of_session_events_excluded"] == 2
    full = run_real_l1_research([tmp_path/"input"], ["AAA"], tmp_path/"full", regular_session=False)
    assert full["datasets"][0]["quotes"] == len(raw)+2
    assert full["datasets"][0]["out_of_session_events_excluded"] == 0


def test_exchange_calendar_excludes_quotes_after_early_close(tmp_path):
    raw = quotes()
    raw.index = pd.date_range("2026-11-27 09:30", periods=len(raw), freq="s", tz="America/New_York")
    at_close = raw.iloc[[0]].copy()
    at_close.index = pd.DatetimeIndex(["2026-11-27 13:00:00"], tz="America/New_York")
    after_close = raw.iloc[[0]].copy()
    after_close.index = pd.DatetimeIndex(["2026-11-27 15:00:00"], tz="America/New_York")
    save_events(tmp_path/"input", pd.concat([raw, at_close, after_close]), date="2026-11-27")
    result = run_real_l1_research([tmp_path/"input"], ["AAA"], tmp_path/"report")
    assert result["datasets"][0]["quotes"] == len(raw)
    assert result["datasets"][0]["out_of_session_events_excluded"] == 2
    assert "XNYS" in result["session_filter"]
