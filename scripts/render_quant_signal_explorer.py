#!/usr/bin/env python3
"""Render saved signal evidence to a standalone chart; no fitting or networking."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
NY=ZoneInfo("America/New_York")
COLORS={"A":"#61758f","C":"#087f8c","B":"#6b4fc8"}


def render(snapshot, output, symbol=None, date=None):
    data=json.loads(Path(snapshot).read_text())
    symbol=symbol or data['default_selection']['symbol']
    date=date or data['default_selection']['date']
    series=next((s for s in data['series'] if s['symbol']==symbol and s['date']==date),None)
    if series is None:raise ValueError('Requested symbol/date is not present in the saved snapshot')
    points=series['points']
    times=[datetime.fromisoformat(p['timestamp']).astimezone(NY) for p in points]
    decisions=[p for p in points if p['has_decision']]
    dtimes=[datetime.fromisoformat(p['timestamp']).astimezone(NY) for p in decisions]
    with plt.rc_context({'font.family':'DejaVu Sans','font.size':10,'axes.titlesize':12,'axes.labelsize':10,
                         'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#c4ccd3',
                         'axes.labelcolor':'#263747','xtick.color':'#536373','ytick.color':'#536373'}):
        fig,axes=plt.subplots(5,1,figsize=(16,14),sharex=True,gridspec_kw={'height_ratios':[2.3,1.5,1.7,1.3,1.5]})
        fig.patch.set_facecolor('#f6f8fb')
        for ax in axes:
            ax.set_facecolor('white');ax.grid(axis='y',color='#e6ebf0',linewidth=.7)
            ax.margins(x=.015)
        fig.suptitle(f'{symbol}  |  {date}  |  Saved signal and execution evidence',x=.065,y=.975,ha='left',fontsize=21,fontweight='bold',color='#142c42')
        fig.text(.065,.948,'Retrospective development replay • 2 bps execution friction per side • New York time',fontsize=11,color='#566b7c')
        axes[0].plot(times,[p['price']['close'] for p in points],color='#253f52',linewidth=1.7,label='Completed 5-minute close')
        for side,marker,color in [('buy','^','#148660'),('sell','v','#c9574b')]:
            fills=[f for f in series['fills'] if f['model']=='B' and f['side']==side]
            axes[0].scatter([datetime.fromisoformat(f['timestamp']).astimezone(NY) for f in fills],
                            [f['fill_price'] for f in fills],marker=marker,c=color,s=48,edgecolors='white',linewidths=.5,
                            label=f'B simulated {side} fills',zorder=4)
        axes[0].set_ylabel('Price (USD)');axes[0].set_title('Observed price and actual simulated fills',loc='left');axes[0].legend(loc='best',frameon=False,ncol=3,fontsize=9)
        axes[1].plot(dtimes,[p['A']['forecast_bps'] for p in decisions],color=COLORS['A'],linewidth=1.8,label='A prediction • 5 minutes')
        axes[1].plot(dtimes,[np.nan if p['A']['realized_bps'] is None else p['A']['realized_bps'] for p in decisions],color='#9da8b2',alpha=.6,linewidth=.8,label='Later 5-minute price return • hindsight')
        axes[1].axhline(0,color='#aeb8c1',linewidth=.7);axes[1].set_ylabel('Return (bps)');axes[1].set_title('Original model A — five-minute horizon',loc='left');axes[1].legend(loc='best',frameon=False,ncol=2,fontsize=9)
        for model in ['C','B']:
            axes[2].plot(dtimes,[p[model]['forecast_bps'] for p in decisions],color=COLORS[model],linewidth=1.8,label=f'{model} prediction • effective horizon')
        axes[2].plot(dtimes,[np.nan if p['C']['realized_bps'] is None else p['C']['realized_bps'] for p in decisions],color='#9da8b2',alpha=.55,linewidth=.8,label='Later matched price return • hindsight')
        axes[2].axhline(0,color='#aeb8c1',linewidth=.7);axes[2].set_ylabel('Return (bps)');axes[2].set_title('C and B — thirty minutes, shortened toward the 15:55 exit',loc='left');axes[2].legend(loc='best',frameon=False,ncol=3,fontsize=9)
        full=np.array([p['text']['full_adjustment_bps'] for p in decisions])
        effective=np.array([p['text']['effective_adjustment_bps'] for p in decisions])
        axes[3].step(dtimes,full,where='post',color='#d2872b',linestyle='--',linewidth=1.3,label='Full 30-minute text correction')
        axes[3].step(dtimes,effective,where='post',color='#7848bd',linewidth=1.8,label='Applied horizon-scaled correction')
        axes[3].fill_between(dtimes,0,effective,step='post',color='#8a68c4',alpha=.12)
        axes[3].axhline(0,color='#aeb8c1',linewidth=.7);axes[3].set_ylabel('B − C (bps)');axes[3].set_title('Text correction with explicit missing-data / calibration fallback',loc='left');axes[3].legend(loc='best',frameon=False,ncol=2,fontsize=9)
        for model in ['A','C','B']:
            axes[4].step(times,[p[model]['shares'] for p in points],where='post',color=COLORS[model],linewidth=1.6,label=f'{model} simulated shares')
        axes[4].axhline(0,color='#aeb8c1',linewidth=.7);axes[4].set_ylabel('Signed shares');axes[4].set_title('Recorded holdings at bar close — not target allocations',loc='left');axes[4].legend(loc='best',frameon=False,ncol=3,fontsize=9)
        axes[-1].xaxis.set_major_locator(mdates.HourLocator(tz=NY));axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=NY))
        axes[-1].set_xlabel('Decision / bar-close time (America/New_York)')
        active=int(sum(abs(v)>1e-10 for v in effective))
        covered=sum(p['text']['has_text'] for p in decisions)
        evidence_keys={key for p in decisions for key in p['text']['evidence_keys']}
        receipts=sorted({data['evidence'][key]['received_at'][:10] for key in evidence_keys})
        fig.text(.065,.033,f'This slice: {covered}/{len(decisions)} company decisions with text; {active} nonzero corrections; source receipt dates: '+(', '.join(receipts) or 'none')+'.',fontsize=9,color='#405568')
        fig.text(.065,.018,'Later returns are gross price diagnostics, not portfolio PnL. Linear contributions explain model arithmetic, not market causality. No live promotion.',fontsize=9,color='#405568')
        fig.subplots_adjust(left=.065,right=.97,top=.91,bottom=.085,hspace=.33)
        Path(output).parent.mkdir(parents=True,exist_ok=True)
        fig.savefig(output,dpi=160,facecolor=fig.get_facecolor())
        plt.close(fig)
    return {'symbol':symbol,'date':date,'decision_count':len(decisions),'nonzero_corrections':active,'output':str(output)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=ROOT/'reports/financial_sentiment_signal_explorer.json')
    p.add_argument('--output',type=Path,default=ROOT/'reports/financial_sentiment_signal_explorer.png')
    p.add_argument('--symbol');p.add_argument('--date')
    a=p.parse_args();print(json.dumps(render(a.input,a.output,a.symbol,a.date)))
