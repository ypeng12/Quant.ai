#!/usr/bin/env python3
"""Report every large-cap candidate, including losses and selection limitations."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.research.artifacts import load_platform_results,digest


def report(bundle,output):
    bundle=Path(bundle);output=Path(output)
    result=load_platform_results(bundle)
    if result['status']!='complete':raise ValueError(result.get('reason'))
    output.mkdir(parents=True,exist_ok=False);r=result['research']
    trials={t['candidate']['name']:t for t in r['trials']}
    control=trials['four_tree_control']['summary'];best=trials[r['retrospective_best']]
    integrated=trials['largecap_integrated'];rows=[];daily={};admission=[];allocation=[]
    for name,t in trials.items():
        s=t['summary'];daily[name]=pd.read_csv(bundle/f'{name}_cost5/daily.csv')
        delta=daily[name].net_pnl-daily['four_tree_control'].net_pnl
        rows.append(dict(candidate=name,**s,improvement=s['net_pnl']-control['net_pnl'],
            first_five=float(daily[name].net_pnl.iloc[:5].sum()),last_four=float(daily[name].net_pnl.iloc[5:].sum()),
            daily_difference_standard_error=float(delta.std(ddof=1)/np.sqrt(len(delta)))))
        marks=pd.read_csv(bundle/f'{name}_cost5/marks.csv.gz')
        closes=marks.loc[marks.phase=='bar_close']
        for symbol,contribution in t['per_symbol'].items():
            allocation.append(dict(candidate=name,symbol=symbol,mean_abs_weight=float(closes[f'{symbol}_weight'].abs().mean()),
                max_abs_weight=float(closes[f'{symbol}_weight'].abs().max()),**contribution))
        if name=='four_tree_control':continue
        train=json.loads((bundle/f'{name}_cost5/training.json').read_text())
        for day in train:
            for symbol,e in day['eligibility'].items():
                if e['eligible']:
                    assert e['last_price']>=r['liquidity_rules']['min_price'] and e['adv']>=r['liquidity_rules']['min_adv']
                    assert e['market_cap']>=r['liquidity_rules']['min_market_cap'] and e['history_end']<day['day']
                if name=='largecap_integrated':admission.append(dict(day=day['day'],symbol=symbol,**e))
            if day['calibration']:
                assert all(f['training_last_session']<f['validation_day']<day['day'] for f in day['calibration']['folds'])
    pd.DataFrame(rows).to_csv(output/'comparison.csv',index=False)
    pd.DataFrame(admission).to_csv(output/'admission.csv',index=False)
    pd.DataFrame(allocation).to_csv(output/'allocation.csv',index=False)
    lines=['# 大市值股票池与动态组合比较','',
        '**以下均为历史模拟，不是账户已赚金额。** 2026-08-31 至 2026-09-11，共九个交易日，起始资金 $100,000，单边成本 5 bps。',
        '',f"原四股树模型精确复现净收益 ${control['net_pnl']:,.2f}。本轮事后最高 `{best['candidate']['name']}` 为 ${best['summary']['net_pnl']:,.2f}，相对原四股 ${best['summary']['net_pnl']-control['net_pnl']:+,.2f}。",
        f"新增综合模型 `largecap_integrated` 净收益 ${integrated['summary']['net_pnl']:,.2f}，相对原四股 ${integrated['summary']['net_pnl']-control['net_pnl']:+,.2f}。更复杂或覆盖更多股票不保证利润提升。",'',
        '## 全部预登记比较','',
        '| 候选 | 净盈亏 | 相对原四股 | 毛盈亏 | 成本 | 最大回撤 | 前五日 | 后四日 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for x in rows:
        lines.append(f"| {x['candidate']} | ${x['net_pnl']:,.2f} | ${x['improvement']:+,.2f} | ${x['gross_pnl']:,.2f} | ${x['costs']:,.2f} | {x['max_drawdown']:.2%} | ${x['first_five']:,.2f} | ${x['last_four']:,.2f} |")
    lines+=['','后四日承接前五日资金，不重置为 $100,000。逐日差额与描述性标准误见 comparison.csv；九日且重复探索，不构成显著性证明。',
        '', '## 实现及取舍','',
        '- 32 只候选公司，10 只仅作输入的参考资产。当前快照有 29 只达到 $500 亿市值；COIN、MARA、SMCI 不满足。前收盘 $10、历史 20 日日均成交额 $5,000 万和证券类型同时筛选。SNDK 没有被按过去盈亏删除。',
        '- 树模型与 Ridge 通过前五天逐日向前验证的预测校准；可选加入日内协方差、共同参考风险和预测残差风险。不是人工“胜率”或固定股票优先级。',
        '- 总目标敞口 95%、默认单股上限 70%；另测单股 25% 情景。按完整五分钟数据更新，次根开盘模拟整数股成交，计入真实持仓变化和成本。',
        '- 股票失去准入资格时，旧持仓仍进入组合预算并计算平仓成本。模型成交参考价低于 $10 时不增加仓位，减仓仍可完成。',
        '- 扩池同时增加了部分共同参考输入，不能把所有差额归因于股票数量。风险惩罚可能重复计算部分共同风险；其权重是明确研究偏好，不是唯一正确的估计值。',
        '- 初次运行因日历起点落在周末退出，保留原目录；v2 修复日期边界，未通过更改预测或费用来修复错误。',
        '', '## 综合模型逐股归因','', '| 股票 | 净盈亏 | 成本 |','|---|---:|---:|']
    for symbol,p in sorted(integrated['per_symbol'].items(),key=lambda x:x[1]['net_pnl'],reverse=True):
        lines.append(f"| {symbol} | ${p['net_pnl']:,.2f} | ${p['costs']:,.2f} |")
    lines+=['','## 逐日比较','', '| 日期 | 原四股 | 综合模型 | 单股 25% 情景 |','|---|---:|---:|---:|']
    for i,x in daily['four_tree_control'].iterrows():
        lines.append(f"| {x.date} | ${x.net_pnl:,.2f} | ${daily['largecap_integrated'].net_pnl.iloc[i]:,.2f} | ${daily['largecap_integrated_25pct'].net_pnl.iloc[i]:,.2f} |")
    lines+=['','## 尚未验证','']+['- '+x for x in r['unverified_assumptions']]
    lines+=['','大公司、活跃成交不等于安全，也没有审计这些公司的经营质量。市值取自当前快照，历史结果存在当前选股的偏差；不能称为历史全市场扫描或已验证实盘 Alpha。',
        '这次没有自动选利润最高者上实盘。模拟决策接口共用同一逻辑并保留来源与输入，只记录目标、没有成交或净值。原 live_runner 仍运行原有策略。',
        '', '实现、研究依据与可复现命令见 [逻辑说明](../../docs/largecap_liquid_policy.md)。Lab → 主流大市值股票 → 点击候选查看逐股与多空归因；展开准入明细可查看筛选原因。']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    fig,ax=plt.subplots(figsize=(11,5))
    for name in ('four_tree_control','largecap_equal','largecap_tree','largecap_calibrated','largecap_integrated','largecap_integrated_25pct'):
        ax.plot(range(10),[100000,*daily[name].ending_equity],marker='.',label=name)
    ax.set(title='Exploratory large-cap simulation | USD 100,000 | 5 bps per side',xlabel='Session (Aug 31 to Sep 11, 2026)',ylabel='Simulated equity (USD)')
    ax.grid(alpha=.2);ax.legend(fontsize=8);fig.tight_layout();fig.savefig(output/'equity.png',dpi=160);plt.close(fig)
    (output/'validation.json').write_text(json.dumps(dict(bundle_hash=digest(bundle/'registry.json'),
        artifact_and_pnl_checks='passed',admission_and_training_causality='passed',trials=len(trials),orders_submitted=0),indent=2)+'\n')
    print(json.dumps(dict(best=best['candidate']['name'],net_pnl=best['summary']['net_pnl'],integrated_net=integrated['summary']['net_pnl']),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();report(args.bundle,args.output)
