from datetime import datetime, timezone

from app.news_monitor import Feed, _take_lease, collect_once, list_items, parse_rss, source_status


RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>New Senate poll released</title><link>https://example.org/story?utm_source=rss</link>
<pubDate>Sun, 27 Sep 2026 16:00:00 GMT</pubDate><source>Original Publisher</source></item>
<item><title>Nvidia earnings update</title><link>https://example.org/nvidia</link>
<pubDate>Sun, 27 Sep 2026 16:30:00 GMT</pubDate><source>Market Publisher</source></item>
<item><title>Weekly interview transcript Sept 2026</title><link>https://example.org/transcript</link></item>
<item><title>Invalid URL</title><link>javascript:alert(1)</link></item>
</channel></rss>"""


def test_rss_records_are_safe_bounded_and_date_stamped():
    records = parse_rss(RSS, Feed("test", "elections", "Test", "https://example.org/rss"),
                        datetime(2026, 9, 27, 17, tzinfo=timezone.utc))
    assert len(records) == 1
    assert records[0]["url"] == "https://example.org/story"
    assert records[0]["published_at"] == "2026-09-27T16:00:00+00:00"
    assert records[0]["discovered_at"] == "2026-09-27T17:00:00+00:00"
    assert records[0]["priority"] >= 3


def test_collector_deduplicates_and_preserves_source_health(tmp_path):
    path = tmp_path / "news.sqlite3"

    def fetch(url):
        if url == "https://www.eac.gov/rss.xml":
            raise ValueError("upstream unavailable")
        return RSS

    first = collect_once(path, fetch)
    second = collect_once(path, fetch)
    assert first == {"inserted": 2, "failed_sources": 1}
    assert second == {"inserted": 0, "failed_sources": 1}
    assert len(list_items("elections", path=path)) == 1
    assert len(list_items("markets", path=path)) == 1
    assert source_status(path)[-1]["status"] == "error"


def test_poll_lease_prevents_duplicate_workers(tmp_path):
    path = tmp_path / "news.sqlite3"
    assert _take_lease(path)
    assert not _take_lease(path)
