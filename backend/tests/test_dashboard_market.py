import json
from pathlib import Path

import pytest

from app.ml.dashboard_market import archived_fills, market_data, observed_snapshot


def test_complete_session_is_resampled_without_changing_closes():
    one = market_data('NVDA', '2026-09-11', '1m')
    five = market_data('NVDA', '2026-09-11', '5m')
    assert len(one['time']) == 390
    assert len(five['time']) == 78
    assert five['time'][0] == '09:30' and five['time'][-1] == '15:55'
    assert five['close'][-1] == one['close'][-1]
    assert five['data_provenance']['last_bar_end'][11:16] == '16:00'


def test_requested_missing_day_never_falls_back_to_another_session():
    with pytest.raises(ValueError, match='unavailable'):
        market_data('TSLA', '2026-09-12', '5m')


def test_snapshot_has_observations_but_no_invented_model_result():
    result = observed_snapshot('SNDK')
    assert result['status'] == 'market_data_only'
    assert result['result'] is None
    assert result['observed']['bar_count'] == 78
    assert 'feature_importance' in result['unavailable_metrics']


def test_archived_fills_only_expose_confirmed_fill_facts(tmp_path):
    archive = tmp_path / 'backend/data/datasets/daily_archives'
    archive.mkdir(parents=True)
    (archive / 'trades_2026-09-11.json').write_text(json.dumps({'trade_history': [
        {'ticker': 'TSLA', 'time': '2026-09-11 09:32:26', 'action': 'BUY', 'shares': 2,
         'price': 364.25, 'pnl': 999999, 'order_status': 'filled', 'source': 'alpaca_trading_api'},
        {'ticker': 'TSLA', 'time': '2026-09-11 09:35:00', 'action': 'SELL', 'shares': 2,
         'price': 365.00, 'order_status': 'new'}
    ]}))
    result = archived_fills('TSLA', '2026-09-11', tmp_path)
    assert result['fills'] == [{'time': '2026-09-11 09:32:26', 'action': 'BUY', 'shares': 2.0,
                                'price': 364.25, 'source': 'alpaca_trading_api'}]
    assert result['data_provenance']['pnl_verified'] is False
