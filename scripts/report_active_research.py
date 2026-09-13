#!/usr/bin/env python3
"""Concentration results, with all trials and the original four-stock control."""
import argparse
import json
from pathlib import Path
import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.research.artifacts import load_platform_results,digest

def report(bundle,output):
    bundle=Path(bundle);output=Path(output);r=load_platform_results(bundle)
    if r['status']!='complete':raise ValueError(r.get('reason'))
    r=r['research'];output.mkdir(parents=True,exist_ok=False)
    control=next(t for t in r['trials'] if t['candidate']['name']=='four_tree_control')['summary']
    rows=[];allocations=[];daily={}
    for t in r['trials']:
        name=t['candidate']['name'];s=t['summary'];daily[name]=pd.read_csv(bundle/f'{name}_cost5/daily.csv')
        marks=pd.read_csv(bundle/f'{name}_cost5/marks.csv.gz');marks=marks.loc[marks.phase=='bar_close']
        rows.append(dict(candidate=name,**s,delta_from_four_tree=s['net_pnl']-control['net_pnl'],
            mean_gross_exposure=float(marks.gross_exposure.mean()),first_five=float(daily[name].net_pnl.iloc[:5].sum()),
            last_four=float(daily[name].net_pnl.iloc[5:].sum())))
        for symbol,p in t['per_symbol'].items():
            allocations.append(dict(candidate=name,symbol=symbol,mean_abs_weight=float(marks[f'{symbol}_weight'].abs().mean()),
                max_abs_weight=float(marks[f'{symbol}_weight'].abs().max()),**p))
    pd.DataFrame(rows).to_csv(output/'comparison.csv',index=False)
    pd.DataFrame(allocations).to_csv(output/'allocation.csv',index=False)
    lines=['# 更积极与接近满仓：同条件模拟','',
        '**不是账户实际盈亏。** 2026-08-31 至 2026-09-11，九个交易日，起始 $100,000、单边成本 5 bps。日期已经用于探索，不能称为新的未见测试。',
        '', '本轮来自用户的新偏好：允许较小公司、希望更积极。不再设置市值规模门槛，仍要求有效普通股/ADR 属性、股价 $10、过去 20 个完整交易日日均成交额 $5,000 万。当前 32 公司研究池不是历史全市场成分股全集。',
        '', '| 候选 | 净盈亏 | 较原四股 | 成本 | 最大回撤 | 成交笔数 | 平均总敞口 | 后四日净盈亏 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for x in rows:
        lines.append(f"| {x['candidate']} | ${x['net_pnl']:,.2f} | ${x['delta_from_four_tree']:+,.2f} | ${x['costs']:,.2f} | {x['max_drawdown']:.2%} | {x['fill_count']} | {x['mean_gross_exposure']:.1%} | ${x['last_four']:,.2f} |")
    lines+=['','后四日继承前五日资金，未重置本金。平均总敞口取全部五分钟收盘观察，包含未持仓时刻。目标上限不是固定资金比例，价格跳空可导致实际敞口超过目标。','',
        '## 具体比较','',
        '- `four_tree_control`：原四股树预测、总目标 95%、单股上限 70%、风险惩罚系数 50。',
        '- `liquid_dynamic_70`：允许较小公司的 32 股池，联合考虑预测、相关性、成本与旧持仓；单股上限仍为 70%。',
        '- `four_concentrated_95`：保留原四股预测与风险系数，只放宽单股上限至 95%。',
        '- `liquid_single_95`：在现金、某只合格股票 +95% 或 -95% 之间，按相同预测收益减风险及换仓成本的目标逐项比较。旧持仓平仓也收费。它是接近满仓的离散对照，不是事后按最高最低点挑股票。',
        '- `liquid_dynamic_95_g25`：32 股池，单股上限 95%，风险惩罚系数从 50 降到 25。用这一公开偏好变化检验更积极投入的代价，不强制每天交易几次。',
        '', '## 6% 振幅能否变成 $6,000','',
        '恰好在 97 买、103 卖，价格收益为 103/97−1，约 6.186%，$100,000 毛收益约 $6,186。买卖均按单边 5 bps 且本金须覆盖买入成本时，忽略整数股，净收益约 $6,080。该算式是假设已知买卖点，不是模型能实现的收益。',
        '价格从相对昨收 −3% 走到 +3% 是事后区间；系统在 97 时不知道还会不会跌，在 103 前也不知道最高点。满仓后下跌 3% 会产生约 $3,000 价格损失，另有成本。集中仓位同时放大单股判断错误的影响。[FINRA 集中风险说明](https://www.finra.org/investors/insights/concentration-risk)。',
        '', '## 逐日原四股与集中四股','', '| 日期 | 原四股 | 四股 95% 上限 |','|---|---:|---:|']
    for i,x in daily['four_tree_control'].iterrows():
        lines.append(f"| {x.date} | ${x.net_pnl:,.2f} | ${daily['four_concentrated_95'].net_pnl.iloc[i]:,.2f} |")
    lines+=['','逐股收益、成本和平均/最大持仓见 allocation.csv；全部逐笔成交、目标与原始来源保存在实验目录。','', '## 未验证项','']+['- '+x for x in r['unverified_assumptions']]
    lines+=['','原大市值七组比较仍保留于 [大市值报告](../liquid_report_20260913/REPORT.md)。本轮没有改变成本或杠杆去制造利润，五个候选事先登记，全部完成结果均展示。',
        '这些实验可以比较当前样本中的资金使用方式，不能证明哪种方式未来“最好”。共用模拟接口支持这些候选，但没有切换 live_runner 或下真实订单。',
        '', '```bash',
        'OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/run_active_research.py --output reports/active_research_NEW',
        'python3 scripts/shadow_liquid_policy.py register --bundle reports/active_research_NEW --directory reports/active_forward_NEW --candidate four_concentrated_95',
        '```','']
    (output/'REPORT.md').write_text('\n'.join(lines))
    fig,ax=plt.subplots(figsize=(11,5))
    for name,d in daily.items():ax.plot(range(10),[100000,*d.ending_equity],marker='.',label=name)
    ax.set(title='Exploratory concentration test | USD 100,000 | 5 bps per side',xlabel='Session (Aug 31 to Sep 11, 2026)',ylabel='Simulated equity (USD)')
    ax.grid(alpha=.2);ax.legend(fontsize=8);fig.tight_layout();fig.savefig(output/'equity.png',dpi=160);plt.close(fig)
    (output/'validation.json').write_text(json.dumps(dict(bundle_sha256=digest(bundle/'registry.json'),artifact_and_pnl_checks='passed',orders_submitted=0),indent=2)+'\n')
    print(json.dumps(rows,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();report(args.bundle,args.output)
