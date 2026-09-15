"""Saved chart data must preserve fills, partial exposure and portfolio accounting."""
import hashlib
import json
from datetime import datetime, timedelta

import pytest

from app.dashboard.price_replay import BUNDLE_ROOT, price_replay


def test_all_portable_replays_reconcile_without_double_charging_friction():
    manifest = json.loads((BUNDLE_ROOT / "manifest.json").read_text())
    assert len(manifest["files"]) == 24
    for day in manifest["available_dates"]:
        for variant in manifest["variants"]:
            for ticker in manifest["tickers"]:
                payload = price_replay(ticker, day, variant)
                assert payload["success"]
                assert payload["is_simulated"] and not payload["actual_fees_verified"]
                assert payload["capital_scope"] == "four_stock_portfolio"
                position = 0
                for fill in payload["fills"]:
                    assert fill["shares_before"] == position
                    assert abs(fill["quantity"]) == fill["shares"]
                    assert fill["action"] == (
                        "B" if fill["quantity"] > 0 and position >= 0 else
                        "C" if fill["quantity"] > 0 else "S" if position > 0 else "X")
                    position += fill["quantity"]
                    assert position == fill["shares_after"]
                for bar, mark in zip(payload["bars"], payload["marks"]):
                    assert datetime.fromisoformat(bar["time"]) - datetime.fromisoformat(bar["bar_open"]) == timedelta(minutes=5)
                    assert bar["time"] == mark["time"]
                    seen = [fill for fill in payload["fills"] if fill["time"] < mark["time"]]
                    shares = sum(fill["quantity"] for fill in seen)
                    cash = -sum(fill["quantity"] * fill["price"] + fill["commission_cost"] for fill in seen)
                    assert mark["shares"] == shares
                    # Fill prices already include assumed slippage. Subtracting
                    # assumed_cost here a second time would fail this equality.
                    assert mark["pnl"] == pytest.approx(cash + shares * bar["close"], abs=1e-7)
                summary = payload["summary"]
                assert summary["net_pnl"] == payload["marks"][-1]["pnl"]
                assert summary["cost"] == pytest.approx(sum(f["assumed_cost"] for f in payload["fills"]))
                assert summary["gross_pnl"] - summary["cost"] == pytest.approx(summary["net_pnl"])
                assert summary["ending_shares"] == position
                assert summary["fill_count"] == len(payload["fills"])


def test_partial_session_keeps_open_short_and_original_cutoff():
    data = price_replay(" sndk ", "2026-09-15", "levels_error_risk")
    assert data["success"] and data["partial"]
    assert data["as_of"] == "2026-09-15T15:50:00-04:00"
    assert data["bars"][-1]["time"] == data["as_of"]
    assert len(data["bars"]) == 76
    assert data["summary"]["ending_shares"] == -3
    assert data["summary"]["net_pnl"] == pytest.approx(-147.1863435058549)
    complete = price_replay("SNDK", "2026-09-14")
    assert not complete["partial"]
    assert complete["summary"]["ending_shares"] == 0


@pytest.mark.parametrize("kwargs", [{"ticker": "MSTR"}, {"date": "2026-09-11"},
                                    {"variant": "does_not_exist"}, {"ticker": "../SNDK"}])
def test_unknown_request_does_not_fall_back_to_wrong_prices_or_zero_pnl(kwargs):
    data = price_replay(**kwargs)
    assert not data["success"]
    assert data["status"] == "unavailable"
    assert data["summary"] is None
    assert data["bars"] == []
    assert data["available_dates"]


def test_missing_or_tampered_bundle_is_unavailable(tmp_path):
    assert not price_replay(root=tmp_path)["success"]
    manifest = json.loads((BUNDLE_ROOT / "manifest.json").read_text())
    name = "2026-09-15/levels_error_risk/SNDK.json"
    destination = tmp_path / name
    destination.parent.mkdir(parents=True)
    raw = (BUNDLE_ROOT / name).read_bytes()
    destination.write_bytes(raw + b" ")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert not price_replay(root=tmp_path)["success"]
    destination.write_bytes(raw)
    assert price_replay(root=tmp_path)["success"]
    # Even a hash-updated wrong-symbol payload must not masquerade as SNDK.
    changed = json.loads(raw)
    changed["ticker"] = "TSLA"
    destination.write_text(json.dumps(changed))
    manifest["files"][name] = hashlib.sha256(destination.read_bytes()).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert not price_replay(root=tmp_path)["success"]
