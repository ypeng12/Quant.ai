"""Versioned, research-only universes.

They are deliberately separate from the broker watchlist.  Selecting a research
universe never changes a live account, starts collection, or submits orders.
"""
from __future__ import annotations

# Alpaca's free IEX WebSocket plan supports at most 30 simultaneous symbols.
# The list contains broad market/sector references plus liquid names spanning
# the current four-name project.  It is a research panel, not a recommendation
# or an automatically tradable universe.
LIQUID_US_IEX_30 = (
    "SPY", "QQQ", "IWM", "XLK", "SOXX",
    "AAPL", "MSFT", "NVDA", "AMD", "AVGO", "MU", "SNDK",
    "TSLA", "META", "AMZN", "GOOGL", "NFLX", "ORCL", "PLTR",
    "COIN", "MSTR", "MARA", "HOOD", "SMCI", "INTC", "TSM",
    "CRM", "UBER", "JPM", "XLF",
)

RESEARCH_UNIVERSES = {"liquid_us_iex_30": LIQUID_US_IEX_30}


def research_universe(name: str) -> tuple[str, ...]:
    """Return a fixed, deduplicated research panel by versioned name."""
    try:
        symbols = RESEARCH_UNIVERSES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown research universe: {name}") from exc
    if len(symbols) != len(set(symbols)):
        raise ValueError(f"Research universe {name} contains duplicate symbols")
    return symbols
