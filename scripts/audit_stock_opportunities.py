#!/usr/bin/env python3
"""Descriptive opportunity audit only: no forecasts, orders, or strategy PnL."""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.quant_policy import normalize_bars
from app.research.artifacts import digest


def run(output):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    files = {s: ROOT/'reports/quant_audit_20260912/bars'/f'{s}.parquet' for s in ('SNDK', 'TSLA', 'NVDA')}
    files.update({s: ROOT/'reports/platform_universe30_bars_20260913'/f'{s}.parquet' for s in ('MU', 'SPY', 'SOXX')})
    frames = {s: normalize_bars(pd.read_parquet(p)) for s, p in files.items()}
    rows, prefixes, returns = [], [], {}
    for s, f in frames.items():
        sample = f.loc['2026-08-31':'2026-09-11']
        returns[s] = sample.close.groupby(sample.index.date).pct_change(fill_method=None)
        for day, b in sample.groupby(sample.index.date):
            assert len(b) == 78 and b.index[0].strftime('%H:%M') == '09:30' and b.index[-1].strftime('%H:%M') == '15:55'
            opening = float(b.open.iloc[0]); net = float(b.close.iloc[-1]-opening)
            path = abs(float(b.close.iloc[0])-opening)+b.close.diff().abs().sum()
            rows.append(dict(date=str(day), symbol=s, open_to_close_pct=net/opening*100,
                             high_low_range_pct=float(b.high.max()-b.low.min())/opening*100,
                             close_path_efficiency=float(abs(net)/path) if path else 0.))
            for cutoff in ('10:00', '10:30', '11:00'):
                available = pd.Timestamp(f'{day} {cutoff}', tz='America/New_York')
                observed = b.loc[b.index+pd.Timedelta(minutes=5) <= available]
                past = f.loc[f.index.date < day]
                past_prefix = past.loc[past.index.strftime('%H:%M') < cutoff]
                grouped = past_prefix.groupby(past_prefix.index.date)
                totals = grouped.volume.sum().loc[grouped.size() == len(observed)].iloc[-20:]
                prefixes.append(dict(date=str(day), symbol=s, available_at=available.isoformat(),
                                     observed_return_pct=float(observed.close.iloc[-1]/opening-1)*100,
                                     observed_range_pct=float(observed.high.max()-observed.low.min())/opening*100,
                                     volume_vs_prior20_same_prefix=float(observed.volume.sum()/totals.mean()) if len(totals)==20 else None))
    daily = pd.DataFrame(rows); daily.to_csv(output/'daily.csv', index=False)
    pd.DataFrame(prefixes).to_csv(output/'observed_prefixes.csv', index=False)
    aligned = pd.DataFrame(returns)[['SNDK', 'MU']].dropna()
    a = daily.pivot(index='date', columns='symbol', values='open_to_close_pct')
    result = dict(interpretation='Descriptive, already-viewed historical sample; not predictive Alpha or simulated profit',
                  start='2026-08-31', end='2026-09-11', daily_sessions=len(a),
                  sndk_mu_same_day_direction_count=int((np.sign(a.SNDK)==np.sign(a.MU)).sum()),
                  sndk_mu_contemporaneous_5min_correlation=float(aligned.SNDK.corr(aligned.MU)),
                  aligned_5min_rows=len(aligned), source_sha256=digest(__file__),
                  inputs={s:dict(path=str(p.relative_to(ROOT)), sha256=digest(p)) for s,p in files.items()},
                  limitations=['Full-day range and path efficiency are hindsight diagnostics, never known at the open.',
                               'Contemporaneous correlation does not establish lead-lag predictability or mean reversion.',
                               'Close-path efficiency uses sampled five-minute closes and omits within-bar paths.',
                               'Data are the existing local research snapshot; this audit does not independently verify the vendor.'])
    result['outputs']={p.name:digest(p) for p in output.glob('*.csv')}
    (output/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('inputs','outputs','limitations')},indent=2))
    print(daily.loc[(daily.date>='2026-09-08') & daily.symbol.isin(['SNDK','MU'])].to_string(index=False))
    print(daily.loc[daily.date=='2026-09-04'].to_string(index=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    run(parser.parse_args().output)
