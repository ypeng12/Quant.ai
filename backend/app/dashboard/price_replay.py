"""Serve portable saved research, without loading models or contacting a broker."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


BUNDLE_ROOT = Path(__file__).resolve().parents[2] / "data" / "price_replay"


def price_replay(ticker="SNDK", date="", variant="levels_error_risk", *, root=None):
    root = Path(root) if root is not None else BUNDLE_ROOT
    ticker = ticker.strip().upper()
    request = {"ticker": ticker, "date": date, "variant": variant}
    metadata = {"available_dates": [], "variants": [], "tickers": []}
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        metadata = {key: manifest[key] for key in metadata}
        date = date or max(metadata["available_dates"])
        request["date"] = date
        if (ticker not in metadata["tickers"] or date not in metadata["available_dates"]
                or variant not in metadata["variants"]):
            raise ValueError("No saved research for the requested ticker, date and model.")
        name = f"{date}/{variant}/{ticker}.json"
        raw = (root / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["files"][name]:
            raise ValueError("Saved replay integrity check failed.")
        payload = json.loads(raw)
        if any(payload[key] != value for key, value in request.items()):
            raise ValueError("Saved replay identity does not match the requested data.")
        return {**payload, **metadata, "success": True}
    except (OSError, ValueError, KeyError, TypeError):
        return {"success": False, "status": "unavailable", **request, **metadata,
                "error": "该股票、日期或模型的已保存回放不可用，或数据校验失败。",
                "bars": [], "fills": [], "marks": [], "summary": None}


def replay_date_catalog(ticker, variant, broker_dates, today, *, root=None):
    """Calendar dates remain visible even when no research artifact exists."""
    root = Path(root) if root is not None else BUNDLE_ROOT
    research_dates = []
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        research_dates = [day for day in manifest["available_dates"]
                          if f"{day}/{variant}/{ticker.upper()}.json" in manifest["files"] and day <= today]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return dict(success=True, today=today,
                available_dates=sorted({today, *broker_dates, *research_dates}, reverse=True),
                research_dates=sorted(research_dates, reverse=True))
