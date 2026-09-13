"""Read-only, paginated Alpaca history; no config/broker imports or paid upgrades."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import time
import pandas as pd
import requests
from dotenv import dotenv_values


def credentials():
    env = dotenv_values(Path(__file__).resolve().parents[2] / '.env')
    key = os.getenv('ALPACA_API_KEY') or env.get('ALPACA_API_KEY')
    secret = os.getenv('ALPACA_SECRET_KEY') or os.getenv('ALPACA_API_SECRET') or env.get('ALPACA_SECRET_KEY') or env.get('ALPACA_API_SECRET')
    if not key or not secret:
        raise ValueError('Alpaca credentials unavailable; configure backend/.env locally')
    return key, secret


def validate_symbol(symbol):
    symbol = str(symbol).strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', symbol):
        raise ValueError('Invalid stock symbol')
    return symbol


def download_history(symbols, start, end, feed, kind, output, *, max_pages=0):
    symbols=[validate_symbol(s) for s in symbols]
    if not symbols or len(symbols)!=len(set(symbols)) or max_pages<0:
        raise ValueError('Distinct nonempty symbols and nonnegative page budget required')
    if feed not in ('iex', 'sip') or kind not in ('quotes', 'trades', 'bars'):
        raise ValueError('Explicit stock feed and data kind required')
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError('Timezone-aware start < end required')
    if end > pd.Timestamp.now(tz='UTC') - pd.Timedelta(minutes=15):
        raise ValueError('Historical free workflow requires end at least 15 minutes old')
    key, secret = credentials()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = dict(status='running', source='alpaca_stock_historical', feed=feed, kind=kind,
                    start=start.isoformat(), end=end.isoformat(), symbols=[validate_symbol(s) for s in symbols],
                    files=[], symbol_stats={})
    def save(): (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    save()
    try:
        with requests.Session() as session:
            session.headers.update({'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret})
            for symbol in manifest['symbols']:
                token, pages, bar_records, seen_tokens = None, 0, [], set()
                event_count, first_timestamp, last_timestamp = 0, None, None
                while True:
                    params = dict(symbols=symbol, start=start.isoformat(), end=end.isoformat(), feed=feed, limit=10000, sort='asc')
                    if kind=='bars': params.update(timeframe='5Min', adjustment='raw')
                    if token: params['page_token']=token
                    response = session.get('https://data.alpaca.markets/v2/stocks/'+kind,params=params,timeout=30)
                    if response.status_code!=200:
                        raise ValueError(f'Historical endpoint HTTP {response.status_code}; no feed substitution')
                    payload=response.json(); pages+=1
                    if kind not in payload:raise ValueError('Historical response is missing the requested data field')
                    page_records=(payload.get(kind) or {}).get(symbol,[])
                    raw=output/f'{symbol}_{pages:06d}.json'; raw.write_text(json.dumps(payload,separators=(',',':'))+'\n')
                    manifest['files'].append(dict(path=raw.name,sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                                                  symbol=symbol,records=len(page_records)))
                    if page_records:
                        event_count += len(page_records)
                        first_timestamp = first_timestamp or page_records[0].get('t')
                        last_timestamp = page_records[-1].get('t')
                    if kind=='bars':
                        bar_records.extend(page_records)
                    else:
                        event_type='quote' if kind=='quotes' else 'trade'
                        handles = {}
                        try:
                            for raw_event in page_records:
                                event=dict(schema_version=1,source='alpaca_stock_historical',feed=feed,symbol=symbol,event_type=event_type,
                                           timestamp=raw_event['t'],downloaded_at=pd.Timestamp.now(tz='UTC').isoformat(),conditions=raw_event.get('c'),tape=raw_event.get('z'))
                                if kind=='quotes':
                                    event.update(market_depth='L1',quote_size_unit='round_lots',bid_price=raw_event['bp'],ask_price=raw_event['ap'],bid_size=raw_event['bs'],ask_size=raw_event['as'],bid_exchange=raw_event.get('bx'),ask_exchange=raw_event.get('ax'))
                                else:
                                    event.update(market_depth='trade_print',price=raw_event['p'],size=raw_event['s'],trade_size_unit='shares',trade_id=raw_event.get('i'),exchange=raw_event.get('x'))
                                day=str(pd.Timestamp(event['timestamp']).tz_convert('America/New_York').date())
                                path=output/day/f'{symbol}.jsonl'; path.parent.mkdir(exist_ok=True)
                                handle=handles.get(path)
                                if handle is None:
                                    handle=path.open('a')
                                    handles[path]=handle
                                handle.write(json.dumps(event,separators=(',',':'))+'\n')
                        finally:
                            for handle in handles.values():
                                handle.close()
                    token=payload.get('next_page_token')
                    if not token: break
                    if token in seen_tokens:raise ValueError('Historical endpoint repeated a page token')
                    seen_tokens.add(token)
                    if max_pages and pages>=max_pages:
                        raise ValueError('Page budget reached; capture incomplete and cannot be used as a complete interval')
                    time.sleep(.35)
                if bar_records:
                    frame=pd.DataFrame(bar_records).rename(columns={'t':'timestamp','o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'})
                    frame.index=pd.to_datetime(frame.pop('timestamp'),utc=True).dt.tz_convert('America/New_York')
                    frame.to_parquet(output/f'{symbol}.parquet')
                manifest['symbol_stats'][symbol]=dict(pages=pages,records=event_count,
                                                      first_timestamp=first_timestamp,last_timestamp=last_timestamp)
                save()
                time.sleep(.35)
        manifest['normalized_files'] = [dict(path=str(p.relative_to(output)),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                                        for p in sorted(output.rglob('*')) if p.suffix in ('.jsonl','.parquet')]
        manifest['status']='complete'
    except Exception as exc:
        manifest.update(status='incomplete',error_type=type(exc).__name__)
        raise
    finally: save()
    return manifest
