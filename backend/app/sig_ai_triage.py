"""SIG headline triage through the Gemini Developer API.

Results are cached per headline. This module cannot forecast or submit trades.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from app.news_monitor import _connect


MODEL = "gemini-3.5-flash"
MODEL_PRIORITY = (MODEL, "gemini-3.5-flash-lite", "gemini-2.5-flash")
KEY_FILE = Path(__file__).resolve().parents[1] / ".runtime_state" / "sig_gemini_key"
MODEL_URL = "https://generativelanguage.googleapis.com/v1beta/models/"
_model_cache: tuple[str, str, float] | None = None
RELEVANCE = {"high", "medium", "low", "unclear"}
EVENT_TYPES = {"poll", "candidate", "legal", "election_administration", "other"}


class TriageError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _prepare(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sig_triage_calls (
            news_id TEXT NOT NULL, day TEXT NOT NULL, started_at TEXT NOT NULL,
            status TEXT NOT NULL, PRIMARY KEY(news_id, day)
        );
        CREATE TABLE IF NOT EXISTS sig_triage_results (
            news_id TEXT PRIMARY KEY, model TEXT NOT NULL, result_json TEXT NOT NULL,
            analyzed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sig_triage_control (
            key TEXT PRIMARY KEY, value REAL NOT NULL
        );
    """)


def _key() -> str | None:
    value = os.getenv("SIG_GEMINI_API_KEY", "").strip()
    if value:
        return value
    try:
        return KEY_FILE.read_text().strip() or None
    except OSError:
        return None


def _available_model(key: str) -> str:
    """Probe only approved Flash models; never fall back to an arbitrary model."""
    global _model_cache
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    if _model_cache and _model_cache[0] == fingerprint and _model_cache[2] > time.time():
        return _model_cache[1]
    for model in MODEL_PRIORITY:
        try:
            response = requests.get(MODEL_URL + model, headers={"x-goog-api-key": key}, timeout=10)
        except requests.RequestException as exc:
            raise TriageError("Could not check Google model availability") from exc
        if response.status_code == 200:
            _model_cache = (fingerprint, model, time.time() + 3600)
            return model
        if response.status_code in {401, 403}:
            raise TriageError("Google rejected the configured API key", 503)
    raise TriageError("No supported Gemini Flash model is available for this key", 503)


def status(path: Path | None = None) -> dict:
    day = datetime.now(timezone.utc).date().isoformat()
    with _connect(path) as db:
        _prepare(db)
        used = db.execute("SELECT COUNT(*) FROM sig_triage_calls WHERE day=? AND status='ok'", (day,)).fetchone()[0]
        failed = db.execute("SELECT COUNT(*) FROM sig_triage_calls WHERE day=? AND status='error'", (day,)).fetchone()[0]
        pause = db.execute("SELECT value FROM sig_triage_control WHERE key='quota_pause'").fetchone()
    selected = _model_cache[1] if _model_cache and _model_cache[2] > time.time() else MODEL
    paused_until = (datetime.fromtimestamp(pause["value"], timezone.utc).isoformat(timespec="seconds")
                    if pause and pause["value"] > time.time() else None)
    return {"available": bool(_key()), "model": selected, "calls_today": used,
            "failed_today": failed, "paused_until": paused_until}


def results(path: Path | None = None, limit: int = 100) -> dict[str, dict]:
    with _connect(path) as db:
        _prepare(db)
        rows = db.execute("""SELECT news_id,model,result_json,analyzed_at FROM sig_triage_results
            ORDER BY analyzed_at DESC LIMIT ?""", (max(1, min(limit, 100)),)).fetchall()
    return {row["news_id"]: {**json.loads(row["result_json"]), "model": row["model"],
                              "analyzed_at": row["analyzed_at"]} for row in rows}


def _parse(text: str, title: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise TriageError("The model did not return usable JSON")
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError) as exc:
        raise TriageError("The model returned malformed JSON") from exc
    if not isinstance(data, dict):
        raise TriageError("The model returned an invalid result")
    relevance = data.get("relevance")
    event_type = data.get("event_type")
    if relevance not in RELEVANCE or event_type not in EVENT_TYPES:
        raise TriageError("The model returned an invalid classification")
    evidence = str(data.get("evidence_quote", ""))[:240].strip()
    if not evidence or evidence.casefold() not in title.casefold():
        raise TriageError("The model evidence does not match the headline")
    race_hint = str(data.get("race_hint") or "")[:100].strip()
    if race_hint and race_hint.casefold() not in title.casefold():
        race_hint = ""
    return {"relevance": relevance, "event_type": event_type,
            "summary": str(data.get("summary", ""))[:280].strip(),
            "evidence_quote": evidence, "race_hint": race_hint or None,
            "reason": str(data.get("reason", ""))[:280].strip(),
            "source_review_required": True, "headline_only": True,
            "market_mapping": "pending"}


def _prompt(item: sqlite3.Row) -> str:
    return (
        "You are screening an untrusted RSS headline for the 2026 U.S. midterm "
        "election prediction markets. You have NOT read the article. The headline "
        "is a claim, not verified evidence. Do not infer facts from its URL. "
        "Return one JSON object only with: relevance (high|medium|low|unclear), "
        "event_type (poll|candidate|legal|election_administration|other), "
        "summary (short English sentence about the headline claim), "
        "evidence_quote (exact contiguous text from the title), "
        "race_hint (exact contiguous location/race text from title or null), "
        "reason (why a person should or should not review the original source). "
        "Do not estimate probabilities, identify an exact SIG contract, or suggest trades. "
        "When information is thin, use unclear.\n"
        f"Title: {item['title'][:320]}\nPublisher: {item['publisher'][:80]}\n"
        f"Published: {item['published_at'] or 'unknown'}\n"
    )


def analyze(news_id: str, path: Path | None = None, post=None) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", news_id):
        raise TriageError("Invalid news ID", 400)
    key = _key()
    if not key:
        raise TriageError("AI triage key is not configured", 503)
    model = _available_model(key) if post is None else MODEL
    day = datetime.now(timezone.utc).date().isoformat()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(path) as db:
        _prepare(db)
        pause = db.execute("SELECT value FROM sig_triage_control WHERE key='quota_pause'").fetchone()
        if pause and pause["value"] > time.time():
            raise TriageError("AI analysis is paused after a Google quota response", 429)
        item = db.execute("SELECT * FROM news_items WHERE id=? AND topic='elections'", (news_id,)).fetchone()
        if item is None:
            raise TriageError("Election headline not found", 404)
        cached = db.execute("SELECT model,result_json,analyzed_at FROM sig_triage_results WHERE news_id=?", (news_id,)).fetchone()
        if cached:
            return {**json.loads(cached["result_json"]), "model": cached["model"],
                    "analyzed_at": cached["analyzed_at"], "cached": True}
        db.execute("BEGIN IMMEDIATE")
        reservation = db.execute("""INSERT INTO sig_triage_calls VALUES(?,?,?,?)
            ON CONFLICT(news_id,day) DO UPDATE SET started_at=excluded.started_at,status='started'
            WHERE sig_triage_calls.status='error'""", (news_id, day, now, "started"))
        if reservation.rowcount == 0:
            raise TriageError("This headline is already being analyzed", 409)

    try:
        send = post or requests.post
        payload = {"contents": [{"parts": [{"text": _prompt(item)}]}],
                   "generationConfig": {"maxOutputTokens": 700,
                                        "thinkingConfig": {"thinkingLevel": "minimal"}}}
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
        response = send(MODEL_URL + model + ":generateContent", headers=headers,
                        json=payload, timeout=75)
        if response.status_code in {500, 502, 503, 504} and model == MODEL and post is None:
            # The preferred Flash model can be temporarily overloaded. Use the
            # already-approved Flash Lite model and remember it for one hour.
            model = "gemini-3.5-flash-lite"
            response = send(MODEL_URL + model + ":generateContent", headers=headers,
                            json=payload, timeout=75)
            global _model_cache
            if response.status_code == 200:
                _model_cache = (hashlib.sha256(key.encode()).hexdigest(), model, time.time() + 3600)
        if response.status_code == 429:
            raise TriageError("Google's free quota is temporarily exhausted", 429)
        if response.status_code != 200:
            raise TriageError(f"Google AI request returned HTTP {response.status_code}")
        payload = response.json()
        text = "".join(str(part.get("text", "")) for candidate in payload.get("candidates", [])
                       for part in candidate.get("content", {}).get("parts", []) if isinstance(part, dict))
        result = _parse(text, item["title"])
        with _connect(path) as db:
            _prepare(db)
            db.execute("""INSERT OR REPLACE INTO sig_triage_results VALUES(?,?,?,?)""",
                       (news_id, model, json.dumps(result), now))
            db.execute("UPDATE sig_triage_calls SET status='ok' WHERE news_id=? AND day=?", (news_id, day))
        return {**result, "model": model, "analyzed_at": now, "cached": False}
    except (requests.RequestException, ValueError, TriageError) as exc:
        with _connect(path) as db:
            _prepare(db)
            db.execute("UPDATE sig_triage_calls SET status='error' WHERE news_id=? AND day=?", (news_id, day))
            if isinstance(exc, TriageError) and exc.status_code == 429:
                db.execute("""INSERT INTO sig_triage_control VALUES('quota_pause',?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (time.time() + 1800,))
        if isinstance(exc, TriageError):
            raise
        raise TriageError("Google AI analysis failed") from exc


def analyze_pending(path: Path | None = None, limit: int = 8) -> dict:
    """Analyze recent high-priority headlines after a feed collection pass."""
    if not _key():
        return {"analyzed": 0, "failed": 0}
    day = datetime.now(timezone.utc).date().isoformat()
    with _connect(path) as db:
        _prepare(db)
        pause = db.execute("SELECT value FROM sig_triage_control WHERE key='quota_pause'").fetchone()
        if pause and pause["value"] > time.time():
            return {"analyzed": 0, "failed": 0}
        rows = db.execute("""SELECT n.id FROM news_items n
            LEFT JOIN sig_triage_results r ON r.news_id=n.id
            LEFT JOIN sig_triage_calls c ON c.news_id=n.id AND c.day=?
            WHERE n.topic='elections' AND n.priority>=3 AND r.news_id IS NULL
              AND c.news_id IS NULL
            ORDER BY n.priority DESC, COALESCE(n.published_at,n.discovered_at) DESC
            LIMIT ?""", (day, max(1, min(limit, 20)))).fetchall()
    analyzed = failed = 0
    for row in rows:
        try:
            analyze(row["id"], path)
            analyzed += 1
        except TriageError as exc:
            failed += 1
            if exc.status_code == 429:
                break
    return {"analyzed": analyzed, "failed": failed}
