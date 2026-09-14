import asyncio
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.market_data.alpaca_l1_capture import AlpacaL1Capture
from app.market_data.l1_quality import audit_l1_capture


def test_l1_quality_reports_coverage_spread_and_live_latency(tmp_path):
    collector = AlpacaL1Capture(["PLTR"], tmp_path)
    quote = dict(symbol="PLTR", timestamp=pd.Timestamp("2026-09-11T13:30:01Z"),
                 bid_price=100.00, bid_size=10, ask_price=100.02, ask_size=20)
    trade = dict(symbol="PLTR", timestamp=pd.Timestamp("2026-09-11T13:30:02Z"),
                 price=100.02, size=5, exchange="V", id=1, conditions=["@"])
    asyncio.run(collector.on_quote(quote))
    asyncio.run(collector.on_trade(trade))

    summary, detail = audit_l1_capture(tmp_path, ["PLTR", "NVDA"])

    assert summary["events"] == 2
    assert summary["missing_symbols"] == ["NVDA"]
    assert detail.iloc[0].quotes == 1 and detail.iloc[0].trades == 1
    assert detail.iloc[0].spread_bps_median > 0
    assert detail.iloc[0].latency_ms_median >= 0


def _write_events(root, session, symbol, stamps, event_type="quote"):
    import json
    path = root / session / f"{symbol}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for number, stamp in enumerate(stamps):
            event = dict(schema_version=1, source="alpaca_stock_historical", feed="iex", symbol=symbol,
                         event_type=event_type, timestamp=pd.Timestamp(stamp).isoformat())
            if event_type == "quote":
                event.update(market_depth="L1", bid_price=100, ask_price=100.02, bid_size=10, ask_size=20)
            else:
                event.update(market_depth="trade_print", price=100.02, size=5, trade_id=number)
            handle.write(json.dumps(event) + "\n")
    return path


def test_empty_capture_is_unavailable_with_csv_headers(tmp_path):
    summary, detail = audit_l1_capture(tmp_path, ["PLTR"])
    assert summary["status"] == "unavailable"
    assert summary["missing_symbols"] == summary["missing_quote_symbols"] == summary["missing_trade_symbols"] == ["PLTR"]
    assert summary["common_full_minute_coverage_session_count"] == 0
    assert summary["performance_verified"] is False
    assert {"session", "quote_minute_coverage", "latency_ms_p95"} <= set(detail.columns)


def test_early_close_uses_exchange_calendar_and_counts_complete_minutes(tmp_path):
    # Friday after Thanksgiving closes at 13:00 NY (18:00 UTC), not 16:00.
    stamps = pd.date_range("2026-11-27T14:30:00Z", periods=210, freq="min")
    _write_events(tmp_path, "2026-11-27", "PLTR", stamps)
    _write_events(tmp_path, "2026-11-27", "PLTR", stamps, "trade")
    summary, detail = audit_l1_capture(tmp_path, ["PLTR"])
    row = detail.iloc[0]
    assert row.expected_session_minutes == 210
    assert row.session_close == "2026-11-27T13:00:00-05:00"
    assert row.quote_minute_coverage == row.trade_minute_coverage == 1
    assert summary["common_full_minute_coverage_sessions"] == ["2026-11-27"]
    assert summary["status"] == "complete"
    assert row.latency_ms_median is None  # downloaded_at is not websocket latency


def test_partial_sampling_window_is_not_a_complete_exchange_session(tmp_path):
    stamps = pd.date_range("2026-09-11T13:30:00Z", periods=10, freq="min")
    _write_events(tmp_path, "2026-09-11", "PLTR", stamps)
    summary, detail = audit_l1_capture(tmp_path, ["PLTR"], start="2026-09-11T13:30:00Z",
                                     end="2026-09-11T13:40:00Z", expected_event_types=("quote",))
    row = detail.iloc[0]
    assert row.sampling_window_minutes == 10
    assert row.quote_window_minute_coverage == 1
    assert row.quote_minute_coverage == 10 / 390
    assert not row.full_quote_minute_coverage
    assert summary["common_full_minute_coverage_session_count"] == 0
    assert summary["status"] == "partial"


def test_quotes_only_manifest_does_not_require_trades_and_verifies_hash(tmp_path):
    import hashlib
    import json
    stamps = pd.date_range("2026-11-27T14:30:00Z", periods=210, freq="min")
    path = _write_events(tmp_path, "2026-11-27", "PLTR", stamps)
    manifest = dict(status="complete", kind="quotes", start="2026-11-27T14:30:00Z", end="2026-11-27T18:00:00Z",
                    normalized_files=[dict(path=str(path.relative_to(tmp_path)), sha256=hashlib.sha256(path.read_bytes()).hexdigest())])
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    summary, detail = audit_l1_capture(tmp_path, ["PLTR"])
    assert summary["expected_event_types"] == ["quote"]
    assert summary["missing_trade_symbols"] == ["PLTR"]
    assert summary["status"] == "complete"
    assert detail.iloc[0].full_quote_minute_coverage
    assert not detail.iloc[0].full_trade_minute_coverage

    path.write_text(path.read_text() + "\n")
    import pytest
    with pytest.raises(ValueError, match="integrity"):
        audit_l1_capture(tmp_path, ["PLTR"])


def test_calendar_keeps_missing_sessions_and_excludes_holiday_events(tmp_path):
    # Monday 7 September 2026 is Labor Day. Its events cannot count as a session.
    _write_events(tmp_path, "2026-09-04", "PLTR", ["2026-09-04T13:30:00Z"])
    _write_events(tmp_path, "2026-09-07", "PLTR", ["2026-09-07T13:30:00Z"])
    summary, detail = audit_l1_capture(tmp_path, ["PLTR"], start="2026-09-04T00:00:00-04:00", end="2026-09-09T00:00:00-04:00")
    assert summary["expected_sessions"] == ["2026-09-04", "2026-09-08"]
    assert summary["sessions"] == ["2026-09-04"]
    assert summary["outside_regular_session_events"] == 1
    assert detail.loc[detail.session.eq("2026-09-08"), "events"].item() == 0


def test_empty_completed_historical_download_is_unavailable(tmp_path):
    import json
    (tmp_path / "manifest.json").write_text(json.dumps(dict(status="complete", kind="quotes", normalized_files=[],
        start="2026-09-11T13:30:00Z", end="2026-09-11T20:00:00Z")))
    summary, detail = audit_l1_capture(tmp_path, ["PLTR"])
    assert summary["status"] == "unavailable"
    assert summary["expected_session_count"] == 1
    assert detail.iloc[0].events == 0


def test_close_boundary_excluded_and_duplicate_measurement_preserved(tmp_path):
    _write_events(tmp_path, "2026-09-11", "PLTR", ["2026-09-11T19:59:59Z"] * 2 + ["2026-09-11T20:00:00Z"])
    summary, detail = audit_l1_capture(tmp_path, ["PLTR"])
    assert summary["events"] == 2
    assert summary["duplicate_events"] == 1
    assert summary["outside_regular_session_events"] == 1
    assert detail.iloc[0].quote_minutes == 1


def test_naive_timestamp_and_wrong_date_directory_rejected(tmp_path):
    import pytest
    _write_events(tmp_path, "2026-09-11", "PLTR", ["2026-09-11T13:30:00"])
    with pytest.raises(ValueError, match="timezone-naive"):
        audit_l1_capture(tmp_path, ["PLTR"])
    (tmp_path / "2026-09-11" / "PLTR.jsonl").unlink()
    _write_events(tmp_path, "2026-09-11", "PLTR", ["2026-09-10T13:30:00Z"])
    with pytest.raises(ValueError, match="session directory"):
        audit_l1_capture(tmp_path, ["PLTR"])
