"""Bounded, zero-LLM collection of public Futu community posts."""

from __future__ import annotations

import html
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from app.news_monitor import _connect, db_path

ENDPOINT = "https://ai-news-search.futunn.com/stock_feed"
WATCHLIST = Path(__file__).resolve().parents[1] / "watchlist.json"


def symbols() -> list[str]:
    try:
        raw = json.loads(WATCHLIST.read_text())
        return list(dict.fromkeys(s for s in raw if isinstance(s, str) and re.fullmatch(r"[A-Z]{1,5}", s)))[:8]
    except (OSError, ValueError, TypeError):
        return []


def _prepare(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS community_posts (
            symbol TEXT NOT NULL, post_id TEXT NOT NULL, title TEXT NOT NULL,
            excerpt TEXT NOT NULL, published_at TEXT, discovered_at TEXT NOT NULL,
            PRIMARY KEY(symbol, post_id)
        );
        CREATE INDEX IF NOT EXISTS community_posts_latest
            ON community_posts(symbol, published_at DESC);
        CREATE TABLE IF NOT EXISTS community_sources (
            symbol TEXT PRIMARY KEY, last_attempt TEXT, last_success TEXT,
            status TEXT NOT NULL, last_count INTEGER NOT NULL DEFAULT 0
        );
    """)


def _clean(value: str | None, limit: int) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()[:limit]


def parse_posts(payload: dict, symbol: str, now: datetime | None = None) -> list[dict]:
    if payload.get("code") != 0 or not isinstance(payload.get("data"), list):
        raise ValueError("Invalid Futu response")
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
    result = []
    for item in payload["data"][:30]:
        if not isinstance(item, dict):
            continue
        post_id = str(item.get("id", ""))
        if not re.fullmatch(r"\d{1,25}", post_id):
            continue
        title, excerpt = _clean(item.get("title"), 240), _clean(item.get("desc"), 1200)
        if len(title + excerpt) < 8:
            continue
        try:
            timestamp = float(item["publish_time"])
            if timestamp > 1e12:
                timestamp /= 1000
            published = datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")
            if timestamp > time.time() + 86400 or timestamp < time.time() - 14 * 86400:
                continue
        except (KeyError, TypeError, ValueError, OverflowError):
            published = None
        result.append({"symbol": symbol, "post_id": post_id, "title": title,
                       "excerpt": excerpt, "published_at": published, "discovered_at": observed})
    return result


def collect_once(path: Path | None = None, fetch=None) -> dict:
    fetch = fetch or requests.get
    inserted, failures = 0, 0
    with _connect(path) as db:
        _prepare(db)
    for symbol in symbols():
        attempted = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            response = fetch(ENDPOINT, params={"keyword": symbol, "size": 30},
                             headers={"User-Agent": "QuantAI-CommunityMonitor/1.0"}, timeout=15)
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                raise ValueError("Response too large")
            posts = parse_posts(response.json(), symbol)
            with _connect(path) as db:
                _prepare(db)
                for post in posts:
                    result = db.execute("""INSERT OR IGNORE INTO community_posts
                        (symbol,post_id,title,excerpt,published_at,discovered_at)
                        VALUES(:symbol,:post_id,:title,:excerpt,:published_at,:discovered_at)""", post)
                    inserted += result.rowcount
                db.execute("""INSERT INTO community_sources VALUES(?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET last_attempt=excluded.last_attempt,
                    last_success=excluded.last_success,status=excluded.status,last_count=excluded.last_count""",
                    (symbol, attempted, attempted, "ok", len(posts)))
        except (requests.RequestException, ValueError, TypeError, sqlite3.Error):
            failures += 1
            with _connect(path) as db:
                _prepare(db)
                db.execute("""INSERT INTO community_sources(symbol,last_attempt,status,last_count)
                    VALUES(?,?,?,0) ON CONFLICT(symbol) DO UPDATE SET
                    last_attempt=excluded.last_attempt,status=excluded.status,last_count=0""",
                    (symbol, attempted, "error"))
    with _connect(path) as db:
        _prepare(db)
        db.execute("DELETE FROM community_posts WHERE discovered_at < ?",
                   (datetime.fromtimestamp(time.time() - 45 * 86400, timezone.utc).isoformat(timespec="seconds"),))
    return {"inserted": inserted, "failed_sources": failures}


def snapshot(symbol: str, limit: int = 30, path: Path | None = None) -> dict:
    symbol = symbol.upper()
    if not re.fullmatch(r"[A-Z]{1,5}", symbol):
        raise ValueError("Invalid symbol")
    with _connect(path) as db:
        _prepare(db)
        posts = [dict(row) for row in db.execute("""SELECT post_id,title,excerpt,published_at,discovered_at
            FROM community_posts WHERE symbol=? ORDER BY COALESCE(published_at,discovered_at) DESC LIMIT ?""",
            (symbol, max(1, min(limit, 50))))]
        source = db.execute("SELECT * FROM community_sources WHERE symbol=?", (symbol,)).fetchone()
    return {"symbol": symbol, "posts": posts, "source": dict(source) if source else None,
            "analysis": None, "contrarian_signal": None}
