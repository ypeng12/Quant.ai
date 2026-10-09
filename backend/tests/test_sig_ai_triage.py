import hashlib
import json
from datetime import datetime, timezone

import pytest

from app import sig_ai_triage
from app.news_monitor import _connect
from app.sig_ai_triage import TriageError, _parse, analyze, analyze_pending, results, status


def test_evidence_must_be_in_the_supplied_excerpt():
    title = "New Maine Senate poll released"
    excerpt = "Researchers surveyed 800 likely voters in the Maine Senate race."
    valid = {"relevance": "high", "event_type": "poll", "summary": "A poll is mentioned.",
             "evidence_quote": "surveyed 800 likely voters", "race_hint": "Maine Senate", "reason": "Review poll methods."}
    result = _parse(json.dumps(valid), title, excerpt)
    assert result["headline_only"] is False
    assert result["source_excerpt_reviewed"] is True
    assert result["evidence_source"] == "rss_excerpt"
    assert result["market_mapping"] == "pending"
    # A real headline quote still cannot stand in for evidence from the excerpt.
    for evidence in (title, "Candidate has withdrawn"):
        valid["evidence_quote"] = evidence
        with pytest.raises(TriageError, match="supplied RSS excerpt"):
            _parse(json.dumps(valid), title, excerpt)


def test_analysis_is_cached_and_counts_only_one_call(tmp_path, monkeypatch):
    monkeypatch.setenv("SIG_GEMINI_API_KEY", "test-key")
    path = tmp_path / "news.sqlite3"
    title = "New Maine Senate poll released"
    excerpt = "A Maine Senate poll surveyed 800 likely voters."
    news_id = hashlib.sha256(title.encode()).hexdigest()
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(path) as db:
        db.execute("""INSERT INTO news_items
            (id,topic,feed_id,publisher,title,content,title_key,url,published_at,discovered_at,day,priority)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (news_id, "elections", "test", "Publisher", title, excerpt, "mainesenatepoll",
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
    monkeypatch.setattr(sig_ai_triage, "_available_model", lambda key: pytest.fail("Cache must not probe a model"))
    second = analyze(news_id, path)
    assert first["cached"] is False
    assert second["cached"] is True
    assert len(calls) == 1
    assert excerpt in calls[0][1]["json"]["contents"][0]["parts"][0]["text"]
    assert status(path)["calls_today"] == 1
    assert results(path)[news_id]["evidence_source"] == "rss_excerpt"


def test_background_selects_only_unanalyzed_high_priority_election_excerpts(tmp_path, monkeypatch):
    monkeypatch.setenv("SIG_GEMINI_API_KEY", "test-key")
    path = tmp_path / "news.sqlite3"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(path) as db:
        sig_ai_triage._prepare(db)
        for topic, priority, title, content in [
                ("elections", 3, "New Maine Senate poll", "A new survey was published."),
                ("elections", 0, "General election commentary", "An opinion about politics."),
                ("markets", 5, "Stock earnings", "Quarterly financial results."),
                ("elections", 5, "Senate title without excerpt", ""),
                ("elections", 5, "Whitespace excerpt", "   "),
                ("elections", 5, "Previously analyzed poll", "A new survey was published.")]:
            news_id = hashlib.sha256(title.encode()).hexdigest()
            db.execute("""INSERT INTO news_items
                (id,topic,feed_id,publisher,title,content,title_key,url,published_at,discovered_at,day,priority)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (news_id, topic, "test", "Publisher", title, content, title.lower().replace(" ", ""),
                 "https://example.org/" + news_id, timestamp, timestamp, timestamp[:10], priority))
            if title == "Previously analyzed poll":
                cached = {"source_excerpt_reviewed": True, "evidence_source": "rss_excerpt",
                          "evidence_quote": "A new survey was published."}
                db.execute("INSERT INTO sig_triage_results VALUES(?,?,?,?)",
                           (news_id, "test-model", json.dumps(cached), timestamp))
    seen = []
    monkeypatch.setattr("app.sig_ai_triage.analyze", lambda news_id, path: seen.append(news_id))
    assert analyze_pending(path) == {"analyzed": 1, "failed": 0}
    assert seen == [hashlib.sha256(b"New Maine Senate poll").hexdigest()]


@pytest.mark.parametrize("excerpt", [None, "", "   "])
def test_parser_never_claims_excerpt_review_without_an_excerpt(excerpt):
    with pytest.raises(TriageError, match="no RSS excerpt") as error:
        _parse("{}", "A headline", excerpt)
    assert error.value.status_code == 422


def test_evidence_outside_the_sent_excerpt_is_rejected():
    model_result = {"relevance": "high", "event_type": "poll",
                    "evidence_quote": "800 likely voters"}
    with pytest.raises(TriageError, match="supplied RSS excerpt"):
        _parse(json.dumps(model_result), "Poll released", "x" * 1600 + "800 likely voters")


@pytest.mark.parametrize("content", ["", "   "])
def test_missing_excerpt_is_rejected_before_any_model_request(tmp_path, monkeypatch, content):
    monkeypatch.setenv("SIG_GEMINI_API_KEY", "test-key")
    path = tmp_path / "news.sqlite3"
    news_id = "a" * 64
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(path) as db:
        db.execute("""INSERT INTO news_items
            (id,topic,feed_id,publisher,title,content,title_key,url,published_at,discovered_at,day,priority)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (news_id, "elections", "test", "Publisher", "Senate poll", content, "senatepoll",
             "https://example.org/poll", timestamp, timestamp, timestamp[:10], 3))
    monkeypatch.setattr(sig_ai_triage, "_available_model", lambda key: pytest.fail("Missing excerpt must not probe a model"))
    with pytest.raises(TriageError) as error:
        analyze(news_id, path)
    assert error.value.status_code == 422
    with _connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM sig_triage_calls").fetchone()[0] == 0


def test_old_title_evidence_cache_is_hidden_and_selected_for_reanalysis(tmp_path, monkeypatch):
    monkeypatch.setenv("SIG_GEMINI_API_KEY", "test-key")
    path = tmp_path / "news.sqlite3"
    news_id = "b" * 64
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(path) as db:
        sig_ai_triage._prepare(db)
        db.execute("""INSERT INTO news_items
            (id,topic,feed_id,publisher,title,content,title_key,url,published_at,discovered_at,day,priority)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (news_id, "elections", "test", "Publisher", "Senate poll", "Surveyed 800 likely voters.",
             "senatepoll", "https://example.org/poll", timestamp, timestamp, timestamp[:10], 3))
        old = {"source_excerpt_reviewed": True, "headline_only": False, "evidence_quote": "Senate poll"}
        db.execute("INSERT INTO sig_triage_results VALUES(?,?,?,?)",
                   (news_id, "old-model", json.dumps(old), timestamp))
        db.execute("INSERT INTO sig_triage_calls VALUES(?,?,?,?)",
                   (news_id, timestamp[:10], timestamp, "ok"))
    assert results(path) == {}
    seen = []
    monkeypatch.setattr(sig_ai_triage, "analyze", lambda news_id, path: seen.append(news_id))
    assert analyze_pending(path) == {"analyzed": 1, "failed": 0}
    assert seen == [news_id]
