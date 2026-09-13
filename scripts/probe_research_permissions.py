#!/usr/bin/env python3
"""Read-only free-history entitlement probe; stores no credentials or raw account data."""
import argparse
import json
from pathlib import Path
import sys
import pandas as pd
import requests
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.market_data.history import credentials,validate_symbol


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--symbol',default='SPY');p.add_argument('--output',required=True)
    args=p.parse_args();symbol=validate_symbol(args.symbol);now=pd.Timestamp.now(tz='UTC')
    result=dict(checked_at=now.isoformat(),symbol=symbol,credentials_present=False,checks=[])
    try:key,secret=credentials()
    except ValueError:pass
    else:
        result['credentials_present']=True
        end=now-pd.Timedelta(minutes=16);start=end-pd.Timedelta(days=4)
        with requests.Session() as session:
            session.headers.update({'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret})
            for feed in ('iex','sip'):
                for kind in ('quotes','trades','bars'):
                    params=dict(symbols=symbol,start=start.isoformat(),end=end.isoformat(),feed=feed,limit=1)
                    if kind=='bars':params.update(timeframe='5Min',adjustment='raw')
                    check=dict(feed=feed,kind=kind,start=start.isoformat(),end=end.isoformat())
                    try:
                        response=session.get('https://data.alpaca.markets/v2/stocks/'+kind,params=params,timeout=20)
                        check.update(http_status=response.status_code,authorized=response.status_code==200)
                        if response.status_code==200:check['sample_rows']=len((response.json().get(kind) or {}).get(symbol,[]))
                    except requests.RequestException as exc:check.update(authorized=None,error_type=type(exc).__name__)
                    result['checks'].append(check)
    with Path(args.output).open('x') as handle:json.dump(result,handle,indent=2)
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
