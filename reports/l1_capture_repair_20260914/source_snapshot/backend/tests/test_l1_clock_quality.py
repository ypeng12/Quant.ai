"""Clock anomalies must remain visible in the retained-event audit."""
import json

import pandas as pd
import pytest

from app.market_data.l1_quality import audit_l1_capture


def test_clock_skew_differences_are_not_dropped_or_clipped(tmp_path):
    path = tmp_path / "2026-09-11" / "NVDA.jsonl"
    path.parent.mkdir()
    base = pd.Timestamp("2026-09-11T13:30:01Z")
    original = []
    for i, delay in enumerate([-250, 50, None]):
        stamp = base + pd.Timedelta(seconds=i)
        row = dict(schema_version=1, source="alpaca_stock_websocket", feed="iex", symbol="NVDA",
                   event_type="quote", timestamp=stamp.isoformat(), market_depth="L1",
                   bid_price=100, ask_price=100.02, bid_size=2, ask_size=3,
                   received_at="invalid" if delay is None else (stamp+pd.Timedelta(milliseconds=delay)).isoformat())
        original.append(row)
    raw = "".join(json.dumps(row)+"\n" for row in original)
    path.write_text(raw)
    summary, detail = audit_l1_capture(tmp_path, ["NVDA"])
    row = detail.iloc[0]
    assert row.latency_ms_median == pytest.approx(-100)
    assert row.observed_delay_samples == 2
    assert row.negative_observed_delay_events == 1
    assert row.negative_observed_delay_fraction == .5
    assert summary["negative_observed_delay_events"] == 1
    assert summary["clock_alignment_verified"] is False
    assert "not verified network/socket arrival" in summary["timing_interpretation"]
    assert path.read_text() == raw
