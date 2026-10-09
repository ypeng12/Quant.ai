"""Regression checks that never import the API module or start its trading runner."""

import ast
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import sig_ai_triage
from app.broker.fill_accounting import ACCOUNTING
from app.news_monitor import _connect


def test_legacy_headline_cache_can_be_replaced_with_excerpt_analysis(tmp_path, monkeypatch):
    path = tmp_path / 'news.sqlite3'
    news_id = 'a' * 64
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    day = now[:10]
    monkeypatch.setenv('SIG_GEMINI_API_KEY', 'unit-test-key')
    with _connect(path) as db:
        sig_ai_triage._prepare(db)
        db.execute("""INSERT INTO news_items
            (id,topic,feed_id,publisher,title,content,title_key,url,published_at,discovered_at,day,priority)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (news_id, 'elections', 'test', 'Test publisher', 'Senate poll shows a close race',
             'A new poll reports a close Senate race.', 'senatepoll', 'https://example.com/poll',
             now, now, day, 5))
        db.execute('INSERT INTO sig_triage_results VALUES(?,?,?,?)',
                   (news_id, 'old-model', json.dumps({'headline_only': True}), now))
        db.execute('INSERT INTO sig_triage_calls VALUES(?,?,?,?)', (news_id, day, now, 'ok'))

    calls = []
    model_result = dict(relevance='high', event_type='poll', summary='The Senate race is close.',
                        evidence_quote='a close Senate race', race_hint='Senate', reason='Check poll methodology.')

    def post(*args, **kwargs):
        calls.append(kwargs['json'])
        return SimpleNamespace(status_code=200, json=lambda: {
            'candidates': [{'content': {'parts': [{'text': json.dumps(model_result)}]}}]
        })

    result = sig_ai_triage.analyze(news_id, path=path, post=post)
    assert result['source_excerpt_reviewed'] is True and result['cached'] is False
    assert 'A new poll reports a close Senate race.' in calls[0]['contents'][0]['parts'][0]['text']
    assert sig_ai_triage.analyze(news_id, path=path, post=post)['cached'] is True
    assert len(calls) == 1
    with _connect(path) as db:
        row = db.execute('SELECT status FROM sig_triage_calls WHERE news_id=? AND day=?',
                         (news_id, day)).fetchone()
        assert row['status'] == 'ok'


def _trade_history_endpoint(tmp_path, monkeypatch):
    # Importing main_api constructs LiveTradingRunner. Compile only this handler
    # so file-read behavior is tested without executing application startup.
    source = Path(__file__).resolve().parents[1] / 'main_api.py'
    tree = ast.parse(source.read_text())
    handler = next(node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == 'get_trade_history')
    handler.decorator_list = []
    namespace = {'os': os, 'json': json, '__file__': str(tmp_path / 'main_api.py')}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), 'exec'), namespace)
    monkeypatch.setattr(ACCOUNTING, 'snapshot', lambda: (None, 'credentials_unavailable'))
    return namespace['get_trade_history']


@pytest.mark.parametrize('content, expected_count', [
    (None, 0),
    ('{"trade_history": [', 0),
    (json.dumps({'trade_history': [{'order_id': 'legacy', 'pnl': 12}]}), 1),
])
def test_trade_history_handles_missing_partial_and_valid_files(tmp_path, monkeypatch, content, expected_count):
    if content is not None:
        (tmp_path / 'trade_history.json').write_text(content)
    response = _trade_history_endpoint(tmp_path, monkeypatch)()
    assert len(response['trade_history']) == expected_count
    assert all(row['pnl'] is None for row in response['trade_history'])


def test_trade_history_handles_file_read_error(tmp_path, monkeypatch):
    (tmp_path / 'trade_history.json').write_text('{}')
    handler = _trade_history_endpoint(tmp_path, monkeypatch)
    with monkeypatch.context() as patch:
        def unavailable(*args, **kwargs):
            raise PermissionError('test file is temporarily unavailable')
        patch.setattr('builtins.open', unavailable)
        response = handler()
    assert response['trade_history'] == []
