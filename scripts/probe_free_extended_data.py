#!/usr/bin/env python3
"""Probe free premarket/earnings data quality; never infer missing observations."""
import argparse
import hashlib
import json
from pathlib import Path
import pandas as pd
import yfinance as yf

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    args=parser.parse_args();root=Path(args.output);root.mkdir(parents=True,exist_ok=False)
    result=dict(retrieved_at=pd.Timestamp.now(tz='UTC').isoformat(),provider='Yahoo Finance via yfinance',version=yf.__version__,checks=[],status='running')
    for symbol in ('NVDA','TSLA','MSTR'):
        check=dict(symbol=symbol,kind='five_minute_premarket',requested_start='2026-07-27',requested_end_exclusive='2026-09-12',prepost=True)
        try:
            f=yf.download(symbol,start='2026-07-27',end='2026-09-12',interval='5m',prepost=True,auto_adjust=False,actions=True,threads=False,progress=False,timeout=20)
            if f.empty:raise ValueError('Empty response')
            if isinstance(f.columns,pd.MultiIndex):f=f.xs(symbol,axis=1,level='Ticker')
            if f.index.tz is None:raise ValueError('Timezone missing')
            f.index=f.index.tz_convert('America/New_York')
            path=root/f'{symbol}_extended.parquet';f.to_parquet(path)
            # At 09:25 only bars opening through 09:20 are complete.
            pre=f.between_time('04:00','09:20')
            stats=pre.groupby(pre.index.strftime('%Y-%m-%d')).agg(bars=('Volume','size'),volume=('Volume','sum'),positive_volume_bars=('Volume',lambda x:int((x>0).sum())))
            stats.to_csv(root/f'{symbol}_premarket_coverage.csv')
            check.update(status='received',rows=len(f),premarket_rows=len(pre),premarket_positive_volume_rows=int((pre.Volume>0).sum()),
                premarket_sessions=len(stats),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),file=path.name,
                eligible_for_rvol_research=bool(len(stats)>1 and (stats.positive_volume_bars>0).all()),
                limitation='Coverage probe only; no point-in-time universe/catalyst archive or independent volume verification')
        except Exception as exc:check.update(status='unavailable',reason=str(exc))
        result['checks'].append(check);(root/'probe.json').write_text(json.dumps(result,indent=2)+'\n');print(symbol,check['status'],check.get('premarket_positive_volume_rows'),flush=True)
    for symbol in ('NVDA','TSLA'):
        check=dict(symbol=symbol,kind='earnings_calendar')
        try:
            f=yf.Ticker(symbol).get_earnings_dates(limit=24)
            if f is None or f.empty:raise ValueError('No earnings rows returned')
            path=root/f'{symbol}_earnings.csv';f.to_csv(path)
            check.update(status='received',rows=len(f),columns=list(f.columns),file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        except Exception as exc:check.update(status='unavailable',reason=str(exc))
        check.update(eligible_for_point_in_time_pead=False,reason_for_exclusion='Current retrieval does not establish historical consensus revisions, actual release availability and contemporaneous guidance')
        result['checks'].append(check);(root/'probe.json').write_text(json.dumps(result,indent=2)+'\n');print(symbol,'earnings',check['status'],flush=True)
    result['status']='complete';(root/'probe.json').write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':main()
