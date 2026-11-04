"""Offline builder contracts; synthetic fixtures are not market evidence."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_profit_shadow_artifact as builder


def panel(periods=10):
    days = pd.bdate_range("2026-08-03", periods=periods)
    index = pd.DatetimeIndex([t for day in days for t in pd.date_range(
        f"{day.date()} 09:30", periods=78, freq="5min", tz=builder.NY)])
    rng = np.random.default_rng(41126)
    frames = {}
    for i, symbol in enumerate(builder.INPUT_SYMBOLS):
        price = (100 + 20 * i) * np.exp(np.cumsum(rng.normal(0, .001, len(index))))
        frames[symbol] = pd.DataFrame({"open": price, "high": price + .1,
            "low": price - .1, "close": price, "volume": rng.integers(100, 10000, len(index))}, index=index)
    return frames


def archive(tmp_path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    for symbol, frame in panel().items():
        # Poisoned future prices must be discarded before price validation/fitting.
        extra = pd.DataFrame(np.nan, columns=frame.columns,
            index=pd.DatetimeIndex([pd.Timestamp("2026-08-17 09:30", tz=builder.NY)]))
        pd.concat([frame, extra]).to_csv(folder / f"{symbol}.csv", index_label="timestamp")
    return folder


def test_build_refits_prior_real_math_and_writes_hashed_artifact_without_overwrite(tmp_path):
    source = archive(tmp_path)
    out = tmp_path / "built"
    receipt = builder.build("2026-08-17", out, archive=source)
    assert receipt["training_sessions"] == list(pd.bdate_range("2026-08-03", periods=10).strftime("%Y-%m-%d"))
    assert all(pd.Timestamp(row["last_label_end"]) < builder.session_cutoff("2026-08-17")
               for row in receipt["training_fits"])
    assert len(receipt["training_fits"]) == 6
    assert receipt["execution_enabled"] is False
    assert receipt["performance_verified"] is False
    assert receipt["artifact"]["sha256"] == hashlib.sha256((out / "shadow_model.json").read_bytes()).hexdigest()
    assert all(row["rows"] == 780 for row in receipt["input_coverage"].values())
    assert str(source) not in json.dumps(receipt)
    with pytest.raises(FileExistsError):
        builder.build("2026-08-17", out, archive=source)


def test_source_timezone_and_source_ambiguity_are_not_guessed(tmp_path):
    source = archive(tmp_path)
    path = source / "NVDA.csv"
    rows = pd.read_csv(path)
    rows["timestamp"] = pd.to_datetime(rows.timestamp, utc=True).dt.tz_localize(None).astype(str)
    rows.to_csv(path, index=False)
    with pytest.raises(ValueError, match="timezone"):
        builder.load_archive(source, builder.session_cutoff("2026-08-17"))
    (source / "NVDA.parquet").write_text("ambiguous")
    with pytest.raises(ValueError, match="Exactly one"):
        builder.load_archive(source, builder.session_cutoff("2026-08-17"))


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload
        self.content = json.dumps(payload).encode()

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    def get(self, endpoint, **kwargs):
        self.calls.append((endpoint, {**kwargs["params"]}))
        return next(self.responses)


def test_fetch_paginates_every_symbol_and_records_receipts_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "fixture-private-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "fixture-private-secret")
    bar = {"t": "2026-08-14T13:30:00Z", "o": 100., "h": 101., "l": 99., "c": 100., "v": 100}
    first, *remaining = builder.INPUT_SYMBOLS
    client = FakeClient([FakeResponse({"bars": {first: [bar]}, "next_page_token": "next"}),
                         FakeResponse({"bars": {s: [bar] for s in remaining}, "next_page_token": None})])
    frames, capture = builder.fetch_alpaca(builder.session_cutoff("2026-08-17"), tmp_path,
                                           client=client, env_file=tmp_path / "absent.env")
    assert set(frames) == set(builder.INPUT_SYMBOLS)
    assert len(client.calls) == 2
    assert client.calls[1][1]["page_token"] == "next"
    assert all(url == builder.ENDPOINT for url, _ in client.calls)
    assert all(len(f) == 1 for f in frames.values())
    assert capture["historical_receipt_verified"] is False
    assert all(pd.Timestamp(p["received_at"]).tzinfo is not None for p in capture["pages"])
    text = (tmp_path / "capture_receipt.json").read_text()
    assert "fixture-private" not in text and "APCA-API" not in text
    assert "page_token" not in capture["request"]


def test_fetch_rejects_repeated_pages_and_keeps_failure_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "fixture-private-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "fixture-private-secret")
    response = FakeResponse({"bars": {}, "next_page_token": "repeated"})
    client = FakeClient([response, response])
    with pytest.raises(ValueError, match="Repeated"):
        builder.fetch_alpaca(builder.session_cutoff("2026-08-17"), tmp_path,
                             client=client, env_file=tmp_path / "absent.env")
    assert len(json.loads((tmp_path / "capture_receipt.json").read_text())["pages"]) == 2


def test_ambiguous_input_and_future_session_do_not_create_output(tmp_path):
    out = tmp_path / "not-created"
    with pytest.raises(ValueError, match="exactly one"):
        builder.build("2026-08-17", out, archive=tmp_path, fetch=True)
    with pytest.raises(ValueError, match="future-session"):
        builder.build("2999-01-01", out, archive=tmp_path)
    assert not out.exists()


def test_next_session_needs_completed_current_day_and_uses_real_capture_clock(tmp_path, monkeypatch):
    source = tmp_path / "inputs"
    source.mkdir()
    for symbol, frame in panel(periods=11).items():
        frame.to_csv(source / f"{symbol}.csv", index_label="timestamp")
    monkeypatch.setattr(builder, "utc_now", lambda: "2026-08-17T19:55:00+00:00")
    with pytest.raises(ValueError, match="completed regular session"):
        builder.build("2026-08-18", tmp_path / "too-early", archive=source)
    assert not (tmp_path / "too-early").exists()
    monkeypatch.setattr(builder, "utc_now", lambda: "2026-08-17T20:20:00+00:00")
    receipt = builder.build("2026-08-18", tmp_path / "next-session", archive=source)
    assert receipt["training_sessions"][-1] == "2026-08-17"
    assert receipt["started_at"] == "2026-08-17T20:20:00+00:00"
    assert receipt["training_cutoff"] == "2026-08-18T00:00:00-04:00"
    for symbol, frame in panel().items():
        frame.to_csv(source / f"{symbol}.csv", index_label="timestamp")
    with pytest.raises(ValueError, match="complete common session today"):
        builder.build("2026-08-18", tmp_path / "missing-today", archive=source)
    assert not (tmp_path / "missing-today" / "shadow_model.json").exists()


def test_fetch_caps_at_delayed_completed_bars_without_requesting_future(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "fixture-private-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "fixture-private-secret")
    monkeypatch.setattr(builder, "utc_now", lambda: "2026-08-17T16:43:00+00:00")
    bar = {"t": "2026-08-17T16:20:00Z", "o": 100., "h": 101., "l": 99., "c": 100., "v": 100}
    client = FakeClient([FakeResponse({"bars": {s: [bar] for s in builder.INPUT_SYMBOLS}})])
    _, capture = builder.fetch_alpaca(builder.session_cutoff("2026-08-18"), tmp_path,
                                     client=client, env_file=tmp_path / "absent.env")
    assert capture["request"]["end"] == "2026-08-17T16:20:00+00:00"
    assert capture["complete_bars_before"] == "2026-08-17T16:25:00+00:00"
    assert capture["completed"] is True
