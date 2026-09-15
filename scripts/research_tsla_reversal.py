"""Declared, prior-trained intraday comparison; no brokerage writes or promotion."""
import argparse
import copy
from dataclasses import replace, asdict
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.quant_policy import normalize_bars, PolicyModel, target_weights, integer_targets
from app.research.holding_policy import HoldingSpec, holding_features, DEFAULT_SYMBOLS, REFERENCES
from app.research.calibrated_holding import CalibratedHoldingModel
from app.research.policy_replay import ShareLedger, ExecutionConfig


def run(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    today=Path(args.today);cutoff=pd.Timestamp(args.day,tz='America/New_York')
    symbols=DEFAULT_SYMBOLS;allowed=('SNDK','TSLA','NVDA')
    inputs={};frames={};day_frames={}
    for s in (*symbols,*REFERENCES,'MSTR'):
        p=today/f'{s}.parquet';d=normalize_bars(pd.read_parquet(p))
        inputs[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
        day_frames[s]=d.loc[d.index.date==cutoff.date()]
        if s!='MSTR':
            p=ROOT/'reports/holding_today_lab_20260914/bars'/f'{s}.parquet'
            old=normalize_bars(pd.read_parquet(p));old=old.loc[old.index<cutoff]
            inputs[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
            frames[s]=pd.concat([old,day_frames[s]])
    index=day_frames['TSLA'].index
    if any(not d.index.equals(index) for d in day_frames.values()):raise ValueError('Identical observed snapshot grid required')
    if index[0]!=cutoff+pd.Timedelta(hours=9,minutes=30) or not np.all(np.diff(index.asi8)==pd.Timedelta(minutes=5).value):raise ValueError('Continuous regular-session prefix required')
    if index[-1]+pd.Timedelta(minutes=5)>pd.Timestamp.now(tz='America/New_York'):raise ValueError('Incomplete bar')
    frozen_path=ROOT/'reports/quant_research_20260913/selected_policy.json'
    context_path=ROOT/'reports/holding_today_lab_20260914/models/calibrated_context_curve.json'
    for p in [frozen_path,context_path]:inputs[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    spec=HoldingSpec(name='session_context_curve',family='session_context',forecast_error_risk=True)
    registration=dict(status='registered',evaluation_day=args.day,as_of=(index[-1]+pd.Timedelta(minutes=5)).isoformat(),
        capital=args.capital,allowed_symbols=allowed,feature_panel=symbols,references=REFERENCES,inputs=inputs,
        variants=['frozen_5m','context_curve','context_error_curve','session_context_curve','session_context_error_curve'],new_spec=asdict(spec),
        actual_broker_fees=None,execution_friction_bps=args.cost_bps,
        limitations=['Intraday marked simulation, not realized broker profit or a full-session result.',
          'Today was inspected before this change; it is development evidence, not an untouched holdout.',
          'Models trained before today; next-bar open assumed executable with full fills and configured friction.',
          'Forecast risk uses overlapping prior forward errors; not a confidence guarantee.',
          'All variants trade the same three online symbols. PLTR supplies peer features only; MSTR is input only for legacy parity.',
          'Yahoo snapshot matches runner provider but may differ from original live fetch; no exact historical decision log available.'])
    (out/'registry.json').write_text(json.dumps(registration,indent=2))
    features=holding_features(frames,symbols,spec)
    print('session features computed',flush=True)
    risk=CalibratedHoldingModel.fit(frames,cutoff,spec,features=features)
    risk.save(out/'session_context_error_curve.json')
    simple=copy.deepcopy(risk);simple.spec=replace(spec,forecast_error_risk=False)
    simple.save(out/'session_context_curve.json')
    context=CalibratedHoldingModel.load(context_path)
    assert pd.Timestamp(context.trained_before)<=cutoff.tz_localize(None)
    oldx=holding_features(frames,symbols,context.spec)
    context_risk=CalibratedHoldingModel.fit(frames,cutoff,replace(context.spec,forecast_error_risk=True),features=oldx)
    context_risk.save(out/'context_error_curve.json')
    candidates={'frozen_5m':PolicyModel.load(frozen_path),'context_curve':context,
                'context_error_curve':context_risk,'session_context_curve':simple,'session_context_error_curve':risk}
    predictions={n:m.predictions({s:x[s].reindex(index) for s in symbols}) for n,m,x in
                 [('context_curve',context,oldx),('context_error_curve',context_risk,oldx),
                  ('session_context_curve',simple,features),('session_context_error_curve',risk,features)]}
    features['TSLA'].reindex(index).to_csv(out/'TSLA_features.csv',index_label='bar_open_et')
    day_frames['TSLA'].to_csv(out/'TSLA_bars.csv',index_label='bar_open_et')
    rows=[];all_decisions=[]
    for name,model in candidates.items():
        ledger=ShareLedger(list(symbols),ExecutionConfig(starting_equity=args.capital,slippage_bps=args.cost_bps))
        pending=None;signal=None;decisions=[]
        for i,stamp in enumerate(index):
            prices={s:float(day_frames[s].open.iloc[i]) for s in symbols}
            state=ledger.mark(prices,stamp,'open',args.day)
            if pending is not None:ledger.execute_targets(pending,prices,stamp,signal,args.day)
            prices={s:float(day_frames[s].close.iloc[i]) for s in symbols}
            state=ledger.mark(prices,stamp+pd.Timedelta(minutes=5),'close',args.day)
            if name=='frozen_5m':
                forecast=model.forecast({s:day_frames[s].iloc[:i+1] for s in model.symbols})
                ix=[model.symbols.index(s) for s in allowed]
                w=target_weights({s:forecast.mu[s] for s in allowed},forecast.covariance.take(ix,0).take(ix,1),
                    {s:state['weights'][s] for s in allowed},model.spec,symbols=allowed,shortable=dict.fromkeys(allowed,True))
                w={s:w.get(s,0.) for s in symbols};info=dict(cumulative_forecast_bps={s:{'5':forecast.mu.get(s,0.)*10000} for s in symbols})
            else:
                forecast={s:{h:float(p.loc[stamp]) for h,p in hs.items()} for s,hs in predictions[name].items()}
                w,info=model.allocation(forecast,state['weights'],stamp,allowed=allowed,shortable=dict.fromkeys(symbols,True))
            pending=integer_targets(w,prices,state['equity'],spec=model.spec);signal=stamp+pd.Timedelta(minutes=5)
            decisions.append(dict(strategy=name,bar_open=stamp.isoformat(),available_at=signal.isoformat(),
                has_observed_next_open=i<len(index)-1,TSLA_price=prices['TSLA'],TSLA_shares_before=ledger.shares['TSLA'],
                TSLA_target_shares=pending['TSLA'],TSLA_target_weight=w['TSLA'],**info))
        state=ledger.state(prices);fills=pd.DataFrame(ledger.fills)
        net=state['equity']-args.capital;assert np.isclose(sum(state['symbol_pnl'].values()),net,atol=1e-7)
        for s in symbols:
            sf=fills[fills.symbol.eq(s)] if len(fills) else fills
            costs=float(sf.cost.sum()) if len(sf) else 0.
            rows.append(dict(strategy=name,symbol=s,net_pnl=state['symbol_pnl'][s],gross_pnl=state['symbol_pnl'][s]+costs,
                assumed_cost=costs,fills=len(sf),ending_shares=ledger.shares[s],ending_mark=prices[s]))
        folder=out/name;folder.mkdir();fills.to_csv(folder/'fills.csv',index=False)
        pd.DataFrame(ledger.marks).to_csv(folder/'marks.csv',index=False)
        (folder/'decisions.json').write_text(json.dumps(decisions,allow_nan=False))
        all_decisions.extend(decisions)
        print(name,round(net,2), 'TSLA',round(state['symbol_pnl']['TSLA'],2),flush=True)
    summary=pd.DataFrame(rows);summary.to_csv(out/'summary.csv',index=False)
    compact=[]
    for d in all_decisions:
        mu=d['cumulative_forecast_bps']['TSLA']
        compact.append({k:d[k] for k in ['strategy','bar_open','available_at','has_observed_next_open','TSLA_price','TSLA_shares_before','TSLA_target_shares','TSLA_target_weight']}|
                       {f'forecast_{h}m_bps':mu.get(str(h)) for h in (5,15,30,60)})
    pd.DataFrame(compact).to_csv(out/'TSLA_decision_comparison.csv',index=False)
    registration.update(status='complete',results=rows,error_training=risk.error_training,
        source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__),ROOT/'backend/app/research/holding_policy.py',ROOT/'backend/app/research/calibrated_holding.py',ROOT/'backend/app/research/direction_policy.py']})
    (out/'registry.json').write_text(json.dumps(registration,indent=2,allow_nan=False))
    (out/'REPORT.md').write_text('# TSLA反转策略开发对照\n\n截至 '+registration['as_of']+'，期初资金 $'+str(args.capital)+
        '。未平仓按最后已完成K线收盘估值，未收盘，不是券商实现盈利。\n\n'+summary.round(2).to_markdown(index=False)+
        '\n\n新特征从当前及此前已完成K线计算；使用模型学习方向，不按今天走势写多空规则。误差风险仅用此前日期前向校准残差。\n\n'+
        '\n'.join('- '+v for v in registration['limitations'])+
        '\n\n决策明细：TSLA_decision_comparison.csv。训练产物为候选，未激活或发送订单。\n')
    (out/'SHA256SUMS.json').write_text(json.dumps({str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name!='SHA256SUMS.json'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--today',required=True);p.add_argument('--output',required=True)
    p.add_argument('--day',default='2026-09-15');p.add_argument('--capital',type=float,default=48324.62)
    p.add_argument('--cost-bps',type=float,default=5.);run(p.parse_args())
