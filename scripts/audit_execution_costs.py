#!/usr/bin/env python3
"""Read-only Paper fill/fee evidence and historical quote matching. Private output."""
import argparse,json,sys
from pathlib import Path
import pandas as pd
import requests
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.broker.credentials import resolve_trading_credentials
from app.research.execution_cost_audit import audit_fills_against_quotes

def run(args):
    credentials=resolve_trading_credentials(dotenv_values(args.env_file))
    if credentials is None or not credentials.is_paper:raise ValueError('Paper-only audit')
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    session=requests.Session();session.headers.update({'APCA-API-KEY-ID':credentials.key,'APCA-API-SECRET-KEY':credentials.secret})
    def get(url,params):
        r=session.get(url,params=params,timeout=25)
        if r.status_code!=200:raise ValueError(f'Endpoint HTTP {r.status_code}')
        return r.json()
    start=pd.Timestamp(args.date,tz='America/New_York');until=min(start+pd.Timedelta(days=1),pd.Timestamp.now(tz='UTC'))
    activities=[];token=None;seen=set()
    while True:
        params=dict(after=start.isoformat(),until=until.isoformat(),direction='asc',page_size=100)
        if token:params['page_token']=token
        page=get(credentials.endpoint+'/v2/account/activities',params)
        activities.extend(page)
        if len(page)<100:break
        token=page[-1]['id']
        if token in seen:raise ValueError('Repeated activity page')
        seen.add(token)
    (output/'activities.json').write_text(json.dumps(activities,indent=2)+'\n')
    fills=[];quotes=[];errors=[]
    for a in activities:
        if a.get('activity_type')!='FILL':continue
        fill=dict(fill_id=a['id'],symbol=a['symbol'],side=a['side'],qty=float(a['qty']),price=float(a['price']),timestamp=a['transaction_time'])
        fills.append(fill);t=pd.Timestamp(fill['timestamp'])
        if t>pd.Timestamp.now(tz='UTC')-pd.Timedelta(minutes=15):
            errors.append(dict(fill_id=a['id'],reason='Historical SIP query must be 15 minutes old'));continue
        try:
            raw=get('https://data.alpaca.markets/v2/stocks/'+a['symbol']+'/quotes',dict(start=(t-pd.Timedelta(seconds=1)).isoformat(),end=t.isoformat(),feed='sip',sort='desc',limit=10000))
            for q in raw.get('quotes') or []:
                quotes.append(dict(symbol=a['symbol'],timestamp=q['t'],bid=q['bp'],ask=q['ap'],feed='sip'))
        except Exception as exc:errors.append(dict(fill_id=a['id'],reason=str(exc)))
    diagnostic=audit_fills_against_quotes(fills,quotes)
    fee_entries=[a for a in activities if a.get('activity_type') in {'FEE','CFEE'}]
    report=dict(date=args.date,account_type='paper',read_only=True,broker_mutations=0,
        coverage_start=start.isoformat(),coverage_end=until.isoformat(),activity_count=len(activities),
        observed_activity_types=sorted({a.get('activity_type','unknown') for a in activities}),
        observed_fee_entries=len(fee_entries),observed_fee_cash_amount=sum(float(a.get('net_amount') or 0) for a in fee_entries),
        all_actual_fees_verified=False,fee_interpretation='No observed FEE rows does not establish absence of later charges or fees posted under other activity types.',
        quote_errors=errors,execution_diagnostic=diagnostic)
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in {'execution_diagnostic','quote_errors'}},indent=2))
    print(json.dumps({k:v for k,v in diagnostic.items() if k!='rows'},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--env-file',required=True);p.add_argument('--date',required=True);p.add_argument('--output',required=True)
    run(p.parse_args())
