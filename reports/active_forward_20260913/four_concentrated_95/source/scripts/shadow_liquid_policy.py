#!/usr/bin/env python3
"""Frozen large-cap research decisions on fresh paper inputs. No broker imports."""
import argparse
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.research.artifacts import load_platform_results,digest
from app.research.shadow import register,read_manifest,append_decision,verify_log
from app.research.liquid_policy import LiquidRuntime,LiquidityRules,LIQUID_CANDIDATES
from app.research.active_policy import ActiveRuntime,ACTIVE_CANDIDATES,ActiveCandidate
from app.quant_policy import normalize_bars


def register_policy(bundle,directory,candidate='largecap_integrated'):
    result=load_platform_results(bundle)
    if result['status']!='complete':raise ValueError(result.get('reason'))
    research=result['research']
    c=next(c for c in (*LIQUID_CANDIDATES,*ACTIVE_CANDIDATES) if c.name==candidate)
    if c.name not in {x['name'] for x in research['candidates']}:raise ValueError('Candidate was not evaluated in this bundle')
    if c.benchmark or c.control:raise ValueError('Register an eligible predictive paper candidate')
    if not all(research['source_matches_workspace'].values()):raise ValueError('Research sources changed; rerun the research before registration')
    return register(directory,dict(candidate=c.name,input_symbols=research['symbols'],cost_bps=5,
        liquidity_rules=research['liquidity_rules'],max_data_age_seconds=300,
        selection_rule='Declared engineering challenger, not a validated winner; no automatic profit-based promotion',
        metadata_cutoff='09:25 America/New_York on decision date',observation_schedule='completed_5min_bar',
        bundle_hash=digest(Path(bundle)/'registry.json')),
        list(dict.fromkeys([*research['sources'],'scripts/shadow_liquid_policy.py','backend/app/research/shadow.py','backend/app/research/active_policy.py'])))


def record(directory,bars,instruments,account_snapshot,*,now=None):
    manifest=read_manifest(directory);cfg=manifest['specification'];clock=now
    now=pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    if now.tzinfo is None:raise ValueError('Observation time must have timezone')
    raw={s:(Path(bars)/f'{s}.parquet').read_bytes() for s in cfg['input_symbols']}
    frames={s:normalize_bars(pd.read_parquet(io.BytesIO(v))) for s,v in raw.items()}
    frames={s:f.loc[f.index+pd.Timedelta(minutes=5)<=now] for s,f in frames.items()}
    if any(f.empty for f in frames.values()):raise ValueError('Missing completed bars')
    latest={f.index[-1] for f in frames.values()}
    if len(latest)!=1:raise ValueError('Synchronized stock and reference bars required')
    stamp=latest.pop();available=stamp+pd.Timedelta(minutes=5)
    if available<=pd.Timestamp(manifest['registered_at']) or not 0<=(now-available).total_seconds()<=cfg['max_data_age_seconds']:
        raise ValueError('Fresh future observations required; historical replay is not forward validation')
    if not '09:30'<=stamp.strftime('%H:%M')<'15:50':raise ValueError('Outside registered prediction schedule')
    metadata_raw=Path(instruments).read_bytes();metadata=json.loads(metadata_raw)['records']
    account_raw=Path(account_snapshot).read_bytes();account=json.loads(account_raw)
    if account.get('simulation') is not True:raise ValueError('Explicit simulation=true account snapshot required')
    account_time=pd.Timestamp(account['timestamp'])
    if account_time.tzinfo is None or not 0<=(now-account_time).total_seconds()<=cfg['max_data_age_seconds']:
        raise ValueError('Fresh paper account snapshot required')
    c=next(c for c in (*LIQUID_CANDIDATES,*ACTIVE_CANDIDATES) if c.name==cfg['candidate'])
    engine=ActiveRuntime if isinstance(c,ActiveCandidate) else LiquidRuntime
    runtime=engine(frames,LiquidityRules(**cfg['liquidity_rules']),metadata)
    symbols=runtime.symbols(c);equity=float(account['equity']);shares=account['shares']
    if equity<=0 or not np.isfinite(equity) or set(shares)!=set(symbols) or not np.isfinite(list(shares.values())).all():
        raise ValueError('Positive equity and all paper holdings required; unknown exposure cannot be omitted')
    current={s:float(shares[s])*float(frames[s].close.iloc[-1])/equity for s in symbols}
    context=runtime.prepare(c,str(stamp.date()),pd.DatetimeIndex([stamp]))
    weights,explanation=runtime.target(c,context,0,current,cost=cfg['cost_bps'])
    inputs=Path(directory)/'inputs';inputs.mkdir(exist_ok=True)
    hashes={s:hashlib.sha256(v).hexdigest() for s,v in raw.items()}
    for s,v in raw.items():
        target=inputs/(hashes[s]+'.parquet')
        if not target.exists():target.write_bytes(v)
    account_hash=hashlib.sha256(account_raw).hexdigest();(inputs/(account_hash+'.json')).write_bytes(account_raw)
    # Retain exact metadata in the signed payload; shared verification checks the
    # hash chain, so metadata cannot be replaced independently of the decision.
    calibration=context['calibration']
    payload=dict(available_at=available.isoformat(),candidate=c.name,current_weights=current,target_weights=weights,
        eligibility=context['eligibility'],training=context['training'],
        calibration=None if calibration is None else {k:v.tolist() if isinstance(v,np.ndarray) else v for k,v in calibration.items()},
        instrument_metadata_json=metadata_raw.decode('utf-8'),instrument_metadata_hash=hashlib.sha256(metadata_raw).hexdigest(),
        data_hashes=hashes,account_hash=account_hash,explanation=explanation,
        pnl=None,orders_submitted=0,execution_status='decision_only_no_assumed_fills')
    return append_decision(directory,payload,now=now if clock is not None else pd.Timestamp.now(tz='UTC'))


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('register');q.add_argument('--bundle',required=True);q.add_argument('--directory',required=True)
    q.add_argument('--candidate',default='largecap_integrated',choices=[c.name for c in (*LIQUID_CANDIDATES,*ACTIVE_CANDIDATES) if not(c.control or c.benchmark)])
    q=sub.add_parser('record');q.add_argument('--directory',required=True);q.add_argument('--bars',required=True)
    q.add_argument('--instruments',required=True);q.add_argument('--account-snapshot',required=True)
    q=sub.add_parser('verify');q.add_argument('--directory',required=True)
    args=p.parse_args()
    if args.command=='register':result=register_policy(args.bundle,args.directory,args.candidate)
    elif args.command=='record':result=record(args.directory,args.bars,args.instruments,args.account_snapshot)
    else:
        m,rows,last=verify_log(args.directory)
        result=dict(candidate=m['specification']['candidate'],observations=len(rows),orders_submitted=0,pnl=None,last_hash=last)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))

if __name__=='__main__':main()
