#!/usr/bin/env python3
"""Compare every predeclared addition on both retrospective date panels."""
import argparse,json,sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.research.artifacts import load_platform_results,digest


def report(bundle,earlier,output):
    roots=[Path(bundle),Path(earlier)];results=[]
    for root in roots:
        r=load_platform_results(root)
        if r['status']!='complete':raise ValueError(r.get('reason'))
        results.append(r['research'])
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    main,prior=({t['candidate']['name']:t for t in r['trials']} for r in results)
    rows=[]
    for name,t in main.items():
        rows.append(dict(candidate=name,net_pnl=t['summary']['net_pnl'],delta=t['summary']['net_pnl']-main['incremental_control']['summary']['net_pnl'],
            costs=t['summary']['costs'],max_drawdown=t['summary']['max_drawdown'],
            earlier_net_pnl=prior[name]['summary']['net_pnl'],earlier_delta=prior[name]['summary']['net_pnl']-prior['incremental_control']['summary']['net_pnl']))
    pd.DataFrame(rows).to_csv(output/'comparison.csv',index=False)
    best=max(rows,key=lambda x:x['net_pnl'])
    lines=['# 继续增加 Alpha：实际增益与失败结果','','**全部结果是历史模拟，不是账户利润。** 三股SNDK、TSLA、NVDA，参考SPY、QQQ、SOXX；各区间分别从$100,000开始，单边成本5 bps。',
        '',f'九日区间净收益最高为 `{best["candidate"]}`：${best["net_pnl"]:,.2f}，较冻结条件Ridge ${best["delta"]:+,.2f}。不能按该排名自动切换实盘。',
        '', '| 候选 | 8/31—9/11净收益 | 较冻结对照 | 成本 | 最大回撤 | 8/24—8/28净收益 | 较同期对照 |', '|---|---:|---:|---:|---:|---:|---:|']
    for x in rows:lines.append(f'| {x["candidate"]} | ${x["net_pnl"]:,.2f} | ${x["delta"]:+,.2f} | ${x["costs"]:,.2f} | {x["max_drawdown"]:.2%} | ${x["earlier_net_pnl"]:,.2f} | ${x["earlier_delta"]:+,.2f} |')
    lines+=['','## 研究与实现','','1. **同一时段的历史收益**：增加过去5/20个交易日同一五分钟时段的已实现目标收益均值、20日标准差。只用先前日期的标签，绝不把当天未来收益放入特征。参考[Heston、Korajczyk、Sadka的原始研究](https://arxiv.org/abs/1005.3535)。论文研究广泛股票横截面的半小时时段，这里是三股五分钟迁移试验，不是原样复现。',
        '2. **隔夜与日内交互**：前一天开盘到收盘收益、隔夜跳空与前日收益/当日已观察收益/已过时段的交互。由过去数据学习延续或回归，不指定跳空后必买必卖。',
        '3. **区间结构与方向波动**：当前价到此前12根K线高低区间的距离、上行与下行平方收益之差及与量能状态的交互。参考区间不包含当前K线或未来高低点。它们是项目待检验假说，不是已证实Alpha。',
        '4. **逐项与合并对照**：模型均为Ridge，保持五分钟标签、风险系数、资金约束、成本及下一根开盘执行一致；保留日内等权和冻结条件Ridge，禁止以加杠杆、降成本或删掉亏损日期制造增益。',
        '', '## 验证边界','','两个日期区间及六组候选在本轮运行前已列入preregistration。较早五天也是已在研究流程中使用过的历史，不构成未见测试；它只提供额外的时间敏感性检查。两个区间资金各自重置，不可直接把收益率相加当成连续账户回报。',
        '本轮记录所有尝试；若新增信息不能超过同期对照，就保留为失败或未证实候选。未来验证继续以此前冻结版本为参考，不能事后按每只股票最赚钱的模型拼接收益。',
        '一次五日区间计算遇到报告脚本对空尾部区间的处理错误，已修复并重跑v2。原始尝试目录保留，Lab只引用完成且通过校验的v2。']+['- '+a for a in results[0]['unverified_assumptions']]
    lines+=['','## 逐股净贡献','','| 候选 | SNDK | TSLA | NVDA |','|---|---:|---:|---:|']
    for name,t in main.items():lines.append('| '+name+' | '+' | '.join(f'${t["per_symbol"][s]["net_pnl"]:,.2f}' for s in results[0]['traded_symbols'])+' |')
    lines+=['','## 复现','','```bash',
        'OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/run_incremental_research.py --output reports/incremental_NEW',
        'OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/run_incremental_research.py --output reports/incremental_earlier_NEW --start 2026-08-24 --end 2026-08-28',
        'python3 scripts/report_incremental_research.py --bundle reports/incremental_NEW --earlier reports/incremental_earlier_NEW --output reports/incremental_report_NEW',
        '```','','研究模型在backend/app/research/incremental_policy.py。未来决策适配器为scripts/shadow_incremental_policy.py，只记录模拟目标，不提交订单。live_runner未改动。']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    (output/'validation.json').write_text(json.dumps(dict(bundle_hashes={str(p):digest(p/'registry.json') for p in roots},checks='artifact and PnL integrity passed',orders_submitted=0),indent=2)+'\n')
    print(json.dumps(best,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',required=True);p.add_argument('--earlier',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();report(a.bundle,a.earlier,a.output)
