#!/usr/bin/env python3
"""Retain explicitly sourced free Yahoo bars, independently of broker configuration."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import pandas as pd
import yfinance as yf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.research.universe import LIQUID_US_IEX_30
from app.quant_policy import normalize_bars
from app.market_data.history import validate_symbol


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--universe30',action='store_true');g.add_argument('--symbols',nargs='+')
    p.add_argument('--start',required=True);p.add_argument('--end',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();root=Path(args.output);root.mkdir(parents=True,exist_ok=False)
    symbols=LIQUID_US_IEX_30 if args.universe30 else [validate_symbol(s) for s in args.symbols]
    manifest={};status=dict(status='running',requested_symbols=list(symbols),failures={},yfinance_version=yf.__version__,downloaded_at=pd.Timestamp.now(tz='UTC').isoformat())
    for symbol in symbols:
        try:
            f=yf.download(symbol,start=args.start,end=args.end,interval='5m',auto_adjust=False,actions=True,progress=False,threads=False,timeout=20)
            if f.empty:raise ValueError('Empty Yahoo response')
            if isinstance(f.columns,pd.MultiIndex):f=f.xs(symbol,axis=1,level='Ticker')
            # Keep corporate-action columns in raw file and explicitly audit them.
            raw_rows=len(f);events={c:f.loc[f[c]!=0,c].to_dict() for c in ['Dividends','Stock Splits'] if c in f}
            event_records={c:{str(t):float(v) for t,v in values.items()} for c,values in events.items()}
            normalized=normalize_bars(f)
            f=f.loc[normalized.index]
            path=root/f'{symbol}.parquet';f.to_parquet(path)
            manifest[symbol]=dict(source='Yahoo Finance via yfinance direct historical request',requested_start=args.start,requested_end_exclusive=args.end,
                                  interval='5m',auto_adjust=False,raw_rows=raw_rows,regular_rows=len(f),first=str(f.index[0]),last=str(f.index[-1]),
                                  sha256=hashlib.sha256(path.read_bytes()).hexdigest(),corporate_actions=event_records,
                                  sessions={str(d):int(n) for d,n in f.groupby(f.index.date).size().items()})
            print(symbol,len(f),flush=True)
        except Exception as exc:
            status['failures'][symbol]=type(exc).__name__+': '+str(exc);print(symbol,'unavailable',flush=True)
        (root/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
        (root/'download_status.json').write_text(json.dumps(status,indent=2,allow_nan=False)+'\n')
    status['status']='complete' if not status['failures'] else 'incomplete'
    (root/'download_status.json').write_text(json.dumps(status,indent=2,allow_nan=False)+'\n')
    print(status['status'],flush=True)
if __name__=='__main__':main()
