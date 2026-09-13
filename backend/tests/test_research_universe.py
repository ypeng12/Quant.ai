from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research.universe import LIQUID_US_IEX_30, RESEARCH_UNIVERSES, research_universe


def test_free_iex_research_universe_is_fixed_and_within_stream_limit():
    symbols = research_universe("liquid_us_iex_30")
    assert symbols == LIQUID_US_IEX_30
    assert len(symbols) == 30
    assert len(set(symbols)) == 30
    assert {"SNDK", "TSLA", "MSTR", "NVDA", "SPY", "QQQ"}.issubset(symbols)
    assert tuple(RESEARCH_UNIVERSES) == ("liquid_us_iex_30",)
