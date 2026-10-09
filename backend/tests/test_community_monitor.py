from datetime import datetime, timezone

from app.community_monitor import parse_posts, snapshot


def test_public_posts_are_cleaned_and_bounded(tmp_path):
    now = datetime(2026, 9, 27, 18, tzinfo=timezone.utc)
    payload = {"code": 0, "data": [
        {"id": "12345", "title": "<p>NVDA may rise</p>", "desc": "<b>Because of earnings</b>", "publish_time": "1790530000"},
        {"id": "bad-id", "title": "Skip", "desc": "Invalid post", "publish_time": "1790530000"},
    ]}
    posts = parse_posts(payload, "NVDA", now)
    assert len(posts) == 1
    assert posts[0]["title"] == "NVDA may rise"
    assert posts[0]["excerpt"] == "Because of earnings"
    assert snapshot("NVDA", path=tmp_path / "community.sqlite3")["contrarian_signal"] is None
