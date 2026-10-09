#!/usr/bin/env python3
"""Bounded, read-only public Futu endpoint audit; never accesses app databases.

Usage: python3 scripts/audit_signal_lab_futu.py --output reports/market_impact_data_audit_20261007/futu
Four public HTTP requests by default. Raw responses are research snapshots, not
licensed full-text archives. No pagination, login, retry, LLM, or trading calls.
Use a new --output directory for each run; existing evidence is never overwritten.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "https://ai-news-search.futunn.com/stock_feed"
ALIASES = {
    "NVDA": ["NVDA", "NVIDIA", "英伟达", "英偉達", "辉达", "輝達"],
    "SNDK": ["SNDK", "SANDISK", "闪迪", "閃迪"],
    "TSLA": ["TSLA", "TESLA", "特斯拉"],
    "PLTR": ["PLTR", "PALANTIR", "帕兰提尔", "帕蘭提爾"],
}


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()


def as_date(value: object) -> str | None:
    try:
        number = float(value)
        return datetime.fromtimestamp(number / 1000 if number > 1e12 else number, timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def quantiles(values: list[int]) -> dict:
    values = sorted(values)
    if not values:
        return {}
    return {"min": values[0], "median": values[len(values) // 2], "p90": values[int((len(values) - 1) * .9)], "max": values[-1], "total": sum(values)}


def run(output: Path, symbols: list[str]) -> dict:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Audit directory is not empty: {output}. Use a new --output directory.")
    output.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    per_symbol = {}
    for symbol in symbols:
        request_started_at = stamp()
        url = ENDPOINT + "?" + urllib.parse.urlencode({"keyword": symbol, "size": 30})
        request = urllib.request.Request(url, headers={"User-Agent": "QuantAI-CommunityMonitor/1.0"})
        metadata = {"symbol": symbol, "url": url, "request_started_at": request_started_at, "requested_size": 30}
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                content = response.read(1_000_001)
                response_received_at = stamp()
                metadata.update(http_status=response.status, content_type=response.headers.get("Content-Type"), response_date=response.headers.get("Date"), response_bytes=len(content), response_received_at=response_received_at)
            if len(content) > 1_000_000:
                raise ValueError("Response exceeds 1 MB audit limit")
            payload = json.loads(content)
            (output / f"{symbol}_raw.json").write_bytes(content)
            metadata["sha256"] = hashlib.sha256(content).hexdigest()
            metadata["api_code"] = payload.get("code") if isinstance(payload, dict) else None
            items = payload.get("data", []) if isinstance(payload, dict) else []
            if not isinstance(items, list):
                raise ValueError("API data is not a list")
            metadata["returned_count"] = len(items)
            metadata["field_counts"] = dict(collections.Counter(key for item in items if isinstance(item, dict) for key in item))
            rows = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                title, excerpt = clean(item.get("title")), clean(item.get("desc"))
                text = title + " " + excerpt
                source = item.get("source")
                author_keys = [key for key in item if re.search(r"author|user|uid|nickname", key, re.I)]
                interaction_keys = [key for key in item if re.search(r"like|comment|reply|share|read|view|favor|interact", key, re.I)]
                links = re.findall(r"https?://[^\s<>\"'\\]+", " ".join(str(value) for value in item.values()))
                published = as_date(item.get("publish_time"))
                rows.append({
                    "query_symbol": symbol, "post_id": str(item.get("id", "")),
                    "title": title, "excerpt": excerpt, "title_chars": len(title), "excerpt_chars": len(excerpt),
                    "published_at": published, "request_started_at": request_started_at,
                    "response_received_at": response_received_at, "first_seen_in_this_audit_at": response_received_at,
                    "raw_publish_time": item.get("publish_time"), "source": source,
                    "all_raw_fields": sorted(item), "author_fields": author_keys,
                    "interaction_fields": interaction_keys, "url_values": links,
                    "contains_chinese_characters": bool(re.search(r"[\u4e00-\u9fff]", text)),
                    "query_alias_present": any(alias.lower() in text.lower() for alias in ALIASES.get(symbol, [symbol])),
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                })
            write_json(output / f"{symbol}_normalized.json", rows)
            dates = [row["published_at"] for row in rows if row["published_at"]]
            metadata.update(
                unique_ids=len(set(row["post_id"] for row in rows)),
                unique_texts=len(set(row["text_sha256"] for row in rows)),
                published_min=min(dates) if dates else None,
                published_max=max(dates) if dates else None,
                title_chars=quantiles([row["title_chars"] for row in rows]),
                excerpt_chars=quantiles([row["excerpt_chars"] for row in rows]),
                missing_title=sum(not row["title"] for row in rows),
                missing_excerpt=sum(not row["excerpt"] for row in rows),
                chinese_rows=sum(row["contains_chinese_characters"] for row in rows),
                query_alias_rows=sum(row["query_alias_present"] for row in rows),
                rows_with_author_field=sum(bool(row["author_fields"]) for row in rows),
                rows_with_interaction_field=sum(bool(row["interaction_fields"]) for row in rows),
                rows_with_url=sum(bool(row["url_values"]) for row in rows),
                title_equals_excerpt=sum(row["title"] == row["excerpt"] for row in rows),
                excerpt_under_50_chars=sum(row["excerpt_chars"] < 50 for row in rows),
                title_over_app_limit_240=sum(row["title_chars"] > 240 for row in rows),
                excerpt_over_app_limit_1200=sum(row["excerpt_chars"] > 1200 for row in rows),
            )
            all_rows.extend(rows)
        except urllib.error.HTTPError as exc:
            metadata.update(http_status=exc.code, error=str(exc))
            (output / f"{symbol}_error.txt").write_bytes(exc.read(4000))
        except Exception as exc:
            metadata.update(error=f"{type(exc).__name__}: {exc}")
        metadata["duration_seconds"] = round(time.monotonic() - started, 3)
        per_symbol[symbol] = metadata
        write_json(output / f"{symbol}_request.json", metadata)
    id_symbols = collections.defaultdict(set)
    for row in all_rows:
        id_symbols[row["post_id"]].add(row["query_symbol"])
    summary = {
        "completed_at": stamp(), "read_only": True, "request_count": len(symbols),
        "endpoint": ENDPOINT, "method": "One GET per symbol; no retry, login, pagination, app DB writes, or LLM.",
        "normalization_note": "Raw title/desc cleaned without truncation. Presence-based field checks and alias matches are heuristics, not semantic relevance or sentiment labels. Raw payload is preserved.",
        "per_symbol": per_symbol, "total_rows": len(all_rows),
        "global_unique_post_ids": len(id_symbols),
        "global_unique_texts": len(set(row["text_sha256"] for row in all_rows)),
        "post_ids_returned_for_multiple_symbols": {key: sorted(value) for key, value in id_symbols.items() if len(value) > 1},
    }
    write_json(output / "all_normalized.json", all_rows)
    write_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports/market_impact_data_audit_20261007/futu"))
    parser.add_argument("--symbols", nargs="+", default=["NVDA", "SNDK", "TSLA", "PLTR"])
    args = parser.parse_args()
    if not all(re.fullmatch(r"[A-Z]{1,5}", symbol) for symbol in args.symbols) or len(args.symbols) > 4:
        parser.error("Use at most four uppercase US stock tickers")
    result = run(args.output, args.symbols)
    print(json.dumps(result, ensure_ascii=False, indent=2))
