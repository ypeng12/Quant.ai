#!/usr/bin/env python3
"""Offline consistency checks of the bounded Financial Sentiment Using Prices data acquisition experiment."""
import hashlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'reports/market_impact_data_audit_20261007'
A = BASE / 'alpaca'


def read(path):
    return json.loads(path.read_text())


def main():
    summary = read(A / 'summary.json')
    articles = read(A / 'news_normalized.json')
    byid = {x['id']: x for x in articles}
    raw = [a for p in sorted(A.glob('news_recent_[0-9]*.json')) for a in read(p)['news']]
    assert len(raw) == summary['news']['raw_count']
    assert len({str(x['id']) for x in raw}) == len(byid) == summary['news']['unique_ids']
    assert all(x['historical_availability_verified'] is False for x in articles)
    labels = read(A / 'exploratory_labels.json')
    assert len({(x['event_id'], x['symbol']) for x in labels}) == len(labels)
    assert len(labels) == sum(len(set(x['symbols']) & {'NVDA','TSLA','PLTR','SNDK'}) for x in articles)
    bars = {}
    for symbol in summary['bars']:
        rows = [r for p in sorted(A.glob(f'bars_{symbol}_[0-9]*.json')) for r in read(p)['bars'][symbol]]
        bars[symbol] = {pd.Timestamp(r['t']): r for r in rows}
        assert len(rows) == len(bars[symbol]), 'Duplicate bar timestamps'
        assert len(rows) == summary['bars'][symbol]['all_bars']
    good = [x for x in labels if x['status'] == 'exploratory_label_available']
    for row in good:
        start, end = pd.Timestamp(row['entry_at']), pd.Timestamp(row['exit_at'])
        item = byid[row['event_id']]
        assert start >= max(pd.Timestamp(item['created_at']), pd.Timestamp(item['updated_at'])) + pd.Timedelta(seconds=60)
        assert end-start == pd.Timedelta(minutes=60)
        local = start.tz_convert('America/New_York')
        endlocal = end.tz_convert('America/New_York')
        assert local.date() == endlocal.date() and local.strftime('%H:%M') >= '09:30'
        assert endlocal.strftime('%H:%M') <= '15:55'
        s = row['symbol']
        sr = bars[s][end]['o']/bars[s][start]['o']-1
        mr = bars['SPY'][end]['o']/bars['SPY'][start]['o']-1
        assert abs(sr-row['stock_return']) < 1e-12
        assert abs(mr-row['spy_return']) < 1e-12
        assert abs(sr-mr-row['excess_return']) < 1e-12
    statuses = Counter(x['status'] for x in labels)
    assert dict(statuses) == summary['label_status_counts']
    for filename, expected in read(A / 'hashes.json').items():
        assert hashlib.sha256((A / filename).read_bytes()).hexdigest() == expected, filename
    good_ids = {x['event_id'] for x in good}
    output = {
        'status': 'passed', 'checks': ['raw news counts', 'unique article-stock rows', 'no historical arrival claim',
            'bar uniqueness', 'entry after assumed availability plus delay', 'same-day 60min label within 15:55',
            'raw price return recomputation', 'saved hashes'],
        'article_stock_rows': len(labels), 'valid_exploratory_label_rows':len(good),
        'valid_label_unique_articles':len(good_ids),
        'valid_label_rows_with_body':sum(bool(byid[x['event_id']]['text']) for x in good),
        'valid_label_articles_with_body':sum(bool(byid[i]['text']) for i in good_ids),
        'all_bars':sum(len(x) for x in bars.values()),
        'rth_bars':sum(x['rth_bars'] for x in summary['bars'].values()),
        'label_rows_by_date':dict(Counter(pd.Timestamp(x['entry_at']).tz_convert('America/New_York').date().isoformat() for x in good)),
        'article_counts_by_publication_date':dict(Counter(pd.Timestamp(x['created_at']).tz_convert('America/New_York').date().isoformat() for x in articles)),
        'scope':'Internal consistency only, not source completeness, independent events, real-time backtest or predictive validity.'}
    (BASE / 'validation.json').write_text(json.dumps(output, indent=2)+'\n')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
