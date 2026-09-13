#!/usr/bin/env python3
"""Register or record future research decisions from local data; never place orders."""
import argparse
from dataclasses import asdict
import json
import io
import hashlib
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.research.shadow import register,read_manifest,append_decision,verify_log
from app.research.platform import CANDIDATES,features_for_panel,FittedForecast,joint_risk,portfolio_target,risk_diagnostics
from app.quant_policy import PolicySpec,normalize_bars,labeled_frame
from app.research.artifacts import digest
from app.market_data.alpaca_l1_capture import load_real_l1_events


def record(args):
    m=read_manifest(args.directory);cfg=m['specification'];candidate=next(c for c in CANDIDATES if c.name==cfg['candidate'])
    now=pd.Timestamp.now(tz='UTC');symbols=tuple(cfg['symbols']);paths={s:Path(args.bars)/f'{s}.parquet' for s in symbols}
    raw_bytes={s:p.read_bytes() for s,p in paths.items()}
    frames={s:normalize_bars(pd.read_parquet(io.BytesIO(content))) for s,content in raw_bytes.items()}
    frames={s:f.loc[f.index+pd.Timedelta(minutes=5)<=now] for s,f in frames.items()}
    if any(f.empty for f in frames.values()):raise ValueError('No completed bars')
    latest={f.index[-1] for f in frames.values()}
    if len(latest)!=1:raise ValueError('Symbols do not have synchronized latest bars')
    stamp=latest.pop();available=stamp+pd.Timedelta(minutes=5);day=str(stamp.date())
    if available<=pd.Timestamp(m['registered_at']) or (now-available).total_seconds()>cfg['max_data_age_seconds']:
        raise ValueError('Need fresh bars after registration; old replay is not future validation')
    if stamp.strftime('%H:%M')<'09:30' or stamp.strftime('%H:%M')>='15:50':
        raise ValueError('No predictive rebalance at this bar under registered intraday research schedule')
    account_bytes=Path(args.account_snapshot).read_bytes()
    account=json.loads(account_bytes);account_time=pd.Timestamp(account['timestamp'])
    if account_time.tzinfo is None or not 0 <= (now-account_time).total_seconds() <= cfg['max_data_age_seconds']:
        raise ValueError('Current timestamped account snapshot required')
    equity=float(account['equity']);shares=account['shares']
    if not np.isfinite(equity) or equity<=0 or set(shares)!=set(symbols) or not np.isfinite(list(shares.values())).all():
        raise ValueError('Explicit finite equity and all symbol holdings required')
    policy=PolicySpec('shadow',horizon_bars=1,risk_aversion=cfg['risk_aversion'],cost_bps=cfg['cost_bps'],ridge_alpha=cfg['ridge_alpha'])
    events={s:pd.concat([load_real_l1_events(d,s) for d in args.l1_dir]).sort_index(kind='stable') for s in symbols} if args.l1_dir else {}
    features=features_for_panel(frames,candidate.features,events)
    mu={};errors={};training={}
    for s in symbols:
        labels=labeled_frame(frames[s],policy)[1]
        fit=FittedForecast(candidate.features,candidate.model,cfg['ridge_alpha']).fit(features[s],labels,day)
        pred,error=fit.predict(features[s].loc[[stamp]])
        if not np.isfinite([pred[0],error[0]]).all():raise ValueError('Missing genuine features')
        mu[s]=float(pred[0]);errors[s]=float(error[0]);training[s]=dict(last_train=fit.last_train,rows=fit.rows,sessions=fit.sessions)
    cov,common,loading=joint_risk(frames,day,symbols)
    current={s:float(shares[s])*float(frames[s].close.iloc[-1])/equity for s in symbols}
    weights=portfolio_target(mu,errors,current,cov,common,policy,robust=candidate.portfolio in ('robust','uncertainty','common'),
                             uncertainty_aversion=0 if candidate.portfolio=='common' else cfg['uncertainty_aversion'],
                             common_risk_aversion=0 if candidate.portfolio=='uncertainty' else cfg['common_risk_aversion'])
    retained=Path(args.directory)/'inputs';retained.mkdir(exist_ok=True)
    hashes={s:hashlib.sha256(content).hexdigest() for s,content in raw_bytes.items()}
    for s,content in raw_bytes.items():
        archive=retained/(hashes[s]+'.parquet')
        if not archive.exists():archive.write_bytes(content)
    event_hashes={}
    for s,event_frame in events.items():
        buffer=io.BytesIO();event_frame.to_parquet(buffer);content=buffer.getvalue()
        event_hashes[s]=hashlib.sha256(content).hexdigest()
        archive=retained/(event_hashes[s]+'.parquet')
        if not archive.exists():archive.write_bytes(content)
    account_hash=hashlib.sha256(account_bytes).hexdigest()
    (retained/(account_hash+'.json')).write_bytes(account_bytes)
    payload=dict(available_at=available.isoformat(),bar_open=stamp.isoformat(),candidate=candidate.name,forecast=mu,forecast_error=errors,
                 current_weights=current,target_weights=weights,training=training,account_snapshot=account,
                 data_hashes=hashes,l1_event_hashes=event_hashes,account_hash=account_hash,
                 risk=risk_diagnostics([weights[s] for s in symbols],cov,common,loading),pnl=None,orders_submitted=0)
    return append_decision(args.directory,payload,now=pd.Timestamp.now(tz='UTC'))


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('register');r.add_argument('--directory',required=True);r.add_argument('--symbols',nargs='+',required=True)
    r.add_argument('--candidate',choices=[c.name for c in CANDIDATES if c.portfolio not in ('cash','equal')],default='context_robust')
    for name,value in [('cost-bps',5),('risk-aversion',50),('ridge-alpha',10),('uncertainty-aversion',1),('common-risk-aversion',1),('max-data-age-seconds',300)]:
        r.add_argument('--'+name,type=float,default=value)
    d=sub.add_parser('record');d.add_argument('--directory',required=True);d.add_argument('--bars',required=True);d.add_argument('--account-snapshot',required=True);d.add_argument('--l1-dir',nargs='+')
    v=sub.add_parser('verify');v.add_argument('--directory',required=True)
    args=p.parse_args()
    if args.command=='register':
        cfg=vars(args).copy();cfg.pop('directory');cfg.pop('command')
        if not args.symbols or len(set(args.symbols))!=len(args.symbols):raise ValueError('Distinct symbols required')
        for key,value in cfg.items():
            if isinstance(value,float) and (not np.isfinite(value) or value<0):raise ValueError('Nonnegative finite parameters required')
        sources=['scripts/shadow_research.py','backend/app/research/shadow.py','backend/app/research/platform.py','backend/app/research/artifacts.py','backend/app/quant_policy.py','backend/app/alpha/real_l1_alpha.py','backend/app/market_data/alpaca_l1_capture.py','backend/app/market_data/history.py']
        result=register(args.directory,cfg,sources)
    elif args.command=='record':result=record(args)
    else:
        manifest,records,last=verify_log(args.directory);result=dict(registered_at=manifest['registered_at'],observations=len(records),last_hash=last,orders_submitted=0)
    print(json.dumps(result,indent=2,allow_nan=False))
if __name__=='__main__':main()
