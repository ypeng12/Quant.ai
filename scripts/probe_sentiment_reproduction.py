#!/usr/bin/env python3
"""One registered cloud-only fit and tiny numeric QP probes, never a replay.

Reconstruct the first divergent 2 bps C decision from frozen fills and OHLCV.
Compare decoder precision, uncompressed same-protocol forecasts, and solvers
while holding inventory, prices, equity, covariance, constraints and costs fixed.
The production/frozen integer conversion is intentionally unchanged.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.quant_policy import normalize_bars,target_weights,integer_targets,horizon_fraction,_validated_covariance
from app.research.sentiment_alpha_candidate import PriceCandidate,FIXED_SPEC

SYMBOLS=('NVDA','SNDK','TSLA')
INPUTS=(*SYMBOLS,'MSTR')
DAY='2026-09-14'
DECISION='2026-09-14T10:00:00-04:00'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def reconstruct_state(fills,decision_at,close_prices,symbols=SYMBOLS,capital=50000.0):
    at=pd.Timestamp(decision_at)
    if at.tz is None:raise ValueError('Aware decision required')
    cash=float(capital);shares=dict.fromkeys(symbols,0);used=[];previous=None
    for row in fills:
        when=pd.Timestamp(row['fill_time'])
        if when.tz is None or (previous is not None and when<previous):raise ValueError('Unordered fill clock')
        previous=when
        if when>=at:continue  # Same-clock orders execute AFTER this completed-bar decision.
        symbol=row['symbol'];delta=int(row['quantity'])
        if symbol not in shares:raise ValueError('Unexpected filled company')
        cash-=delta*float(row['fill_price'])+float(row['commission_cost'])
        shares[symbol]+=delta
        if not math.isclose(cash,float(row['cash_after']),rel_tol=0,abs_tol=1e-7):raise ValueError('Frozen cash does not reconcile')
        if shares[symbol]!=int(row['shares_after']):raise ValueError('Frozen inventory does not reconcile')
        cash=float(row['cash_after'])  # Preserve the recorded ledger's exact binary float.
        used.append({k:row[k] for k in ('fill_time','symbol','quantity','fill_price','commission_cost')})
    values={s:shares[s]*float(close_prices[s]) for s in symbols}
    equity=cash+sum(values.values())
    if equity<=0:raise ValueError('Invalid probe equity')
    expected=shares.copy()
    for row in fills:
        if pd.Timestamp(row['fill_time'])==at:expected[row['symbol']]+=int(row['quantity'])
    return {'cash':cash,'equity':equity,'shares':shares,'close_prices':close_prices,
            'current_weights':{s:values[s]/equity for s in symbols},
            'frozen_next_open_shares_after_orders':expected,'prior_fills':used}


def qp_probe(mu,covariance,state,solver,spec=FIXED_SPEC):
    cov=_validated_covariance(covariance,len(SYMBOLS))
    weights=target_weights(mu,covariance,state['current_weights'],spec,
        shortable=dict.fromkeys(SYMBOLS,True),symbols=SYMBOLS,solver=solver)
    integer=integer_targets(weights,state['close_prices'],state['equity'],spec)
    w=np.asarray([weights[s] for s in SYMBOLS]);smooth=np.asarray([mu[s] for s in SYMBOLS])-spec.risk_aversion*cov@w
    gross=float(np.abs(w).sum());result={}
    for i,s in enumerate(SYMBOLS):
        raw=float(weights[s]*state['equity']/state['close_prices'][s]);absolute=abs(raw)
        ulp=math.ulp(absolute);current=state['shares'][s]
        result[s]={'mu':float(mu[s]),'mu_hex':float(mu[s]).hex(),
            'target_weight':weights[s],'current_weight':state['current_weights'][s],
            'weight_change':weights[s]-state['current_weights'][s],
            'raw_shares':raw,'raw_shares_hex':raw.hex(),'current_shares':current,
            'raw_share_change':raw-current,'nearest_integer':round(raw),
            'distance_to_nearest_integer_shares':abs(raw-round(raw)),
            'raw_share_ulp':ulp,'absolute_raw_minus_absolute_current_in_ulps':(absolute-abs(current))/ulp,
            'integer_target':integer[s],'integer_delta':integer[s]-current,
            'smooth_marginal_return_bps':float(smooth[i])*10000,
            'no_trade_margin_bps':(spec.cost_bps/10000-abs(float(smooth[i])))*10000,
            'box_constraint_inactive':abs(weights[s])<spec.symbol_limit-1e-8,
            'gross_constraint_inactive':gross<spec.gross_limit-1e-8}
    return {'solver':solver,'status':'solved','gross_weight':gross,'symbols':result}


def run_probe(packet_path,output_path):
    packet,output=Path(packet_path),Path(output_path)
    if output.exists():raise ValueError('Choose a new probe output directory')
    output.mkdir(parents=True,mode=0o700);(output/'.gitignore').write_text('*\n')
    frames={s:normalize_bars(pd.read_parquet(packet/f'{s}.parquet')) for s in INPUTS}
    at=pd.Timestamp(DECISION);signal_at=at-pd.Timedelta(minutes=5)
    prices={s:float(frames[s].loc[signal_at,'close']) for s in SYMBOLS}
    with gzip.open(packet/'baseline/cost_2bps/C/fills.csv.gz','rt') as f:fills=list(csv.DictReader(f))
    state=reconstruct_state(fills,DECISION,prices)
    with gzip.open(packet/'decisions.jsonl.gz','rt') as f:python_rows=[json.loads(line) for line in f]
    def select(rows):
        selected={r['symbol']:float(r['C_mu']) for r in rows if pd.Timestamp(r['decision_at'])==at}
        if set(selected)!=set(SYMBOLS):raise ValueError('Missing/extra probe predictions')
        return selected
    exact=select(python_rows)
    pandas=select(pd.read_json(packet/'decisions.jsonl.gz',lines=True).to_dict(orient='records'))
    precise=select(pd.read_json(packet/'decisions.jsonl.gz',lines=True,precise_float=True).to_dict(orient='records'))
    training=json.loads((packet/'training.json').read_text());frozen_audit=next(r['price'] for r in training if r['date']==DAY)
    files=[packet/f'{s}.parquet' for s in INPUTS]+[packet/'decisions.jsonl.gz',packet/'training.json',packet/'baseline/cost_2bps/C/fills.csv.gz']
    registration={'registered_at':datetime.now(timezone.utc).isoformat(),'day':DAY,'decision_at':DECISION,
        'spec':asdict(FIXED_SPEC),'fits':1,'replays':0,'prediction_updates':False,'promoted':False,
        'purpose':'Numeric reproduction probe; no performance selection.',
        'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),ROOT/'backend/app/quant_policy.py',ROOT/'backend/app/research/sentiment_alpha_candidate.py']},
        'input_sha256':{str(p.relative_to(packet)):sha(p) for p in files},
        'package_versions':{p:importlib.metadata.version(p) for p in ('numpy','pandas','scipy','scikit-learn','osqp')},
        'state':state,'forecast_decoder_values':{'python_json':exact,'pandas_default':pandas,'pandas_precise_float':precise}}
    write(output/'registration.json',registration)
    try:
        candidate=PriceCandidate.fit(frames,DAY,traded_symbols=SYMBOLS)  # The sole cloud fit.
        today={s:f.loc[f.index.date==at.date()] for s,f in frames.items()}
        full=candidate.forecast_frames(today)
        full_mu={s:float(full[s].loc[signal_at]) for s in SYMBOLS}
        covariance=candidate.covariance_at(signal_at)
        variants={'python_json':exact,'pandas_default':pandas,'pandas_precise_float':precise,
                  'refit_unserialized':full_mu}
        # Fixed rounding-bin sensitivity, not forecast/hyperparameter tuning.
        for sign in (-1,1):
            variants[f'python_all_plus_{sign}_half_decimal_bin']={s:exact[s]+sign*5e-11 for s in SYMBOLS}
            variants[f'python_NVDA_plus_{sign}_half_decimal_bin']={**exact,'NVDA':exact['NVDA']+sign*5e-11}
        results={}
        for name,mu in variants.items():
            results[name]={}
            for solver in ('slsqp','osqp'):
                try:results[name][solver]=qp_probe(mu,covariance,state,solver,candidate.spec)
                except Exception as exc:results[name][solver]={'status':'failed','error_type':type(exc).__name__,'reason':str(exc)}
        result={**registration,'status':'complete','covariance':covariance.tolist(),
            'horizon_fraction':horizon_fraction(signal_at,candidate.spec),
            'refit_price_audit':candidate.audit,'frozen_price_audit':frozen_audit,
            'refit_minus_python_mu':{s:full_mu[s]-exact[s] for s in SYMBOLS},'results':results,
            'limitations':['The original uncompressed forecasts and original optimizer iterates were not retained.',
                'Refit-unserialized is generated in this probe environment, not claimed to be the original exact float.',
                'A positive no-trade margin is interpreted only with inactive box/gross constraints.',
                'One-ULP decoder differences are measured; causation requires comparing target/raw-share outputs.',
                'No integer-sizing rule or original strategy was changed by this probe.']}
        write(output/'summary.json',result);return result
    except Exception as exc:
        write(output/'failure.json',{'status':'failed','error_type':type(exc).__name__,'reason':str(exc)})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=run_probe(args.packet,args.output)
    print(json.dumps({'status':result['status'],'fits':result['fits'],'replays':result['replays']}))
