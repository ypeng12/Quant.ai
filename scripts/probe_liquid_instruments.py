#!/usr/bin/env python3
"""Retain contemporary instrument metadata; never backdate listing eligibility."""
from pathlib import Path
import sys,json,argparse
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import yfinance as yf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.research.universe import LIQUID_US_IEX_30
from app.research.liquid_policy import EXTRA_STOCKS,RISK_REFERENCES,instrument_admission

def fetch(symbol):
    now=pd.Timestamp.now(tz='UTC').isoformat()
    try:
        info=yf.Ticker(symbol).get_info()
        record=dict(symbol=symbol,known_at=now,source='Yahoo Finance current instrument metadata',
            exchange=info.get('exchange'),quote_type=info.get('quoteType'),name=info.get('shortName'),market_cap=info.get('marketCap'),
            instrument_type='adr' if symbol=='TSM' else 'common_stock',leveraged=False,
            review='Explicit common-stock/ADR research panel; not inferred from ticker suffix',
            historical_membership_verified=False)
        record['admitted'],record['reason']=instrument_admission(record,pd.Timestamp.now(tz='UTC'))
        return symbol,record
    except Exception as exc:return symbol,dict(symbol=symbol,known_at=now,admitted=False,reason=str(exc),historical_membership_verified=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args();path=Path(args.output)
    if path.exists():raise ValueError('Exclusive metadata destination required')
    symbols=tuple(sorted(set((*LIQUID_US_IEX_30,*EXTRA_STOCKS))-set(RISK_REFERENCES)))
    with ThreadPoolExecutor(max_workers=4) as pool:records=dict(pool.map(fetch,symbols))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(dict(retrieved_at=pd.Timestamp.now(tz='UTC').isoformat(),records=records,
        limitation='Current security metadata does not prove historical membership. Historical replay uses an explicitly selected research panel.'),indent=2)+'\n')
    print(json.dumps({s:dict(admitted=r['admitted'],exchange=r.get('exchange'),reason=r['reason']) for s,r in records.items()},indent=2))

if __name__=='__main__':main()
