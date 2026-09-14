"""Offline context lineage/causality tests; fixtures are not performance data."""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("record_context_cli", ROOT / "scripts/record_l1_policy_context.py")
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


def forecast(tmp_path):
    data = dict(decision_time="2026-09-01T09:40:00-04:00", horizon_seconds=300,
                target="next_open_to_horizon_close_gross_return", symbols=["AAA"],
                mu={"AAA": .0012}, covariance=[[.0002]], return_units="decimal_gross_return",
                model_trained_before="2026-09-01T09:29:00-04:00",
                last_training_label_end="2026-08-31T15:59:00-04:00")
    path = tmp_path / "forecast.json"
    path.write_text(json.dumps(data))
    return path, data


def capture(tmp_path):
    root = tmp_path / "capture"
    path = root / "2026-09-01" / "AAA.jsonl"
    path.parent.mkdir(parents=True)
    with path.open("w") as handle:
        for stamp in pd.date_range("2026-09-01T09:30:00-04:00", periods=601, freq="s"):
            event = dict(schema_version=1, event_type="quote", source="alpaca_stock_historical",
                         feed="iex", market_depth="L1", quote_size_unit="round_lots", symbol="AAA",
                         timestamp=stamp.isoformat(), bid_price=99.99, ask_price=100.01, bid_size=2, ask_size=3)
            # A future mutation at the exact exclusive cutoff must not affect the record.
            if stamp.minute == 40:
                event["bid_price"], event["ask_price"] = 999.99, 1000.01
            handle.write(json.dumps(event) + "\n")
    return root, path


def test_cli_records_real_event_prefix_and_keeps_base_with_lineage(tmp_path):
    source, base = forecast(tmp_path)
    root, event_file = capture(tmp_path)
    target = tmp_path / "record.json"
    result = CLI.record_context(source, [root], target, feed="iex", source="alpaca_stock_historical", max_quote_age="2s")
    assert result["base_mu"] == base["mu"]
    assert result["covariance"] == base["covariance"]
    assert result["candidate_mu"] is None
    assert result["l1"]["AAA"]["status"] == "available"
    assert result["l1"]["AAA"]["current_mid"] == 100.
    assert result["l1"]["AAA"]["bucket_end"] == base["decision_time"]
    assert result["input_files"][0]["path"] == str(event_file)
    assert len(result["input_files"][0]["sha256"]) == 64
    assert not result["forecast_source"]["lineage_verified"]
    assert json.loads(target.read_text()) == result
    with pytest.raises(ValueError, match="already exists"):
        CLI.record_context(source, [root], target, feed="iex", source="alpaca_stock_historical", max_quote_age="2s")


def test_cli_corrupt_l1_preserves_supplied_forecast_and_records_failure(tmp_path):
    source, base = forecast(tmp_path)
    root, path = capture(tmp_path)
    with path.open("a") as handle:
        handle.write("invalid-json\n")
    result = CLI.record_context(source, [root], tmp_path / "record.json", feed="iex",
                                source="alpaca_stock_historical", max_quote_age="2s")
    assert result["base_mu"] == base["mu"]
    assert result["l1"]["AAA"]["status"] == "unavailable"
    assert "AAA" in result["input_errors"]
    assert result["orders_submitted"] == 0


def test_cli_rejects_future_trained_baseline_before_writing_output(tmp_path):
    source, base = forecast(tmp_path)
    base["model_trained_before"] = "2026-09-01T16:00:00-04:00"
    source.write_text(json.dumps(base))
    target = tmp_path / "record.json"
    with pytest.raises(ValueError, match="not mature"):
        CLI.record_context(source, [tmp_path / "absent"], target, feed="iex",
                           source="alpaca_stock_historical", max_quote_age="2s")
    assert not target.exists()
