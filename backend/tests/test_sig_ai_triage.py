import hashlib
import json
from datetime import datetime, timezone

from app.news_monitor import _connect
from app.sig_ai_triage import TriageError, _parse, analyze, analyze_pending, status


def test_headline_evidence_must_be_in_title():
    title = "New Maine Senate poll released"
    valid = {"relevance": "high", "event_type": "poll", "summary": "A poll is mentioned.",
             "evidence_quote": "Maine Senate poll", "race_hint": "Maine Senate", "reason": "Review poll methods."}
    result = _parse(json.dumps(valid), title)
    assert result["headline_only"] is True
    assert result["market_mapping"] == "pending"
    valid["evidence_quote"] = "Candidate has withdrawn"
    try:
        _parse(json.dumps(valid), title)
        assert False, "Unsupported evidence should be rejected"
    except TriageError:
        pass


def test_analysis_is_cached_and_counts_only_one_call(tmp_path, monkeypatch):
    monkeypatch.setenv("SIG_GEMINI_API_KEY", "test-key")
    path = tmp_path / "news.sqlite3"
    title = "New Maine Senate poll released"
    news_id = hashlib.sha256(title.encode()).hexdigest()
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(path) as db:
        db.execute("""INSERT INTO news_items
            (id,topic,feed_id,publisher,title,title_key,url,published_at,discovered_at,day,priority)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (news_id, "elections", "test", "Publisher", title, "mainesenatepoll",
             "https://example.org/poll", timestamp, timestamp, timestamp[:10], 3))

    class Response:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": json.dumps({
                "relevance": "high", "event_type": "poll", "summary": "Poll headline.",
                "evidence_quote": "Maine Senate poll", "race_hint": "Maine Senate",
                "reason": "Review source."})}]}}]}

    calls = []

    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    first = analyze(news_id, path, post)
    second = analyze(news_id, path, post)
    assert first["cached"] is False
    assert second["cached"] is True
    assert len(calls) == 1
    assert status(path)["calls_today"] == 1


def test_background_selects_only_unanalyzed_high_priority_election_titles(tmp_path, monkeypatch):
    monkeypatch.setenv("SIG_GEMINI_API_KEY", "test-key")
    path = tmp_path / "news.sqlite3"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(path) as db:
        for topic, priority, title in [("elections", 3, "New Maine Senate poll"),
                                       ("elections", 0, "General election commentary"),
                                       ("markets", 5, "Stock earnings")]:
            news_id = hashlib.sha256(title.encode()).hexdigest()
            db.execute("""INSERT INTO news_items
                (id,topic,feed_id,publisher,title,title_key,url,published_at,discovered_at,day,priority)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (news_id, topic, "test", "Publisher", title, title.lower().replace(" ", ""),
                 "https://example.org/" + news_id, timestamp, timestamp, timestamp[:10], priority))
    seen = []
    monkeypatch.setattr("app.sig_ai_triage.analyze", lambda news_id, path: seen.append(news_id))
    assert analyze_pending(path) == {"analyzed": 1, "failed": 0}
    assert len(seen) == 1
