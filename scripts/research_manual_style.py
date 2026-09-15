"""Compare learned level-aware holding with existing context on saved OHLCV.

Real saved candles, causal model features, simulated orders. No copied human
order labels, option signals without data, brokerage calls, or live activation.
"""
import argparse
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.quant_policy import normalize_bars,integer_targets
from app.research.holding_policy import HoldingSpec,holding_features,DEFAULT_SYMBOLS,REFERENCES
from app.research.calibrated_holding import CalibratedHoldingModel
from app.research.policy_replay import ShareLedger,ExecutionConfig,replay_day


def snapshot_run(model,frames,predictions,day,capital):
    bars={s:frames[s].loc[frames[s].index.strftime('%Y-%m-%d')==day].rename(columns=str.title) for s in DEFAULT_SYMBOLS}
    index=bars['SNDK'].index;decisions=[]
    if not len(index) or any(not b.index.equals(index) for b in bars.values()):raise ValueError('Synchronized observed session required')
    if not np.all(np.diff(index.asi8)==pd.Timedelta(minutes=5).value):raise ValueError('Missing bars')
    ledger=ShareLedger(list(DEFAULT_SYMBOLS),ExecutionConfig(starting_equity=capital,slippage_bps=5.))
    def target(i,current):
        stamp=index[i]
        mu={s:{h:float(p.loc[stamp]) for h,p in hs.items()} for s,hs in predictions.items()}
        w,info=model.allocation(mu,current,stamp)
        decisions.append(dict(bar_open=stamp.isoformat(),available_at=(stamp+pd.Timedelta(minutes=5)).isoformat(),targets=w,**info))
        return w
    if len(index)==78 and index[-1].strftime('%H:%M')=='15:55':
        result=replay_day(ledger,bars,day,target,lambda w,p,e:integer_targets(w,p,e,spec=model.spec))
    else:
        pending=None;signal=None
        for i,stamp in enumerate(index):
            prices={s:float(b.Open.iloc[i]) for s,b in bars.items()}
            ledger.mark(prices,stamp,'open_before_orders',day)
            if pending is not None:ledger.execute_targets(pending,prices,stamp,signal,day)
            prices={s:float(b.Close.iloc[i]) for s,b in bars.items()}
            state=ledger.mark(prices,stamp+pd.Timedelta(minutes=5),'bar_close',day)
            pending=integer_targets(target(i,state['weights']),prices,state['equity'],spec=model.spec)
            signal=stamp+pd.Timedelta(minutes=5)
        state=ledger.state(prices)
        result=dict(net_pnl=state['equity']-capital,gross_pnl=state['equity']-capital+ledger.costs,costs=ledger.costs,
            fill_count=len(ledger.fills),**{f'{s}_net_pnl':state['symbol_pnl'][s] for s in DEFAULT_SYMBOLS})
    return ledger,result,decisions


def chart(folder,bars,ledger,day,name):
    g=bars.loc[bars.index.strftime('%Y-%m-%d')==day]
    fills=[f for f in ledger.fills if f['symbol']=='SNDK']
    marks=pd.DataFrame(ledger.marks);marks=marks[marks.phase.eq('bar_close')]
    fig,axs=plt.subplots(3,1,figsize=(15,9),sharex=True,gridspec_kw={'height_ratios':[4,1,1]})
    x=g.index+pd.Timedelta(minutes=5)
    axs[0].plot(x,g.close,color='#1678b4',lw=1.7,label='SNDK completed 5m close')
    proxy=((g.high+g.low+g.close)/3*g.volume).cumsum()/g.volume.cumsum()
    axs[0].plot(x,proxy,color='#dba24b',alpha=.85,label='OHLCV VWAP proxy')
    previous=0;export=[];seen=set()
    for f in fills:
        delta=f['quantity']
        action='B' if delta>0 and previous>=0 else 'C' if delta>0 else 'S' if previous>0 else 'X'
        t=pd.Timestamp(f['fill_time']);color={'B':'#df5164','S':'#079a6b','C':'#a779cc','X':'#d79b2a'}[action]
        label={'B':'B: buy long','S':'S: sell long','C':'C: cover short','X':'X: open short'}[action]
        axs[0].scatter(t,f['fill_price'],color=color,marker='^' if delta>0 else 'v',s=28+min(abs(delta),30)*2,
                       label=label if action not in seen else None,zorder=4)
        axs[0].annotate(action,(mdates.date2num(t.to_pydatetime()),f['fill_price']),xytext=(0,7 if delta>0 else -13),textcoords='offset points',ha='center',fontsize=7,color=color)
        seen.add(action);export.append(dict(time=t.isoformat(),action=action,quantity=abs(delta),price=f['fill_price'],
            shares_before=previous,shares_after=f['shares_after'],assumed_cost=f['cost']))
        previous=f['shares_after']
    ts=pd.to_datetime(marks.timestamp,utc=True).dt.tz_convert('America/New_York')
    axs[1].step(ts,marks.SNDK_shares,where='post',color='#555599');axs[1].axhline(0,color='gray',lw=.5);axs[1].set_ylabel('Shares')
    axs[2].plot(ts,marks.SNDK_pnl,color='#258877');axs[2].axhline(0,color='gray',lw=.5);axs[2].set_ylabel('Net PnL ($)')
    axs[0].set_title(f'SNDK {day} | {name}\nActual saved prices + simulated fills; marker size represents shares')
    axs[0].legend(loc='best',ncol=3,fontsize=8);axs[0].set_ylabel('Price ($)')
    for ax in axs:ax.grid(alpha=.15)
    axs[-1].xaxis.set_major_locator(mdates.MinuteLocator(byminute=[0,30],tz=ZoneInfo('America/New_York')))
    axs[-1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=ZoneInfo('America/New_York')))
    fig.tight_layout();fig.savefig(folder/'SNDK_BS_chart.png',dpi=145);plt.close(fig)
    pd.DataFrame(export).to_csv(folder/'SNDK_orders.csv',index=False)


def run(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    source=ROOT/'reports/holding_today_lab_20260914/bars';frames={};hashes={}
    for s in (*DEFAULT_SYMBOLS,*REFERENCES):
        p=source/f'{s}.parquet';f=normalize_bars(pd.read_parquet(p));hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
        p=Path(args.today)/f'{s}.parquet';new=normalize_bars(pd.read_parquet(p));hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
        frames[s]=pd.concat([f.loc[f.index.strftime('%Y-%m-%d')<'2026-09-15'],new])
    if any(not f.index.equals(frames['SNDK'].index) for f in frames.values()):raise ValueError('Input panel timestamps differ')
    reg=dict(status='registered',dates=['2026-09-14','2026-09-15'],variants=['context','levels','levels_error_risk'],
        sources=hashes,capital_by_day={'2026-09-14':47006.42,'2026-09-15':47958.07},execution_friction_bps=5,
        policy_planning_cost_bps=2,actual_fees_verified=False,options_inputs=False,selected_for_live=False,
        limitations=['These dates were already inspected; retrospective development evidence.',
            'No exact manual order times or quantities supplied. Human screenshot is a style reference, not training labels or verified PnL.',
            'Independent daily capital resets and zero starting holdings; shorting and next-open full fills assumed.',
            'Price and quantity decisions generated by a prior-trained model, never copied from future extrema.',
            'Partial sessions retain marked open positions; full sessions use existing 15:55 liquidation.'])
    (out/'registry.json').write_text(json.dumps(reg,indent=2))
    level_spec=HoldingSpec(name='level_context_curve',family='support_context',forecast_error_risk=True)
    x=holding_features(frames,spec=level_spec)
    base_spec=HoldingSpec(name='calibrated_context_curve');base_x=holding_features(frames,spec=base_spec)
    summaries=[]
    for day in reg['dates']:
        before=pd.Timestamp(day,tz='America/New_York')
        risk=CalibratedHoldingModel.fit(frames,before,level_spec,features=x)
        level=copy.deepcopy(risk);level.spec=replace(level_spec,forecast_error_risk=False)
        base=CalibratedHoldingModel.fit(frames,before,base_spec,features=base_x)
        for name,model,features in [('context',base,base_x),('levels',level,x),('levels_error_risk',risk,x)]:
            folder=out/day/name;folder.mkdir(parents=True)
            model.save(folder/'candidate.json')
            today_x={s:f.loc[f.index.strftime('%Y-%m-%d')==day] for s,f in features.items()}
            predictions=model.predictions(today_x)
            ledger,result,decisions=snapshot_run(model,frames,predictions,day,reg['capital_by_day'][day])
            sf=[f for f in ledger.fills if f['symbol']=='SNDK'];cost=sum(f['cost'] for f in sf)
            summaries.append(dict(day=day,variant=name,as_of=(today_x['SNDK'].index[-1]+pd.Timedelta(minutes=5)).isoformat(),
                sndk_net=result['SNDK_net_pnl'],sndk_gross=result['SNDK_net_pnl']+cost,sndk_cost=cost,sndk_fills=len(sf),
                sndk_ending_shares=ledger.shares['SNDK'],portfolio_net=result['net_pnl'],portfolio_cost=result['costs']))
            pd.DataFrame(ledger.fills).to_csv(folder/'fills.csv',index=False);pd.DataFrame(ledger.marks).to_csv(folder/'marks.csv',index=False)
            (folder/'decisions.json').write_text(json.dumps(decisions,allow_nan=False))
            today_x['SNDK'].to_csv(folder/'SNDK_features.csv',index_label='bar_open')
            chart(folder,frames['SNDK'],ledger,day,name)
            print(day,name,round(result['SNDK_net_pnl'],2),len(sf),flush=True)
    s=pd.DataFrame(summaries);s.to_csv(out/'summary.csv',index=False)
    reg.update(status='complete',results=summaries,source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__),ROOT/'backend/app/alpha/support_resistance.py',ROOT/'backend/app/research/holding_policy.py',ROOT/'backend/app/research/calibrated_holding.py',ROOT/'backend/app/research/direction_policy.py']})
    (out/'registry.json').write_text(json.dumps(reg,indent=2))
    report='# SNDK人工交易节奏参考：因果模型对照\n\n'+s.round(2).to_markdown(index=False)+'\n\n'
    report+='不是复制人工成交或事后最优买卖点。B=买入开多，S=卖出多仓，C=平空，X=开空；标记大小反映股数。\n\n'
    for row in summaries:
        path=f"{row['day']}/{row['variant']}"
        report+=f"## {row['day']} {row['variant']}\n\n![SNDK模拟成交]({path}/SNDK_BS_chart.png)\n\n[逐笔股数与价格]({path}/SNDK_orders.csv)\n\n"
    report+='\n'.join('- '+v for v in reg['limitations'])
    (out/'REPORT.md').write_text(report)
    (out/'SHA256SUMS.json').write_text(json.dumps({str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name!='SHA256SUMS.json'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--today',required=True);p.add_argument('--output',required=True);run(p.parse_args())
