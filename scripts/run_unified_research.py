#!/usr/bin/env python3
"""Exclusive, auditable offline comparisons; never writes live model/config."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import traceback
from importlib.metadata import version
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.quant_policy import PolicySpec, labeled_frame, integer_targets
from app.research.platform import CANDIDATES, features_for_panel, FittedForecast, joint_risk, portfolio_target, risk_diagnostics
from app.research.policy_replay import ExecutionConfig, ShareLedger, complete_universe, replay_day, summarize, fixed_order_cost_stress
from app.market_data.alpaca_l1_capture import load_real_l1_events
from app.research.attribution import ledger_attribution
from app.research.data_audit import audit_bars, input_provenance


def write(path,payload):
    path.write_text(json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False)+'\n')

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run(args):
    output=Path(args.output); output.mkdir(parents=True,exist_ok=False)
    files={s:Path(args.bars)/f'{s}.parquet' for s in args.symbols}
    frames={s:pd.read_parquet(p) for s,p in files.items()}
    dates,data_audit=audit_bars(frames,args.start,args.end)
    provenance=input_provenance(args.bars,args.symbols)
    if not dates:raise ValueError('No evaluation dates in supplied data')
    sessions,_,coverage=complete_universe(frames,dates)
    registry=dict(schema_version=1,registered_at=pd.Timestamp.now(tz='UTC').isoformat(),status='running',
                  interpretation='retrospective_exploration_not_untouched_holdout',
                  evaluation_dates=dates,symbols=args.symbols,starting_equity=args.equity,data_audit=data_audit,data_provenance=provenance,
                  library_versions={name:version(name) for name in ['numpy','pandas','scipy','scikit-learn','lightgbm','exchange-calendars','osqp']},
                  portfolio_solver='osqp',
                  cost_bps_per_side=args.costs,candidates=[asdict(c) for c in CANDIDATES],
                  ridge_alpha=10,horizon_bars=1,risk_aversion=50,gross_limit=.95,symbol_limit=.7,
                  uncertainty_aversion=1,common_risk_aversion=1,selected_for_live=None,
                  data_paths={s:str(p.resolve()) for s,p in files.items()},data_hashes={s:digest(p) for s,p in files.items()},
                  sources={str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__).resolve(),ROOT/'backend/app/research/platform.py',ROOT/'backend/app/quant_policy.py',ROOT/'backend/app/research/policy_replay.py',ROOT/'backend/app/research/causal_week_replay.py',ROOT/'backend/app/alpha/real_l1_alpha.py',ROOT/'backend/app/research/attribution.py',ROOT/'backend/app/market_data/alpaca_l1_capture.py',ROOT/'backend/app/market_data/history.py',ROOT/'backend/app/research/data_audit.py']},
                  limitations=['Same prior-session model fit / next-open fills / intraday flat for all candidates.',
                               'Costs assumed, not broker-measured; no latency, intrabar drawdown, impact, financing or historical borrow constraints.',
                               'This is a selected retrospective sample. More symbols do not establish time stability or historical constituent membership.',
                               'Ridge uncertainty is an approximate session-clustered parameter error; not a calibrated probability.',
                               'PCA common factor is statistical, not verified industry exposure.'])
    write(output/'registry.json',registry)
    for source in registry['sources']:
        archive=output/'source'/source;archive.parent.mkdir(parents=True,exist_ok=True)
        archive.write_bytes((ROOT/source).read_bytes())
    pd.DataFrame(coverage).to_csv(output/'coverage.csv',index=False)
    symbols=tuple(args.symbols);spec=PolicySpec('unified',horizon_bars=1,risk_aversion=50)
    labels={s:labeled_frame(f,spec)[1] for s,f in frames.items()}
    features_cache={};models={};forecasts={};risk={};trials=[]
    events={s:pd.concat([load_real_l1_events(d,s) for d in args.l1_dir]).sort_index(kind='stable') for s in symbols} if args.l1_dir else {}
    registry['l1_input_hashes']={str(p.resolve()):digest(p) for d in (args.l1_dir or []) for p in Path(d).rglob('*') if p.is_file()}
    write(output/'registry.json',registry)
    for c in CANDIDATES:
        for cost in args.costs:
            tag=f'{c.name}_cost{cost:g}';folder=output/tag;folder.mkdir()
            print(tag,flush=True)
            cfg=ExecutionConfig(starting_equity=args.equity,slippage_bps=cost)
            policy=PolicySpec(tag,horizon_bars=1,risk_aversion=50,cost_bps=cost)
            ledger=ShareLedger(list(symbols),cfg);daily=[];diagnostics=[]
            try:
                if c.features in ('l1','combined'):
                    missing=[s for s in symbols if s not in events or events[s].empty]
                    if missing:raise ValueError(f'Real L1 unavailable for {missing[0]}')
                if c.portfolio not in ('cash','equal') and c.features not in features_cache:
                    features_cache[c.features]=features_for_panel(frames,c.features,events)
                for day in dates:
                    bars={s:sessions[s][day] for s in symbols};index=bars[symbols[0]].index
                    target=None;opening=None
                    if c.portfolio=='equal':opening={s:policy.gross_limit/len(symbols) for s in symbols}
                    elif c.portfolio!='cash':
                        if day not in risk:risk[day]=joint_risk(frames,day,symbols)
                        cov,common,loading=risk[day]
                        predictions={};errors={}
                        for s in symbols:
                            key=(c.features,c.model,day,s)
                            if key not in models:
                                all_features=features_cache[c.features][s]
                                model=FittedForecast(c.features,c.model).fit(all_features,labels[s],day)
                                models[key]=model
                                forecasts[key]=model.predict(all_features.reindex(index))
                                write(folder/f'train_{day}_{s}.json',dict(last_train=model.last_train,rows=model.rows,sessions=model.sessions,features=model.names))
                            predictions[s],errors[s]=forecasts[key]
                        if any(not np.isfinite(predictions[s][:76]).all() for s in symbols):
                            raise ValueError('Incomplete real L1 evaluation coverage; missing signals cannot become invented predictions')
                        def target(i,current):
                            mu={s:float(predictions[s][i]) for s in symbols};error={s:float(errors[s][i]) for s in symbols}
                            weights=portfolio_target(mu,error,current,cov,common,policy,robust=c.portfolio in ('robust','uncertainty','common'),
                                                     uncertainty_aversion=0 if c.portfolio=='common' else 1,
                                                     common_risk_aversion=0 if c.portfolio=='uncertainty' else 1)
                            diagnostics.append(dict(timestamp=index[i].isoformat(),available_at=(index[i]+pd.Timedelta(minutes=5)).isoformat(),
                                                    forecast=mu,forecast_error=error,weights=weights,
                                                    **risk_diagnostics([weights[s] for s in symbols],cov,common,loading)))
                            return weights
                    daily.append(replay_day(ledger,bars,day,target,lambda w,p,e:integer_targets(w,p,e,policy),opening))
                summary=summarize(daily,ledger.marks)
                if not np.isclose(summary['costs'],summary['turnover_dollars']*cost/10000,atol=1e-7):
                    raise AssertionError('Execution cost mismatch')
                per_symbol={s:dict(net_pnl=sum(d[f'{s}_net_pnl'] for d in daily),costs=sum(d[f'{s}_costs'] for d in daily)) for s in symbols}
                if not np.isclose(sum(r['net_pnl'] for r in per_symbol.values()),summary['net_pnl'],atol=1e-7):
                    raise AssertionError('Attribution mismatch')
                for label,records in [('daily',daily),('fills',ledger.fills),('marks',ledger.marks)]:
                    pd.DataFrame(records).to_csv(folder/f'{label}.csv',index=False)
                write(folder/'decisions.json',diagnostics)
                attribution,detail=ledger_attribution(pd.DataFrame(ledger.marks),pd.DataFrame(ledger.fills),symbols,args.equity)
                write(folder/'attribution.json',attribution);detail.to_csv(folder/'attribution.csv',index=False)
                result=dict(candidate=asdict(c),cost_bps=cost,status='complete',summary=summary,per_symbol=per_symbol,
                            attribution=attribution,
                            fixed_order_stress_5bps=fixed_order_cost_stress(ledger.fills,ledger.marks,ExecutionConfig(starting_equity=args.equity,slippage_bps=5)) if ledger.fills else None)
            except (ValueError,ImportError) as exc:
                result=dict(candidate=asdict(c),cost_bps=cost,status='unavailable',reason=str(exc))
            write(folder/'summary.json',result);trials.append(result)
    # Paired daily differences, by session; a descriptive SE, not a discovery claim.
    for trial in trials:
        if trial['status']!='complete':continue
        cost=trial['cost_bps'];tag=f"{trial['candidate']['name']}_cost{cost:g}"
        base=output/f'price_ridge_cost{cost:g}'/'daily.csv'
        if base.exists():
            a=pd.read_csv(output/tag/'daily.csv');b=pd.read_csv(base)
            diff=a.net_return-b.net_return
            trial['paired_baseline']=dict(mean_daily_return_difference=float(diff.mean()),
                daily_difference_se=float(diff.std(ddof=1)/np.sqrt(len(diff))) if len(diff)>1 else None, sessions=len(diff))
    registry.update(status='complete',finished_at=pd.Timestamp.now(tz='UTC').isoformat(),trials=trials)
    registry['artifact_hashes']={str(p.relative_to(output)):digest(p) for p in output.rglob('*') if p.is_file() and p.name!='registry.json'}
    write(output/'registry.json',registry)
    # Registry digest lives outside the file it verifies.
    (output/'registry.sha256').write_text(digest(output/'registry.json')+'\n')
    print(str(output),flush=True)
    return registry


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bars',default='reports/quant_audit_20260912/bars');p.add_argument('--symbols',nargs='+',default=['SNDK','TSLA','MSTR','NVDA'])
    p.add_argument('--start',default='2026-08-31');p.add_argument('--end',default='2026-09-11')
    p.add_argument('--costs',nargs='+',type=float,default=[2,5]);p.add_argument('--equity',type=float,default=100000)
    p.add_argument('--l1-dir',nargs='+');p.add_argument('--output',required=True)
    run(p.parse_args())
if __name__=='__main__':main()
