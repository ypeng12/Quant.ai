#!/usr/bin/env python3
"""Two-day genuine IEX diagnostic: prior-day L1 residual, next-day portfolio.

Historical exchange timestamps are not substituted for realtime arrival evidence.
"""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.market_data.alpaca_l1_capture import load_real_l1_events
from app.alpha.paper_l1_alpha import enhanced_l1_features
from app.research.holding_policy import HoldingModel,HoldingSpec,holding_features,executable_labels,DEFAULT_SYMBOLS,REFERENCES
from app.research.holding_l1 import HoldingL1Residual
from app.research.policy_replay import ExecutionConfig,ShareLedger,replay_day
from app.quant_policy import integer_targets

def run(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    frames={s:pd.read_parquet(Path(args.bars)/f'{s}.parquet') for s in (*DEFAULT_SYMBOLS,*REFERENCES)}
    spec=HoldingSpec();x=holding_features(frames,DEFAULT_SYMBOLS,spec)
    days=['2026-09-11','2026-09-14'];models={};preds={};book={};fit={};metrics=[];inputs=[]
    for d in days:
        models[d]=HoldingModel.fit(frames,pd.Timestamp(d,tz='America/New_York'),spec,features=x)
        preds[d]=models[d].predictions({s:f.loc[f.index.strftime('%Y-%m-%d')==d] for s,f in x.items()})
    (out/'registration.json').write_text(json.dumps(dict(status='registered',days=days,choice='context_curve plus learned prior-day L1 h1 residual; no tuning',cost_bps=5,actual_fees=None))+'\n')
    for s in DEFAULT_SYMBOLS:
        book[s]={}
        for d,roots in [(days[0],args.train_inputs),(days[1],args.test_inputs)]:
            parts=[]
            for root in roots:
                p=Path(root)/d/f'{s}.jsonl'
                manifest=json.loads((Path(root)/'manifest.json').read_text())
                if manifest['status']!='complete':raise ValueError('Capture manifest incomplete')
                parts.append(load_real_l1_events(root,s,d));inputs.append(dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
            events=pd.concat(parts).sort_index(kind='stable')
            b=enhanced_l1_features(events);book[s][d]=b
            b.to_parquet(out/f'{s}_{d}_features.parquet')
            del events,parts
        b=book[s][days[0]];base=preds[days[0]][s][1].reindex(b.index);y,end=executable_labels(frames[s],1)
        trained=pd.Series(pd.Timestamp(days[0],tz='America/New_York'),index=b.index)
        fit[s]=HoldingL1Residual().fit(b,base,y.reindex(b.index),end.reindex(b.index),before=pd.Timestamp(days[1],tz='America/New_York'),base_trained_before=trained)
        fit[s].save(out/f'{s}.json')
        test=book[s][days[1]];p=preds[days[1]][s][1]
        residual={}
        for stamp in p.index:
            try:residual[stamp]=fit[s].adjustment(test,stamp+pd.Timedelta(minutes=5))
            except ValueError:residual[stamp]=np.nan
        delta=pd.Series(residual);pair=pd.DataFrame(dict(base=p,plus_l1=p+delta,target=y.reindex(p.index))).dropna()
        metrics.append(dict(symbol=s,train_rows=fit[s].model.artifact['rows'],test_rows=len(pair),
            base_mse_bps2=float(((pair.base-pair.target)**2).mean()*1e8),
            l1_mse_bps2=float(((pair.plus_l1-pair.target)**2).mean()*1e8),
            base_ic=float(pair.base.corr(pair.target)),l1_ic=float(pair.plus_l1.corr(pair.target))))
        print(json.dumps(metrics[-1]),flush=True)
    results={};day=days[1];bars={s:f.loc[f.index.strftime('%Y-%m-%d')==day].rename(columns=str.title) for s,f in frames.items() if s in DEFAULT_SYMBOLS}
    for label,use_l1 in [('base',False),('plus_l1',True)]:
        ledger=ShareLedger(list(DEFAULT_SYMBOLS),ExecutionConfig(starting_equity=47006.42,slippage_bps=5))
        statuses=[]
        def target(i,current):
            stamp=bars[DEFAULT_SYMBOLS[0]].index[i];forecasts={s:{h:float(p.loc[stamp]) for h,p in hs.items()} for s,hs in preds[day].items()}
            residual=None
            if use_l1:
                residual={}
                for s in DEFAULT_SYMBOLS:
                    try:residual[s]=fit[s].adjustment(book[s][day],stamp+pd.Timedelta(minutes=5))
                    except ValueError:residual[s]=0.;statuses.append(dict(symbol=s,time=stamp.isoformat(),state='base_only_missing_complete_L1'))
            return models[day].allocation(forecasts,current,stamp,l1_adjustment=residual)[0]
        result=replay_day(ledger,bars,day,target,lambda w,p,e:integer_targets(w,p,e,spec=spec))
        pd.DataFrame(ledger.fills).to_csv(out/f'{label}_fills.csv',index=False)
        results[label]=dict(**result,missing_l1_decisions=statuses)
    report=dict(status='complete',training_day=days[0],evaluation_day=days[1],metrics=metrics,results=results,inputs=inputs,
        performance_verified=False,selected_for_live=None,limitation='Only one training and one test session; historical IEX exchange-clock artifacts are incompatible with live arrival-clock packets.')
    (out/'result.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v['net_pnl'] for k,v in results.items()}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bars',required=True);p.add_argument('--output',required=True)
    p.add_argument('--train-inputs',nargs='+',required=True);p.add_argument('--test-inputs',nargs='+',required=True);run(p.parse_args())
