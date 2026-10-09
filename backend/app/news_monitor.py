"""Low-cost, read-only news discovery for Quant.ai.

The collector stores RSS metadata and source-provided excerpts. A separate
cached triage step may summarize selected excerpts; it does not fetch full
article pages, infer probabilities, or send trade instructions.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

import requests


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / ".runtime_state" / "news.sqlite3"
try:
    POLL_SECONDS = max(300, int(os.getenv("QUANT_NEWS_POLL_SECONDS", "1200")))
except ValueError:
    POLL_SECONDS = 1200
MAX_FEED_BYTES = 2_000_000
USER_AGENT = "QuantAI-NewsMonitor/1.0 (+https://github.com/ypeng12/Quant.ai)"
_thread: threading.Thread | None = None
_stop = threading.Event()


@dataclass(frozen=True)
class Feed:
    id: str
    topic: str
    label: str
    url: str
    official: bool = False
    terms: tuple[str, ...] = ()


def feeds() -> list[Feed]:
    election_query = quote("2026 midterm election when:1d")
    try:
        watchlist = json.loads((Path(__file__).resolve().parents[1] / "watchlist.json").read_text())
        tickers = [ticker for ticker in watchlist if isinstance(ticker, str) and re.fullmatch(r"[A-Z]{1,5}", ticker)][:6]
    except (OSError, ValueError, TypeError):
        tickers = ["NVDA", "TSLA", "PLTR", "SNDK"]
    names = {"NVDA": "Nvidia", "TSLA": "Tesla", "PLTR": "Palantir", "SNDK": "Sandisk", "AAPL": "Apple", "MSFT": "Microsoft", "AMD": "AMD"}
    company_terms = [names.get(ticker, ticker) for ticker in tickers]
    market_terms = company_terms + ["Federal Reserve"]
    market_query = quote("(" + " OR ".join(f'"{term}"' for term in market_terms) + ") when:1d")
    suffix = "&hl=en-US&gl=US&ceid=US:en"
    return [
        Feed("google-election", "elections", "Google News: Midterms", f"https://news.google.com/rss/search?q={election_query}{suffix}"),
        Feed("pbs-politics", "elections", "PBS NewsHour: Politics", "https://www.pbs.org/newshour/feeds/rss/politics"),
        Feed("abc-politics", "elections", "ABC News: Politics", "https://feeds.abcnews.com/abcnews/politicsheadlines"),
        Feed("nbc-politics", "elections", "NBC News: Politics", "https://feeds.nbcnews.com/nbcnews/public/politics"),
        Feed("google-markets", "markets", "Google News: Markets", f"https://news.google.com/rss/search?q={market_query}{suffix}", terms=tuple(company_terms)),
        Feed("eac", "elections", "U.S. Election Assistance Commission", "https://www.eac.gov/rss.xml", True),
    ]


def db_path() -> Path:
    return Path(os.getenv("QUANT_NEWS_DB_PATH", str(DEFAULT_DB_PATH))).expanduser()


@contextmanager
def _connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(target), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS news_items (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            feed_id TEXT NOT NULL,
            publisher TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            title_key TEXT NOT NULL,
            url TEXT NOT NULL,
            published_at TEXT,
            discovered_at TEXT NOT NULL,
            day TEXT NOT NULL,
            priority INTEGER NOT NULL,
            UNIQUE(topic, title_key, day)
        );
        CREATE INDEX IF NOT EXISTS news_topic_time ON news_items(topic, discovered_at DESC);
        CREATE TABLE IF NOT EXISTS news_sources (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            label TEXT NOT NULL,
            last_attempt TEXT,
            last_success TEXT,
            status TEXT NOT NULL,
            error TEXT,
            last_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS news_control (key TEXT PRIMARY KEY, lease_until REAL NOT NULL);
    """)
    # Add the feed excerpt field to databases created by earlier app versions.
    columns = {row["name"] for row in db.execute("PRAGMA table_info(news_items)")}
    if "content" not in columns:
        db.execute("ALTER TABLE news_items ADD COLUMN content TEXT NOT NULL DEFAULT ''")
    try:
        with db:
            yield db
    finally:
        db.close()


def _clean(text: str | None, limit: int = 320) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _feed_content(item: ET.Element) -> str:
    # RSS publishers commonly put their short article excerpt in description;
    # Atom and RSS content modules use one of these namespaced elements.
    candidates = [item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded"),
                  item.findtext("{http://www.w3.org/2005/Atom}content"),
                  item.findtext("{http://www.w3.org/2005/Atom}summary"),
                  item.findtext("description")]
    for candidate in candidates:
        cleaned = _clean(candidate, 1600)
        if cleaned:
            return cleaned
    return ""


def _canonical_url(raw: str | None) -> str | None:
    if not raw:
        return None
    parts = urlsplit(raw.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    # Bing RSS points to a redirect. Use the supplied destination for stable IDs.
    if parts.hostname.endswith("bing.com") and parts.path.endswith("/apiclick.aspx"):
        destination = parse_qs(parts.query).get("url", [None])[0]
        if destination and destination != raw:
            return _canonical_url(destination)
    kept = [(k, v) for k, values in parse_qs(parts.query).items() for v in values
            if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", urlencode(kept), ""))


def _published(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def _priority(topic: str, title: str, official: bool) -> int:
    t = title.casefold()
    score = 3 if official else 0
    if topic == "elections":
        for pattern, weight in ((r"\bpolls?\b|\bsurveys?\b", 3), (r"drop(?:s|ped)? out|withdraw|resign|replace", 4),
                                (r"court|ballot|redistrict|recount|certif", 3), (r"senate|house|governor", 1)):
            if re.search(pattern, t):
                score += weight
    else:
        for pattern, weight in ((r"earnings|guidance|filing", 3), (r"federal reserve|rate decision|inflation|jobs report", 3),
                                (r"nvidia|tesla|stock market", 1)):
            if re.search(pattern, t):
                score += weight
    return min(score, 10)


def _matches_topic(feed: Feed, title: str) -> bool:
    text = title.casefold()
    if feed.topic == "elections":
        return bool(re.search(r"midterm|election|senate|congress|house race|governor|\bpoll\b|ballot|candidate|\brace\b|recount|redistrict|certif", text))
    terms = list(feed.terms) or ["Nvidia", "Tesla", "Palantir", "Sandisk"]
    terms.extend(["Federal Reserve", "Fed rate", "stock market", "Wall Street"])
    return any(re.search(r"\b" + re.escape(term.casefold()) + r"\b", text) for term in terms)


def parse_rss(payload: bytes, feed: Feed, now: datetime | None = None) -> list[dict]:
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    observed = now_utc.isoformat(timespec="seconds")
    root = ET.fromstring(payload)
    records: list[dict] = []
    for item in root.findall(".//item")[:75]:
        title = _clean(item.findtext("title"))
        link = _canonical_url(item.findtext("link"))
        if not title or not link or not _matches_topic(feed, title):
            continue
        published_at = _published(item.findtext("pubDate"))
        if published_at and datetime.fromisoformat(published_at) < now_utc - timedelta(days=14):
            continue
        source = _clean(item.findtext("source"), 80) or feed.label
        title_key = re.sub(r"[^a-z0-9]+", "", title.casefold())[:180]
        if not title_key:
            continue
        # Google News RSS wraps the title and publisher name in an anchor; it
        # is not an article excerpt and should not trigger an AI call.
        content = "" if feed.id.startswith("google-") else _feed_content(item)
        date = (published_at or observed)[:10]
        records.append({
            "id": hashlib.sha256(f"{feed.topic}:{link}".encode()).hexdigest(),
            "topic": feed.topic, "feed_id": feed.id, "publisher": source,
            "title": title, "content": content, "title_key": title_key, "url": link,
            "published_at": published_at, "discovered_at": observed,
            "day": date, "priority": _priority(feed.topic, title, feed.official),
        })
    return records


def _download(url: str) -> bytes:
    response = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"}, timeout=15)
    response.raise_for_status()
    if len(response.content) > MAX_FEED_BYTES:
        raise ValueError("Feed exceeds size limit")
    return response.content


def collect_once(path: Path | None = None, downloader=None) -> dict:
    """Collect one bounded pass. Easy to call from a scheduler or an isolated test."""
    fetch = downloader or _download
    inserted = 0
    failures = 0
    for feed in feeds():
        attempted = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            records = parse_rss(fetch(feed.url), feed)
            with _connect(path) as db:
                for row in records:
                    columns = ",".join(row)
                    placeholders = ",".join("?" for _ in row)
                    result = db.execute(f"INSERT OR IGNORE INTO news_items ({columns}) VALUES ({placeholders})", tuple(row.values()))
                    inserted += result.rowcount
                    if result.rowcount == 0:
                        db.execute("""UPDATE news_items SET
                            priority=MAX(priority,?),
                            content=CASE WHEN content='' THEN ? ELSE content END
                            WHERE topic=? AND title_key=? AND day=?""",
                                   (row["priority"], row["content"], row["topic"], row["title_key"], row["day"]))
                db.execute("""INSERT INTO news_sources(id,topic,label,last_attempt,last_success,status,error,last_count)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    last_attempt=excluded.last_attempt,last_success=excluded.last_success,
                    status=excluded.status,error=excluded.error,last_count=excluded.last_count""",
                    (feed.id, feed.topic, feed.label, attempted, attempted, "ok", None, len(records)))
        except (requests.RequestException, ET.ParseError, ValueError, OSError, sqlite3.Error) as exc:
            failures += 1
            with _connect(path) as db:
                db.execute("""INSERT INTO news_sources(id,topic,label,last_attempt,status,error,last_count)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    last_attempt=excluded.last_attempt,status=excluded.status,error=excluded.error,last_count=excluded.last_count""",
                    (feed.id, feed.topic, feed.label, attempted, "error", type(exc).__name__, 0))
    with _connect(path) as db:
        # Keep a bounded local index. Published stories can be found at their source URLs.
        cutoff = datetime.fromtimestamp(time.time() - 45 * 86400, timezone.utc).isoformat(timespec="seconds")
        db.execute("DELETE FROM news_items WHERE discovered_at < ?", (cutoff,))
        recent_cutoff = datetime.fromtimestamp(time.time() - 14 * 86400, timezone.utc).isoformat(timespec="seconds")
        db.execute("DELETE FROM news_items WHERE published_at IS NOT NULL AND published_at < ?", (recent_cutoff,))
        db.execute("""DELETE FROM news_items WHERE id IN
            (SELECT id FROM news_items ORDER BY discovered_at DESC LIMIT -1 OFFSET 5000)""")
    return {"inserted": inserted, "failed_sources": failures}


def list_items(topic: str | None = None, limit: int = 40, path: Path | None = None) -> list[dict]:
    limit = max(1, min(100, limit))
    with _connect(path) as db:
        if topic in {"elections", "markets"}:
            rows = db.execute("""SELECT id,topic,publisher,title,content,url,published_at,discovered_at,priority
                FROM news_items WHERE topic=? ORDER BY COALESCE(published_at,discovered_at) DESC,priority DESC LIMIT ?""", (topic, limit)).fetchall()
        else:
            rows = db.execute("""SELECT id,topic,publisher,title,content,url,published_at,discovered_at,priority
                FROM news_items ORDER BY COALESCE(published_at,discovered_at) DESC,priority DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(row) for row in rows]


def source_status(path: Path | None = None) -> list[dict]:
    with _connect(path) as db:
        stored = {row["id"]: dict(row) for row in db.execute("SELECT * FROM news_sources")}
    return [stored.get(feed.id, {
        "id": feed.id, "topic": feed.topic, "label": feed.label,
        "last_attempt": None, "last_success": None, "status": "waiting", "error": None, "last_count": 0,
    }) for feed in feeds()]


def _take_lease(path: Path | None = None) -> bool:
    with _connect(path) as db:
        now = time.time()
        result = db.execute("""INSERT INTO news_control(key,lease_until) VALUES('poll',?)
            ON CONFLICT(key) DO UPDATE SET lease_until=excluded.lease_until
            WHERE news_control.lease_until < ?""", (now + 120, now))
        return result.rowcount == 1


def _worker() -> None:
    while not _stop.is_set():
        try:
            if _take_lease():
                collect_once()
                from app.sig_ai_triage import analyze_pending
                analyze_pending()
        except (OSError, sqlite3.Error):
            pass
        _stop.wait(POLL_SECONDS)


def start_monitor() -> None:
    global _thread
    if os.getenv("QUANT_NEWS_ENABLED", "1").lower() in {"0", "false", "no"}:
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_worker, name="quant-news-monitor", daemon=True)
    _thread.start()


def stop_monitor() -> None:
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=3)
