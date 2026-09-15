"""Observed support/resistance references with causal availability timestamps.

Diagnostic report only: no brokerage calls, trade rules, or efficacy claims.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from zoneinfo import ZoneInfo


def build_levels(bars, day):
    day=pd.Timestamp(day,tz='America/New_York')
    current=bars.loc[bars.index.date==day.date()].copy()
    prior=bars.loc[bars.index<day]
    previous=prior.loc[prior.index.date==prior.index[-1].date()]
    start=day+pd.Timedelta(hours=9,minutes=30)
    if current.index[0]!=start or len(current)<3:raise ValueError('Opening three completed bars required')
    if not np.all(np.diff(current.index.asi8)==pd.Timedelta(minutes=5).value):raise ValueError('Missing intraday bars')
    levels=[]
    def add(kind,price,formed,available):
        levels.append(dict(kind=kind,price=float(price),formed_at=str(formed),available_at=str(available)))
    for name,value in [('previous_high',previous.high.max()),('previous_low',previous.low.min()),('previous_close',previous.close.iloc[-1])]:
        add(name,value,previous.index[-1]+pd.Timedelta(minutes=5),start)
    add('opening_15m_high',current.high.iloc[:3].max(),start,start+pd.Timedelta(minutes=15))
    add('opening_15m_low',current.low.iloc[:3].min(),start,start+pd.Timedelta(minutes=15))
    # Two completed bars on each side, a descriptive convention, not a fitted
    # trading rule. Pivots become visible at confirmation, never at their origin.
    for i in range(2,len(current)-2):
        window=current.iloc[i-2:i+3]
        if current.high.iloc[i]>window.high.drop(current.index[i]).max():
            add('confirmed_swing_high',current.high.iloc[i],current.index[i],current.index[i+2]+pd.Timedelta(minutes=5))
        if current.low.iloc[i]<window.low.drop(current.index[i]).min():
            add('confirmed_swing_low',current.low.iloc[i],current.index[i],current.index[i+2]+pd.Timedelta(minutes=5))
    current['bar_vwap_proxy']=(((current.high+current.low+current.close)/3)*current.volume).cumsum()/current.volume.cumsum()
    current['running_high']=current.high.cummax();current['running_low']=current.low.cummin()
    current['available_at']=current.index+pd.Timedelta(minutes=5)
    current['opening_low']=np.where(current.available_at>=start+pd.Timedelta(minutes=15),current.low.iloc[:3].min(),np.nan)
    current['below_opening_low']=current.close.lt(current.opening_low).where(current.opening_low.notna())
    return current,pd.DataFrame(levels)


def run(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    bars=pd.read_parquet(args.bars);bars.index=bars.index.tz_convert('America/New_York')
    bars=bars.loc[bars.index+pd.Timedelta(minutes=5)<=pd.Timestamp.now(tz='America/New_York')]
    current,levels=build_levels(bars,args.day)
    # Full snapshot and truncated-snapshot references must agree where both
    # were already available. No final high/low leaks into earlier signals.
    for count in (3, min(15,len(current))):
        end=current.index[count-1]+pd.Timedelta(minutes=5)
        prefix,known=build_levels(bars.loc[bars.index<end],args.day)
        expected=levels.loc[pd.to_datetime(levels.available_at,utc=True)<=end].reset_index(drop=True)
        pd.testing.assert_frame_equal(known,expected)
        pd.testing.assert_frame_equal(current.iloc[:count],prefix)
    current.to_csv(out/'SNDK_bars_and_context.csv',index_label='bar_open_et')
    levels.to_csv(out/'levels.csv',index=False)
    fig,(ax,vol)=plt.subplots(2,1,figsize=(13,8),sharex=True,gridspec_kw={'height_ratios':[4,1]})
    x=mdates.date2num(current.index.to_pydatetime());width=3.4/1440
    for j,row in enumerate(current.itertuples()):
        color='#069477' if row.close>=row.open else '#db4d56'
        ax.vlines(x[j],row.low,row.high,color=color,linewidth=1)
        ax.add_patch(Rectangle((x[j]-width/2,min(row.open,row.close)),width,max(abs(row.close-row.open),.02),color=color))
        vol.bar(x[j],row.volume/1000,width=width,color=color)
    ax.plot(x,current.bar_vwap_proxy,color='#9771c4',label='OHLCV VWAP proxy',linewidth=1.7)
    end=current.available_at.iloc[-1]
    chosen=levels.loc[levels.kind.isin(['previous_high','previous_close','opening_15m_low','confirmed_swing_high','confirmed_swing_low'])]
    labelled=set()
    for r in chosen.itertuples():
        start=pd.Timestamp(r.available_at)
        if start>=end:continue
        color='#2874a6' if 'low' in r.kind else '#c98525'
        ax.hlines(r.price,mdates.date2num(start.to_pydatetime()),mdates.date2num(end.to_pydatetime()),linestyles='dashed',alpha=.65,color=color)
        if round(r.price,1) not in labelled:
            ax.annotate(f'${r.price:,.2f}',(mdates.date2num(end.to_pydatetime()),r.price),xytext=(4,0),
                        textcoords='offset points',va='center',fontsize=8,color=color)
            labelled.add(round(r.price,1))
    ax.set_title(f'SNDK | {args.day} | Completed bars through {end.strftime("%H:%M")} ET\nReference levels start when observable; no future pivots backfilled')
    ax.set_ylabel('Price ($)');vol.set_ylabel('Volume\n(thousands)')
    ax.legend(loc='lower left');ax.grid(alpha=.15);vol.grid(alpha=.15)
    vol.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=ZoneInfo('America/New_York')))
    vol.xaxis.set_major_locator(mdates.MinuteLocator(byminute=[0,15,30,45],tz=ZoneInfo('America/New_York')))
    ax.set_xlim(x[0]-4/1440,mdates.date2num(end.to_pydatetime())+9/1440)
    fig.tight_layout();fig.savefig(out/'SNDK_levels.png',dpi=160);plt.close(fig)
    below=current.loc[current.below_opening_low.eq(True)]
    summary=dict(symbol='SNDK',day=args.day,as_of=end.isoformat(),last_completed_close=float(current.close.iloc[-1]),
        vwap_ohlcv_proxy=float(current.bar_vwap_proxy.iloc[-1]),first_close_below_opening_low=None if below.empty else below.available_at.iloc[0].isoformat(),
        source='Yahoo OHLCV via project data_manager; saved provider snapshot, not consolidated tick VWAP',
        source_sha256=hashlib.sha256(Path(args.bars).read_bytes()).hexdigest(),
        pivot_confirmation='2 observed bars each side; confirmed at rightmost bar close; descriptive convention',
        tests=['prefix reference availability equality','prefix causal context equality'],strategy_modified=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2))
    (out/'REPORT.md').write_text('# SNDK支撑压力观察\n\n截至 '+end.isoformat()+
        '，最后完整K线收盘 $'+f'{current.close.iloc[-1]:.2f}'+
        '。这是历史报价参考区域，未证明碰线反转或突破必延续。\n\n![价位图](SNDK_levels.png)\n\n'+
        levels.to_markdown(index=False)+'\n\nOHLCV典型价加权的日内VWAP代理约 $'+f'{current.bar_vwap_proxy.iloc[-1]:.2f}'+
        '，不是逐笔VWAP或盘口挂单。\n\n价位首次可用时间见available_at；确认摆动点需等待右侧两根K线结束，不能提前使用。\n\n'+
        '最新候选支撑应从confirmed_swing_low行读取，形成时间和确认时间不同；这些价位尚未证明未来会再次守住。'+
        '\n\n[方法参考：Fidelity支撑与压力](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/support-and-resistance?print=true-0)。'+
        '\n\n本次新增行情诊断报告，未新增自动交易规则。\n')
    (out/'SHA256SUMS.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.name!='SHA256SUMS.json'},indent=2))
    print(json.dumps(summary));print(levels.to_string(index=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bars',required=True);p.add_argument('--day',default='2026-09-15');p.add_argument('--output',required=True)
    run(p.parse_args())
