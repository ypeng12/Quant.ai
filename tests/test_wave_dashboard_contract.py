"""Classic wave views must retain dates and never substitute a prior session for today."""
import ast
import asyncio
import datetime
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.ml import lob_wave_realtime


def history_handler(cache):
    source = ROOT / 'backend/main_api.py'
    tree = ast.parse(source.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'get_wave_day_data')
    fn.decorator_list = []
    namespace = {'datetime': datetime, '_wave_history_cache': cache}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['get_wave_day_data']


def test_unavailable_today_never_falls_back_to_legacy_cache(monkeypatch):
    unavailable = {'success': False, 'status': 'unavailable'}
    monkeypatch.setattr(lob_wave_realtime, 'compute_live_wave_day_data', lambda _: unavailable)
    handler = history_handler({'TSLA': {'by_day': {'today': {'signals': ['old']}}, 'days': []}})
    assert asyncio.run(handler('TSLA', 'today')) == unavailable


def test_history_response_identifies_proxy_and_never_substitutes_current_data(monkeypatch):
    def forbidden(_):
        raise AssertionError('Historical lookup must not invoke live market fetch')
    monkeypatch.setattr(lob_wave_realtime, 'compute_live_wave_day_data', forbidden)
    handler = history_handler({'TSLA': {'by_day': {'2026-08-31': {'signals': []}}, 'days': ['2026-08-31']}})
    assert asyncio.run(handler('TSLA', '2026-08-31'))['status'] == 'historical_proxy'
    assert not asyncio.run(handler('TSLA', '2026-08-30'))['success']


def test_current_wave_view_uses_completed_bars_and_names_ohlcv(monkeypatch):
    index = pd.date_range('2026-09-11 09:30', periods=7, freq='min', tz='America/New_York')
    bars = pd.DataFrame({c: 100.0 for c in ['Open', 'High', 'Low', 'Close', 'Volume']}, index=index)
    monkeypatch.setattr(lob_wave_realtime, 'fetch_today_bars', lambda _: bars)
    result = lob_wave_realtime.compute_live_wave_day_data('TSLA',now=pd.Timestamp('2026-09-11T09:37:00-04:00'))
    assert result['success'] and result['is_today']
    assert result['data']['times']==['09:30']
    assert result['data_provenance']['feature_source']=='ohlcv_derived'
    assert 'market_depth' not in result['data_provenance']
    old = lob_wave_realtime.compute_live_wave_day_data('TSLA',now=pd.Timestamp('2026-09-14T09:37:00-04:00'))
    assert not old['success'] and 'data' not in old
