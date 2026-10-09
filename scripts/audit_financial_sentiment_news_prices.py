#!/usr/bin/env python3
"""Bounded read-only news/price feasibility audit; never imports a trading runner."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.market_data.history import credentials

OUT = ROOT / 'reports/market_impact_data_audit_20261007/alpaca'
STOCKS = ['NVDA', 'TSLA', 'PLTR', 'SNDK']
SYMBOLS = STOCKS + ['SPY', 'QQQ', 'SOXX']
START, END = '2026-09-30T04:00:00Z', '2026-10-07T04:00:00Z'
REQUESTS = []


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def clean(text):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', text or ''))).strip()


def stamp(value):
    try:
        result = pd.Timestamp(value)
        return result.tz_convert('UTC') if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def request(session, name, route, params):
    before = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    try:
        response = session.get('https://data.alpaca.markets' + route, params=params, timeout=30)
        try:
            payload = response.json()
        except ValueError:
            payload = {'non_json_response': response.text[:250]}
        status = response.status_code
    except requests.RequestException as exc:
        payload, status = {'error_type': type(exc).__name__}, None
    save(name + '.json', payload)
    REQUESTS.append({'file': name + '.json', 'route': route, 'params': params,
                     'observed_at': before, 'http_status': status,
                     'elapsed_seconds': round(time.monotonic() - t0, 3)})
    save('requests.json', REQUESTS)
    print(name, status, flush=True)
    time.sleep(.25)
    return payload if status == 200 else None


def news(session, prefix, start, end, max_pages):
    records, token, complete = [], None, False
    seen = set()
    for page in range(max_pages):
        params = dict(symbols=','.join(STOCKS), start=start, end=end, sort='asc',
                      limit=50, include_content='true', exclude_contentless='false')
        if token:
            params['page_token'] = token
        payload = request(session, f'{prefix}_{page:03d}', '/v1beta1/news', params)
        if payload is None:
            break
        records.extend(payload.get('news', []))
        token = payload.get('next_page_token')
        if not token:
            complete = True
            break
        if token in seen:
            break
        seen.add(token)
    return records, complete


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT)
    OUT = parser.parse_args().output.resolve()
    if OUT.exists() and any(OUT.iterdir()):
        raise SystemExit('Audit already exists; use a new --output directory.')
    OUT.mkdir(parents=True, exist_ok=True)
    key, secret = credentials()
    session = requests.Session()
    session.headers.update({'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret})
    raw, complete = news(session, 'news_recent', START, END, 40)
    older, older_complete = news(session, 'news_older_probe', '2025-10-01T04:00:00Z', '2025-10-08T04:00:00Z', 1)
    unique = {str(x['id']): x for x in raw}
    normalized = []
    for ident, item in unique.items():
        body, headline = clean(item.get('content')), clean(item.get('headline'))
        normalized.append({'id': ident, 'headline': headline, 'text': body,
                           'summary': clean(item.get('summary')), 'symbols': item.get('symbols', []),
                           'created_at': item.get('created_at'), 'updated_at': item.get('updated_at'),
                           'url': item.get('url'), 'source': item.get('source'),
                           'content_sha256': hashlib.sha256(body.encode()).hexdigest(),
                           'text_words': len(body.split()), 'historical_availability_verified': False})
    save('news_normalized.json', normalized)
    prices = {s: {} for s in SYMBOLS}
    bar_complete = {}
    for symbol in SYMBOLS:
        token = None
        for page in range(5):
            params = dict(symbols=symbol, start=START, end=END, timeframe='5Min', feed='sip',
                          adjustment='raw', limit=10000, sort='asc', asof='-')
            if token:
                params['page_token'] = token
            payload = request(session, f'bars_{symbol}_{page:03d}', '/v2/stocks/bars', params)
            if payload is None:
                bar_complete[symbol] = False
                break
            for row in (payload.get('bars') or {}).get(symbol, []):
                prices[symbol][stamp(row['t'])] = row
            token = payload.get('next_page_token')
            if not token:
                bar_complete[symbol] = True
                break
        else:
            bar_complete[symbol] = False
    # One bounded current-time query: success alone does not prove transport latency.
    now = pd.Timestamp.now(tz='UTC')
    request(session, 'news_recent_access_probe', '/v1beta1/news',
            dict(symbols=','.join(STOCKS), start=(now-pd.Timedelta(minutes=10)).isoformat(),
                 end=now.isoformat(), limit=5, include_content='false'))
    request(session, 'latest_sip_quote_probe', '/v2/stocks/quotes/latest', dict(symbols='NVDA', feed='sip'))
    calendar = xcals.get_calendar('XNYS')
    sessions = calendar.sessions_in_range('2026-09-30', '2026-10-06')
    day_ranges, expected = {}, set()
    for d in sessions:
        op, cl = calendar.session_open(d), calendar.session_close(d)
        day_ranges[str(d.date())] = (op, cl)
        expected.update(pd.date_range(op, cl-pd.Timedelta(minutes=5), freq='5min'))
    counts = {}
    for symbol, rows in prices.items():
        present = expected & rows.keys()
        counts[symbol] = {'all_bars': len(rows), 'rth_bars': len(present), 'expected_rth': len(expected),
                          'missing_rth': len(expected-present), 'pagination_complete': bar_complete.get(symbol),
                          'rth_volume': sum(rows[t]['v'] for t in present)}
    labels = []
    # Historical final text is only assigned an exploratory availability assumption.
    for item in normalized:
        created, updated = stamp(item['created_at']), stamp(item['updated_at'])
        for symbol in set(item['symbols']) & set(STOCKS):
            row = {'event_id': item['id'], 'symbol': symbol,
                   'historical_availability_verified': False,
                   'assumption': 'max(created_at,updated_at)+60sec then next 5min open; final historical text',
                   'status': 'invalid_timestamp'}
            if created is not None and updated is not None:
                available = max(created, updated)
                day = str(available.tz_convert('America/New_York').date())
                row['assumed_available_at'] = available.isoformat()
                if day not in day_ranges:
                    row['status'] = 'outside_audited_sessions'
                else:
                    op, cl = day_ranges[day]
                    if not op <= available < cl:
                        row['status'] = 'outside_regular_hours'
                    else:
                        entry = (available + pd.Timedelta(seconds=60)).ceil('5min')
                        end = entry + pd.Timedelta(minutes=60)
                        row.update(entry_at=entry.isoformat(), exit_at=end.isoformat())
                        if end > cl-pd.Timedelta(minutes=5):
                            row['status'] = 'past_1555_flattening'
                        elif any(t not in prices[s] for s in [symbol,'SPY'] for t in [entry,end]):
                            row['status'] = 'missing_price'
                        else:
                            stock = prices[symbol][end]['o']/prices[symbol][entry]['o']-1
                            market = prices['SPY'][end]['o']/prices['SPY'][entry]['o']-1
                            row.update(status='exploratory_label_available', stock_return=stock,
                                       spy_return=market, excess_return=stock-market)
            labels.append(row)
    save('exploratory_labels.json', labels)
    content_lengths = [x['text_words'] for x in normalized]
    valid_created = [stamp(x['created_at']) for x in normalized if stamp(x['created_at']) is not None]
    revised = [x for x in normalized if stamp(x['created_at']) and stamp(x['updated_at']) and
               stamp(x['updated_at']) > stamp(x['created_at'])]
    summary = {'audit_completed_at': datetime.now(timezone.utc).isoformat(), 'start': START, 'end': END,
               'sessions': list(day_ranges), 'request_count': len(REQUESTS),
               'http_status_counts': dict(Counter(str(x['http_status']) for x in REQUESTS)),
               'news': {'raw_count': len(raw), 'unique_ids': len(unique), 'pagination_complete': complete,
                        'min_created_at': min(valid_created).isoformat() if valid_created else None,
                        'max_created_at': max(valid_created).isoformat() if valid_created else None,
                        'with_body': sum(bool(x['text']) for x in normalized),
                        'median_body_words': statistics.median(content_lengths) if content_lengths else None,
                        'body_under_50_words': sum(v < 50 for v in content_lengths),
                        'revised_after_created': len(revised),
                        'multi_symbol_articles': sum(len(x['symbols']) > 1 for x in normalized),
                        'per_stock_mentions': {s: sum(s in x['symbols'] for x in normalized) for s in STOCKS},
                        'sources': dict(Counter(str(x['source']) for x in normalized)),
                        'duplicate_headlines': len(normalized)-len(set(x['headline'] for x in normalized)),
                        'actual_event_cluster_count': None},
               'older_probe': {'count':len(older), 'pagination_complete':older_complete,
                               'scope':'One page only; tests access, not year-long coverage'},
               'bars': counts, 'label_status_counts': dict(Counter(x['status'] for x in labels)),
               'labels_per_stock': {s:dict(Counter(x['status'] for x in labels if x['symbol']==s)) for s in STOCKS},
               'limits': ['No real-time arrival history', 'No deduplicated event clusters or model training',
                          'Exploratory labels are not predictions or trading returns',
                          'No account/trading endpoints called; no paid service purchased']}
    save('summary.json', summary)
    hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.json')}
    save('hashes.json', hashes)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
