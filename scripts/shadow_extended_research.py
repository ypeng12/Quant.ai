#!/usr/bin/env python3
"""Use extended research decisions on fresh local bars; never submit orders."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.research.artifacts import load_platform_results,digest
from app.research.shadow import register,read_manifest,append_decision,verify_log
from app.research.strategy_extensions import EXTENSIONS,ResearchRuntime,ResearchSpec
from app.quant_policy import normalize_bars

def record(directory,bars,account_snapshot,*,now=None):
    manifest=read_manifest(directory);cfg=manifest['specification'];clock=now
    now=pd.Timestamp.now(tz='UTC') if clock is None else pd.Timestamp(clock)
    if now.tzinfo is None:raise ValueError('Observation clock must have timezone')
    candidate=next(c for c in EXTENSIONS if c.name==cfg['candidate'])
    if cfg.get('numerical_retry'):
        from app.research import strategy_extensions
        from app.research.solver_retry import retry_target_weights
        strategy_extensions.target_weights=retry_target_weights
    raw={s:(Path(bars)/f'{s}.parquet').read_bytes() for s in cfg['input_symbols']}
    frames={s:normalize_bars(pd.read_parquet(io.BytesIO(v))) for s,v in raw.items()}
    frames={s:f.loc[f.index+pd.Timedelta(minutes=5)<=now] for s,f in frames.items()}
    if any(f.empty for f in frames.values()):raise ValueError('Missing completed bars')
    latest={f.index[-1] for f in frames.values()}
    if len(latest)!=1:raise ValueError('Synchronized input/reference bars required')
    stamp=latest.pop();available=stamp+pd.Timedelta(minutes=5)
    if candidate.model=='equal':
        from app.research.data_audit import expected_sessions
        local=now.tz_convert('America/New_York');day=str(local.date())
        if not expected_sessions(day,day):raise ValueError('Benchmark requires an exchange session')
        available=local.normalize()+pd.Timedelta(hours=9,minutes=25)
        if not available<=now<available+pd.Timedelta(minutes=5):raise ValueError('Opening benchmark must be recorded at 09:25–09:30 before its intended open')
    else:
        if available<=pd.Timestamp(manifest['registered_at']) or (now-available).total_seconds()>cfg['max_data_age_seconds']:
            raise ValueError('Fresh observations after registration required; a replay is not future validation')
        if not '09:30'<=stamp.strftime('%H:%M')<'15:50':raise ValueError('Outside registered predictive rebalance schedule')
    account_raw=Path(account_snapshot).read_bytes();account=json.loads(account_raw)
    if account.get('simulation') is not True:raise ValueError('Explicit simulation=true snapshot required for this paper decision tool')
    account_time=pd.Timestamp(account['timestamp'])
    if account_time.tzinfo is None or not 0<=(now-account_time).total_seconds()<=cfg['max_data_age_seconds']:raise ValueError('Fresh paper account snapshot required')
    runtime=ResearchRuntime(frames);symbols=runtime.symbols(candidate)
    equity=float(account['equity']);shares=account['shares']
    if equity<=0 or not np.isfinite(equity) or set(shares)!=set(symbols) or not np.isfinite(list(shares.values())).all():raise ValueError('Finite equity and all paper holdings required')
    current={s:float(shares[s])*float(frames[s].close.iloc[-1])/equity for s in symbols}
    spec=ResearchSpec(candidate.name,horizon_bars=candidate.horizon,cost_bps=cfg['cost_bps'])
    if candidate.model=='equal':
        if any(shares.values()):raise ValueError('Registered opening benchmark starts flat; reconcile unexpected paper inventory')
        context=dict(training=[],selection=None,predictions={})
        weights=dict.fromkeys(symbols,spec.gross_limit/len(symbols))
    else:
        context=runtime.prepare(candidate,str(stamp.date()),pd.DatetimeIndex([stamp]))
        weights=runtime.target(context,0,current,spec)
    inputs=Path(directory)/'inputs';inputs.mkdir(exist_ok=True)
    hashes={s:hashlib.sha256(v).hexdigest() for s,v in raw.items()}
    for s,v in raw.items():
        target=inputs/(hashes[s]+'.parquet')
        if not target.exists():target.write_bytes(v)
    account_hash=hashlib.sha256(account_raw).hexdigest();(inputs/(account_hash+'.json')).write_bytes(account_raw)
    payload=dict(available_at=available.isoformat(),candidate=candidate.name,target_weights=weights,current_weights=current,
        training=context['training'],selection=context['selection'],data_hashes=hashes,account_hash=account_hash,
        forecast={s:float(v[0]) for s,v in context['predictions'].items()},pnl=None,orders_submitted=0,
        execution_status='decision_only_no_assumed_fills',
        intent='precommitted_0930_equal_weight' if candidate.model=='equal' else 'completed_bar_prediction')
    return append_decision(directory,payload,now=pd.Timestamp.now(tz='UTC') if clock is None else now)

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('register');p.add_argument('--bundle',required=True);p.add_argument('--directory',required=True)
    p=sub.add_parser('record');p.add_argument('--directory',required=True);p.add_argument('--bars',required=True);p.add_argument('--account-snapshot',required=True)
    p=sub.add_parser('verify');p.add_argument('--directory',required=True)
    args=parser.parse_args()
    if args.command=='register':
        result=load_platform_results(args.bundle)
        if result['status']!='complete':raise ValueError(result.get('reason'))
        research=result['research'];name=research['selected_for_future_paper']
        c=next(c for c in EXTENSIONS if c.name==name)
        sources=[*research['sources'],'scripts/shadow_extended_research.py','backend/app/research/shadow.py']
        retry=bool(research.get('numerical_retry') or name in research.get('numerical_retry_candidates',[]))
        if retry and 'backend/app/research/solver_retry.py' not in sources:sources.append('backend/app/research/solver_retry.py')
        result=register(args.directory,dict(candidate=name,input_symbols=research['symbols'],cost_bps=5,
            numerical_retry=retry,
            observation_schedule='09:25_precommit_0930_open' if c.model=='equal' else 'completed_5min_bar',
            max_data_age_seconds=300,selection_rule=research['selection_rule'],bundle_hash=digest(Path(args.bundle)/'registry.json')),sources)
    elif args.command=='record':result=record(args.directory,args.bars,args.account_snapshot)
    else:
        m,records,last=verify_log(args.directory);result=dict(candidate=m['specification']['candidate'],observations=len(records),orders_submitted=0,pnl=None,last_hash=last)
    print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))

if __name__=='__main__':main()
