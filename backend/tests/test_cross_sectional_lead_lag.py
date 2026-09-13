from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.alpha.cross_sectional_lead_lag import CrossSectionalLeadLagEngine


def test_legacy_unaligned_buffers_do_not_emit_fabricated_arbitrage():
    engine = CrossSectionalLeadLagEngine(["TSLA", "PLTR"])
    for value in range(30):
        engine.update_tick("TSLA", 100 + value)
        engine.update_tick("PLTR", 80 + value)
    result = engine.calculate_lead_lag_arbitrage_signal("PLTR")
    assert result["status"] == "unavailable"
    assert result["lead_lag_corr"] is None
    assert result["arbitrage_delta_bps"] is None
