#!/usr/bin/env python3
"""Readable report of all extension trials, without selecting hidden winners."""
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
from app.research.artifacts import load_platform_results

def report(bundle,output):
    bundle=Path(bundle);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    payload=load_platform_results(bundle)
    if payload['status']!='complete':raise ValueError(payload.get('reason'))
    r=payload['research'];trials=r['trials']
    complete=[t for t in trials if t['status']=='complete' and t['cost_bps']==5]
    lookup={t['candidate']['name']:t for t in complete}
    best=lookup[r['retrospective_best']];selected=lookup[r['selected_for_future_paper']];control=lookup['four_tree_h1']
    delta=best['summary']['net_pnl']-control['summary']['net_pnl']
    lines=['# Alpha 扩展：实现、复算与取舍','',
        '**全部美元数字都是 $100,000 起始资金的历史模拟，不是账户已赚金额。**',
        '日期：2026-08-31 至 2026-09-11，共 9 个交易日；截至本次研究最新完整交易日。','',
        f"事先登记 27 个候选、2/5 bps 两档单边成本；完成 {sum(t['status']=='complete' for t in trials)} 次，最终未完成 {r['failed_trials']} 次；另有五类因数据缺失无法评估的方向。所有尝试保留。",
        f"其中 {r.get('initial_failed_trials',0)} 次初始 QP 数值不收敛已改用同一目标的 SLSQP 重试完成；原失败保留在 prior_attempts，重试源码与产物保留在 numerical_retry。未通过改变模型、预测或成本解决数值问题。",
        '',f"本轮全区间事后最高为 `{best['candidate']['name']}`：5 bps 下净收益 **${best['summary']['net_pnl']:,.2f}**，相对原树模型 **${delta:+,.2f}**（{delta/control['summary']['net_pnl']:+.2%}）。这是多次尝试后的探索结果。",
        f"提升可分为毛盈亏增加 ${best['summary']['gross_pnl']-control['summary']['gross_pnl']:,.2f}、模拟成本减少 ${control['summary']['costs']-best['summary']['costs']:,.2f}。这来自交易股票池与配仓变化；其余股票仍使用同样的四股树模型预测。",
        f"按预登记的前五日净收益规则选出 `{selected['candidate']['name']}`，随后四日净收益 **${selected['subsequent_period']['net_pnl']:,.2f}**；这四日也已在以前研究中使用，不是未见测试集。",
        '', '## 全部可运行候选','', '| 候选 | 2 bps 净盈亏 | 5 bps 净盈亏 | 5 bps 成本 | 最大回撤 | 前五日 | 后四日 |','|---|---:|---:|---:|---:|---:|---:|']
    rows=[]
    for c in r['candidates']:
        ts=[t for t in trials if t['candidate']['name']==c['name']]
        a=next(t for t in ts if t['cost_bps']==2);b=next(t for t in ts if t['cost_bps']==5)
        if b['status']!='complete' or a['status']!='complete':
            lines.append(f"| {c['name']} | {a['status']} | {b['status']} | — | — | — | — |")
            continue
        s=b['summary'];lines.append(f"| {c['name']} | ${a['summary']['net_pnl']:,.2f} | ${s['net_pnl']:,.2f} | ${s['costs']:,.2f} | {s['max_drawdown']:.2%} | ${b['selection_period']['net_pnl']:,.2f} | ${b['subsequent_period']['net_pnl']:,.2f} |")
        rows.append(dict(candidate=c['name'],net_2bps=a['summary']['net_pnl'],net_5bps=s['net_pnl'],costs_5bps=s['costs'],drawdown_5bps=s['max_drawdown'],first_five=b['selection_period']['net_pnl'],last_four=b['subsequent_period']['net_pnl']))
    pd.DataFrame(rows).to_csv(output/'comparison.csv',index=False)
    lines+=['','后四日资金承接前五日，未重新设为 $100,000；不能直接与旧“周初重置资金”表混算。','', '## 最优候选逐股与逐日归因','', '| 标的 | 毛盈亏 | 成本 | 净盈亏 |','|---|---:|---:|---:|']
    for symbol,s in best['per_symbol'].items():lines.append(f"| {symbol} | ${s['net_pnl']+s['costs']:,.2f} | ${s['costs']:,.2f} | ${s['net_pnl']:,.2f} |")
    lines+=['','| 日期 | 原树模型净盈亏 | 本轮最高候选净盈亏 | 差额 |','|---|---:|---:|---:|']
    base=pd.read_csv(bundle/'four_tree_h1_cost5/daily.csv');winner=pd.read_csv(bundle/f"{best['candidate']['name']}_cost5/daily.csv")
    difference=winner.net_pnl-base.net_pnl
    for i,row in winner.iterrows():lines.append(f"| {row.date} | ${base.net_pnl.iloc[i]:,.2f} | ${row.net_pnl:,.2f} | ${difference.iloc[i]:+,.2f} |")
    lines+=['',f"逐日差额均值 ${difference.mean():,.2f}，按日期计算的描述性标准误 ${difference.std(ddof=1)/np.sqrt(len(difference)):,.2f}。只有九日且做过多次选择，不能用该数宣称统计显著或稳定 Alpha。",'', '## 逻辑具体改动','',
        '- 保留精确原版对照；所有候选沿用真实股数、现金、次根开盘、成本及逐笔归因账本。未通过加杠杆或降低成本假设制造提升。',
        '- 预测未来 5/15/30/60 分钟可执行收益，标签须覆盖每根中间行情并在当日平仓前成熟；收盘前缩短剩余预测期。每根五分钟仍可重新配仓，并不保证持有满预测周期。',
        '- 增加跨股票 Ridge/浅树/LightGBM、波动率缩放目标，以及去除蜡烛形态特征的对照。模型直接预测收益，没有手工拼接的交易胜率。',
        '- 原四股分别做一次去除标的对照，保留四股输入特征；不能将事后删除亏损股票当作可重复选股能力。',
        '- 扩展面板共 31 个行情资产，其中 7 个为参考资产、24 个用于广泛股票池策略；原四股对照仍保持原输入。广泛股票池与四股同时改变了机会和参考特征，不能解释成单一效果。',
        '- 活跃股策略在 09:35 用第一根已完成 K 线的隔夜缺口和历史同一时段相对成交量排序，选八股；不使用全天振幅，也不冒充 09:25 盘前选股。八股容量是明示实验参数。',
        '- 行业/市场/加密参考残差使用过去估计的 beta；组合增加估计的共同参考风险。参考映射是研究设定，非经核验的历史官方行业归属。',
        '- NVDA/AMD、NVDA/TSM、MSTR/IBIT 用过去价格估计对冲比率，再训练未来价差收益；同时计两腿风险与换手成本，整股成交后对冲比率会有舍入偏差。没有声称价差必回归或无风险套利。',
        '- 共用 ResearchRuntime 支持历史回放和未来本地纸面决策，未来记录冻结来源与依赖并保留输入校验链。该记录器只记录目标，不伪造成交或净值。Lab 增加本轮全部候选、归因和未验证项。','', '## 数据不足的方向','']
    for t in trials:
        if t['cost_bps']==5 and t['status']!='complete':lines.append(f"- `{t['candidate']['name']}`：{t.get('reason','运行失败').rstrip('。')}。")
    lines+=['','追加免费接口探测已实际运行：Yahoo 返回 NVDA、TSLA、MSTR 的盘前五分钟行情，但盘前正成交量行数均为 0，不能据此计算可信 RVOL。NVDA、TSLA 财报表有返回，尚无历史预期修订和当时可用时间证明。原始探测结果见 `reports/free_extended_probe_20260913/probe.json`；没有把缺失量能填成可交易 Alpha。']
    lines+=['','限价单可能不成交，不能只把回测成本从 5 bps 改为 1 bps 后称为执行优化。[Alpaca 官方订单说明](https://docs.alpaca.markets/us/docs/orders-at-alpaca)。',
        'PEAD 文献展示了事件策略的研究价值，也显示交易成本可能抵消相当多的纸面利润；不能据此承诺财报后稳定上涨。[原研究](https://business.columbia.edu/faculty/research/liquidity-and-post-earnings-announcement-drift)。',
        '其他理论的来源、假设纠正和适用边界见 [LOB 与执行研究说明](../../docs/lob_data_and_execution.md)。','', '## 未验证项','']+['- '+x for x in r['unverified_assumptions']]
    audit_root=ROOT/'reports/extended_audit_20260913/ledger'
    daily_audit=json.loads((audit_root/'audit.json').read_text())
    continuous=json.loads((audit_root/'continuous_period_audit.json').read_text())
    daily_total=sum(x['fifo_realized_before_fees'] for x in daily_audit['daily'])
    continuous_total=sum(x['fifo_realized_before_fees'] for x in continuous['symbols'].values())
    lines+=['',f'本地订单镜像复核产物位于 `reports/extended_audit_20260913/ledger/`。每天零底仓假设下，九日四股 FIFO 已配对费前合计 ${daily_total:,.2f}；跨日保留库存、只假设区间初始零底仓时，已配对费前合计 ${continuous_total:,.2f}。期末 SNDK 净数量变化 +20 股、TSLA -105 股，未包含未配对库存的期末估值。缺少真实期初库存、净值与费用，两者都不能视作已核实的完整账户损益。','',
        '## 复现与接入','',
        '```bash','OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/run_extended_research.py --retry-solver --output reports/extended_research_NEW',
        'python3 scripts/report_extended_research.py --bundle reports/extended_research_NEW --output reports/extended_report_NEW',
        'python3 scripts/shadow_extended_research.py register --bundle reports/extended_research_NEW --directory reports/extended_forward_NEW',
        'python3 scripts/shadow_extended_research.py record --directory reports/extended_forward_NEW --bars PATH_TO_FRESH_31_SYMBOL_BARS --account-snapshot PATH_TO_PAPER_SNAPSHOT',
        '```','',
        '纸面快照须含 `simulation: true`、带时区的 `timestamp`、`equity` 和所交易标的完整 `shares`。行情目录含研究面板的全部参考资产与历史训练行情。预测记录需要注册后新鲜完成的数据；等权开盘基准在 09:25–09:30 预先记录当日目标，不使用当日未来行情。旧历史不能充当未来表现。',
        '没有更改 live_runner、没有提交订单。默认实盘仍为原有价格 Ridge；新研究候选尚未取得真实成交或未来盈利证据。']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    fig,ax=plt.subplots(figsize=(11,5))
    for name in dict.fromkeys(['four_tree_h1','four_price_ridge_h1',r['retrospective_best'],r['selected_for_future_paper']]):
        d=pd.read_csv(bundle/f'{name}_cost5/daily.csv');ax.plot(range(10),[100000,*d.ending_equity],marker='.',label=name)
    ax.axvline(5,color='gray',linestyle='--',label='Selection ends (reused dates)')
    ax.set(title='Exploratory simulation: USD 100,000, 5 bps per side',xlabel='Session: Aug 31 to Sep 11, 2026',ylabel='Simulated equity (USD)')
    ax.grid(alpha=.2);ax.legend(fontsize=8);fig.tight_layout();fig.savefig(output/'equity.png',dpi=160);plt.close(fig)
    print(json.dumps(dict(best=best['candidate']['name'],net_pnl=best['summary']['net_pnl'],improvement=delta,selected_for_future=selected['candidate']['name'],subsequent_net=selected['subsequent_period']['net_pnl']),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();report(args.bundle,args.output)
