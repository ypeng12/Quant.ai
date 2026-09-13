#!/usr/bin/env python3
"""Offline actual-account PnL or fill TCA from explicitly supplied exports."""
import argparse
import json
from pathlib import Path
import sys
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.research.attribution import actual_account_reconciliation,fill_tca


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('account');a.add_argument('--snapshots',required=True);a.add_argument('--output',required=True)
    t=sub.add_parser('tca');t.add_argument('--fills',required=True);t.add_argument('--quotes',required=True);t.add_argument('--quote-tolerance',default='30s');t.add_argument('--output',required=True)
    args=p.parse_args();output=Path(args.output)
    if output.exists():raise ValueError('Choose a new output path to preserve prior evidence')
    if args.mode=='account':
        result=actual_account_reconciliation(pd.read_csv(args.snapshots))
        with output.open('x') as handle:json.dump(result,handle,indent=2,allow_nan=False)
    else:
        result=fill_tca(pd.read_csv(args.fills),pd.read_csv(args.quotes),tolerance=args.quote_tolerance)
        with output.open('x') as handle:result.to_csv(handle,index=False)
    print(output)
if __name__=='__main__':main()
