from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.alpha.real_l1_alpha import REAL_L1_FEATURES, build_real_l1_features, feature_availability


def event(timestamp, kind, **values):
    base = {"schema_version": 1, "event_type": kind, "source": "alpaca_stock_websocket", "symbol": "TSLA"}
    if kind == "quote":
        base.update(market_depth="L1", bid_price=100.0, bid_size=10.0, ask_price=100.1, ask_size=20.0)
    else:
        base.update(market_depth="trade_print", price=100.1, size=5.0)
    return {**base, **values}


def test_real_l1_features_use_quote_and_trade_events_without_ohlcv_fallback():
    frame = pd.DataFrame([
        event("2026-09-11T13:30:00Z", "quote"),
        event("2026-09-11T13:31:00Z", "quote", bid_price=100.05, bid_size=30.0),
        event("2026-09-11T13:31:01Z", "trade", price=100.1, size=8.0),
    ])
    frame.index = pd.to_datetime(["2026-09-11T13:30:00Z", "2026-09-11T13:31:00Z", "2026-09-11T13:31:01Z"], utc=True).tz_convert("America/New_York")
    features = build_real_l1_features(frame)
    assert tuple(features.columns) == REAL_L1_FEATURES
    assert features.attrs["market_depth"] == "L1"
    assert features.iloc[0].l1_quote_imbalance > 0
    assert features.iloc[0].l1_signed_trade_imbalance == pytest.approx(1.0)
    assert feature_availability(features)["usable_for_model"]


def test_proxy_or_missing_l1_events_are_rejected_instead_of_imputed():
    proxy = pd.DataFrame([{"event_type": "quote", "source": "ohlcv_proxy", "symbol": "TSLA", "market_depth": "L1"}], index=pd.DatetimeIndex(["2026-09-11 09:30"], tz="America/New_York"))
    with pytest.raises(ValueError, match="proxy"):
        build_real_l1_features(proxy)
    with pytest.raises(ValueError, match="No captured"):
        build_real_l1_features(pd.DataFrame(columns=["event_type", "source", "symbol", "market_depth"], index=pd.DatetimeIndex([], tz="America/New_York")))
