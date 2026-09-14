"""Refresh bounded historical dashboard bars; no broker trading calls."""
from pathlib import Path
import hashlib,json,os,sys,time
import pandas as pd
import requests
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]

def refresh(start='2026-08-31T00:00:00Z',end='2026-09-12T00:00:00Z'):
    values={**dotenv_values(ROOT/'backend/.env'),**os.environ}
    headers={'APCA-API-KEY-ID':values['ALPACA_API_KEY'],'APCA-API-SECRET-KEY':values['ALPACA_SECRET_KEY']}
    symbols=['TSLA','NVDA','SNDK','PLTR','AAPL','AMD','MSFT','MU']
    all_rows={s:[] for s in symbols};token=None;seen=set()
    with requests.Session() as client:
        while True:
            params=dict(symbols=','.join(symbols),start=start,end=end,timeframe='1Min',feed='sip',adjustment='raw',limit=10000,sort='asc')
            if token:params['page_token']=token
            response=client.get('https://data.alpaca.markets/v2/stocks/bars',headers=headers,params=params,timeout=30)
            if response.status_code!=200:raise RuntimeError(f'Historical SIP request returned HTTP {response.status_code}')
            payload=response.json()
            for s,rows in payload.get('bars',{}).items():all_rows[s].extend(rows)
            token=payload.get('next_page_token')
            if not token:break
            if token in seen:raise RuntimeError('Repeated page token')
            seen.add(token);time.sleep(.35)
    data={};manifest=dict(source='alpaca_historical_sip',adjustment='raw',start=start,end=end,downloaded_at=pd.Timestamp.now(tz='UTC').isoformat(),symbols={})
    for symbol,rows in all_rows.items():
        frame=pd.DataFrame(rows)
        if frame.empty:raise RuntimeError(f'No historical rows for {symbol}')
        frame.index=pd.to_datetime(frame.pop('t'),utc=True).dt.tz_convert('America/New_York')
        if frame.index.has_duplicates:raise RuntimeError(f'Duplicate timestamps for {symbol}')
        frame=frame.sort_index().between_time('09:30','15:59')
        data[symbol]={}
        for day,group in frame.groupby(frame.index.strftime('%Y-%m-%d')):
            data[symbol][day]=[dict(t=i.isoformat(),o=float(r.o),h=float(r.h),l=float(r.l),c=float(r.c),v=float(r.v)) for i,r in group.iterrows()]
        manifest['symbols'][symbol]={day:len(rows) for day,rows in data[symbol].items()}
    output=ROOT/'backend/data/market_history/dashboard_bars.json';output.parent.mkdir(parents=True,exist_ok=True)
    content=json.dumps(dict(manifest=manifest,bars=data),separators=(',',':'))+'\n'
    temp=output.with_suffix('.tmp');temp.write_text(content);temp.replace(output)
    print('Saved historical SIP dashboard bars:',sum(sum(v.values()) for v in manifest['symbols'].values()),'one-minute rows')
    print('Latest date counts:',{s:manifest['symbols'][s].get('2026-09-11') for s in symbols})

if __name__=='__main__':refresh()
