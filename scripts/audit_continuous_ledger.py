#!/usr/bin/env python3
"""Reproduce period-wide FIFO from a hash-checked local daily archive audit."""
import argparse
import hashlib
import json
from pathlib import Path
from audit_trade_ledger import audit_fills,write_csv

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--daily-audit',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();audit=json.loads(Path(args.daily_audit).read_text());fills=[]
    for source in audit['sources']:
        raw=Path(source['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=source['sha256']:raise ValueError('Source archive checksum changed')
        fills.extend(json.loads(raw)['trade_history'])
    symbols=sorted({row['ticker'] for row in audit['daily']});results={};matches=[]
    for symbol in symbols:
        results[symbol],rows=audit_fills([row for row in fills if row['ticker']==symbol]);matches.extend(rows)
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    write_csv(output/'continuous_period_matches.csv',matches)
    payload=dict(source_type='local order mirrors; unverified completeness and opening inventory',
        method='FIFO across the entire nine-session period without daily inventory reset',symbols=results,sources=audit['sources'],
        fees_verified=False,account_equity_verified=False)
    (output/'continuous_period_audit.json').write_text(json.dumps(payload,indent=2)+'\n')
    print(json.dumps({s:{k:r[k] for k in ('fifo_realized_before_fees','net_quantity_change')} for s,r in results.items()},indent=2))

if __name__=='__main__':main()
