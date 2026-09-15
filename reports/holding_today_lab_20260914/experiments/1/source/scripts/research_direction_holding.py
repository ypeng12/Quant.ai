#!/usr/bin/env python3
"""Declared candidate comparison; daily prior-only fits, no broker or promotion."""
import argparse,contextlib,hashlib,io,json,sys
from dataclasses import asdict, replace
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.quant_policy import normalize_bars,integer_targets
from app.research.holding_policy import HoldingSpec,HoldingModel,holding_features,DEFAULT_SYMBOLS,REFERENCES,executable_labels
from app.research.policy_replay import ExecutionConfig,ShareLedger,replay_day,complete_universe,summarize
from app.research.execution_cost_audit import cost_scenarios
from app.research.calibrated_holding import CalibratedHoldingModel

CANDIDATES=(HoldingSpec('legacy_refit_h1',family='legacy',horizons=(1,),planning=False),
            HoldingSpec('paper31_h1',family='paper',horizons=(1,),planning=False),
            HoldingSpec('context_h1',horizons=(1,),planning=False),HoldingSpec())

def duration_metrics(fills):
    durations=[];switches=0;last={};opened={}
    for f in fills:
        key=(f['date'],f['symbol']);now=pd.Timestamp(f['fill_time']);direction=np.sign(f['shares_after'])
        prev=opened.get(key)
        if prev and direction!=prev[0]:
            durations.append((now-prev[1]).total_seconds()/60);opened.pop(key)
        if direction and not opened.get(key):
            if key in last and direction!=last[key]: switches+=1
            last[key]=direction;opened[key]=(direction,now)
    return dict(direction_switches=switches,position_episodes=len(durations),
                mean_holding_minutes=float(np.mean(durations)) if durations else None)

def run(args):
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    registry=output/'registry.json'
    if registry.exists():raise ValueError('Do not overwrite a registered experiment')
    candidates=(HoldingSpec(name='calibrated_legacy_curve',family='legacy'),HoldingSpec(name='calibrated_context_curve')) if args.calibrated_only else CANDIDATES
    if args.candidate:
        candidates=tuple(s for s in candidates if s.name==args.candidate)
        if not candidates:raise ValueError('Candidate is not in the declared family')
    if args.policy_cost_bps is not None:
        candidates=tuple(replace(s,cost_bps=args.policy_cost_bps,name=f'{s.name}_policy_cost{args.policy_cost_bps:g}') for s in candidates)
    engine=CalibratedHoldingModel if args.calibrated_only else HoldingModel
    registration=dict(status='registered',created_at=pd.Timestamp.now(tz='UTC').isoformat(),
        candidates=[asdict(s) for s in candidates],symbols=DEFAULT_SYMBOLS,references=REFERENCES,
        start=args.start,end=args.end,capital=args.capital,simulated_execution_bps=5.,actual_fees=None,
        selection='All candidates reported; no automatic winner promotion',
        evaluation='Historical diagnostics; these dates have been inspected previously, not a pristine holdout',
        sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/'backend/app/research/holding_policy.py',ROOT/'backend/app/research/calibrated_holding.py',ROOT/'backend/app/research/direction_policy.py',ROOT/'backend/app/alpha/paper_bar_alpha.py',ROOT/'backend/app/research/paper_models.py']})
    registry.write_text(json.dumps(registration,indent=2)+'\n')
    frames={};inputs={};source=Path(args.bars)
    for s in (*DEFAULT_SYMBOLS,*REFERENCES):
        p=source/f'{s}.parquet';f=normalize_bars(pd.read_parquet(p))
        if args.append_today:
            from app.data_manager import fetch_and_prepare_data
            with contextlib.redirect_stdout(io.StringIO()): recent=normalize_bars(fetch_and_prepare_data(s,period='5d',interval='5m'))
            recent=recent.loc[recent.index.strftime('%Y-%m-%d')>str(f.index[-1].date())]
            f=pd.concat([f,recent]).sort_index()
        f=f.loc[f.index.strftime('%Y-%m-%d')<=args.end]
        (output/'bars').mkdir(exist_ok=True);dest=output/'bars'/f'{s}.parquet';f.to_parquet(dest)
        frames[s]=f;inputs[s]=dict(source=str(p),snapshot_sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
    dates=sorted({str(d) for d in frames[DEFAULT_SYMBOLS[0]].index.date if args.start<=str(d)<=args.end})
    sessions,_,coverage=complete_universe({s:f.rename(columns=str.title) for s,f in frames.items()},dates)
    results={};future=output/'models';future.mkdir(exist_ok=True)
    for spec in candidates:
        x=holding_features(frames,DEFAULT_SYMBOLS,spec)
        ledger=ShareLedger(list(DEFAULT_SYMBOLS),ExecutionConfig(starting_equity=args.capital,slippage_bps=5.))
        daily=[];diagnostics=[];metrics=[]
        for day in dates:
            model=engine.fit(frames,pd.Timestamp(day,tz='America/New_York'),spec,features=x)
            preds=model.predictions({s:f.loc[f.index.strftime('%Y-%m-%d')==day] for s,f in x.items()})
            bars={s:sessions[s][day] for s in DEFAULT_SYMBOLS};index=bars[DEFAULT_SYMBOLS[0]].index
            def target(i,current):
                stamp=index[i];forecast={s:{h:float(p.loc[stamp]) for h,p in hs.items()} for s,hs in preds.items()}
                w,info=model.allocation(forecast,current,stamp)
                diagnostics.append(dict(date=day,time=stamp.isoformat(),targets=w,**info))
                return w
            row=replay_day(ledger,bars,day,target,lambda w,p,e:integer_targets(w,p,e,spec=spec))
            daily.append(row)
            for s in DEFAULT_SYMBOLS:
                for h in spec.horizons:
                    y,_=executable_labels(frames[s],h);pair=pd.concat([preds[s][h],y.reindex(index)],axis=1).dropna()
                    metrics.append(dict(date=day,symbol=s,horizon=h,rows=len(pair),
                        ic=pair.iloc[:,0].corr(pair.iloc[:,1]),rank_ic=pair.iloc[:,0].corr(pair.iloc[:,1],method='spearman'),
                        mse_bps2=float(np.mean((pair.iloc[:,0]-pair.iloc[:,1])**2))*1e8))
            print(spec.name,day,round(row['net_pnl'],2),row['fill_count'],flush=True)
        folder=output/spec.name;folder.mkdir(exist_ok=True)
        for name,rows in [('daily',daily),('fills',ledger.fills),('marks',ledger.marks),('forecast_metrics',metrics)]:pd.DataFrame(rows).to_csv(folder/f'{name}.csv',index=False)
        (folder/'decisions.json').write_text(json.dumps(diagnostics,allow_nan=False)+'\n')
        summary=summarize(daily,ledger.marks)
        results[spec.name]=dict(**summary,**duration_metrics(ledger.fills),cost_scenarios=cost_scenarios(summary['gross_pnl'],summary['turnover_dollars']),
            latest_day=daily[-1],feature_count=len(x[DEFAULT_SYMBOLS[0]].columns))
        # A next-session candidate, kept separate from all evaluated daily fits.
        deploy=engine.fit(frames,pd.Timestamp(args.end,tz='America/New_York')+pd.Timedelta(days=1),spec,features=x)
        deploy.save(future/f'{spec.name}.json')
    for name in ['equal_weight_hold','simple_trend']:
        ledger=ShareLedger(list(DEFAULT_SYMBOLS),ExecutionConfig(starting_equity=args.capital,slippage_bps=5.));daily=[]
        for day in dates:
            bars={s:sessions[s][day] for s in DEFAULT_SYMBOLS}
            def trend(i,current):
                signs={s:float(np.sign(bars[s].Close.iloc[i]/bars[s].Open.iloc[0]-1)) for s in DEFAULT_SYMBOLS}
                return {s:v*.95/len(DEFAULT_SYMBOLS) for s,v in signs.items()}
            row=replay_day(ledger,bars,day,trend if name=='simple_trend' else None,lambda w,p,e:integer_targets(w,p,e),
                opening_weights=dict.fromkeys(DEFAULT_SYMBOLS,.95/len(DEFAULT_SYMBOLS)) if name=='equal_weight_hold' else None)
            daily.append(row)
        folder=output/name;folder.mkdir(exist_ok=True)
        for n,rows in [('daily',daily),('fills',ledger.fills),('marks',ledger.marks)]:pd.DataFrame(rows).to_csv(folder/f'{n}.csv',index=False)
        summary=summarize(daily,ledger.marks);results[name]=dict(**summary,**duration_metrics(ledger.fills),
            cost_scenarios=cost_scenarios(summary['gross_pnl'],summary['turnover_dollars']),latest_day=daily[-1])
    registration.update(status='complete',inputs=inputs,coverage=coverage,results=results,
        limitations=['Starting inventory zero, next-open full fills and 15:55 liquidation assumed; no broker orders.',
                     'All explicit broker fees remain unverified. 5bps is execution friction assumption, not an Alpaca bill.',
                     'Fixed contemporary four-stock pool with prior 20-session price/liquidity admission, not a survivorship-free universe.',
                     'L1 is not included in these OHLCV comparisons; separate real-observation validation is required.',
                     'Shorting availability assumed; actual borrow availability, partial fills and arrival latency not reproduced.'])
    registry.write_text(json.dumps(registration,indent=2,allow_nan=False)+'\n')
    print(json.dumps({n:{k:v[k] for k in ['net_pnl','gross_pnl','costs','max_drawdown','fill_count','direction_switches','mean_holding_minutes']} for n,v in results.items()},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bars',required=True);p.add_argument('--output',required=True)
    p.add_argument('--start',default='2026-08-31');p.add_argument('--end',default='2026-09-14');p.add_argument('--capital',type=float,default=47006.42)
    p.add_argument('--append-today',action='store_true');p.add_argument('--calibrated-only',action='store_true')
    p.add_argument('--candidate');p.add_argument('--policy-cost-bps',type=float);run(p.parse_args())
