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
