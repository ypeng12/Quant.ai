#!/usr/bin/env python3
"""Report revised models without promoting a hindsight winner to trading."""
import argparse,json,sys
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.research.artifacts import load_platform_results,digest

def report(bundle,output):
    bundle=Path(bundle);output=Path(output);result=load_platform_results(bundle)
    if result['status']!='complete':raise ValueError(result.get('reason'))
    r=result['research'];output.mkdir(parents=True,exist_ok=False)
    lookup={t['candidate']['name']:t for t in r['trials']};base=lookup['four_tree_control'];rows=[];daily={}
    for name,t in lookup.items():
        d=pd.read_csv(bundle/f'{name}_cost5/daily.csv');daily[name]=d
        rows.append(dict(candidate=name,**t['summary'],delta_from_control=t['summary']['net_pnl']-base['summary']['net_pnl'],
            sndk_net_pnl=t['per_symbol']['SNDK']['net_pnl'],sndk_sep4_net_pnl=float(d.loc[d.date=='2026-09-04','SNDK_net_pnl'].iloc[0]),
            first_five=float(d.net_pnl.iloc[:5].sum()),last_four=float(d.net_pnl.iloc[5:].sum())))
        training=json.loads((bundle/f'{name}_cost5/training.json').read_text())
        assert all(x['last_train']<day['day'] for day in training for x in day['training'])
    pd.DataFrame(rows).to_csv(output/'comparison.csv',index=False)
    selected=lookup['market_tree_h1'];delta=selected['summary']['net_pnl']-base['summary']['net_pnl']
    lines=['# 四股方向模型修改：实际结果与接入范围','',
        '**全部金额为历史模拟，不是账户实盘盈利。** 初始 $100,000，单边成本5 bps，2026-08-31 至 09-11 共九个交易日。交易股票仍为 SNDK、TSLA、MSTR、NVDA。',
        '',f"新模型中净收益最高的 `market_tree_h1` 为 ${selected['summary']['net_pnl']:,.2f}，相对原四股 ${delta:+,.2f}。SNDK 的两周贡献从 ${base['per_symbol']['SNDK']['net_pnl']:,.2f} 变为 ${selected['per_symbol']['SNDK']['net_pnl']:,.2f}；局部改善不能当作组合整体改善。没有新模型自动进入实盘。",
        '', '| 模型 | 四股净盈亏 | 较原对照 | 成本 | 最大回撤 | SNDK两周 | SNDK 9/4 | 后四日组合 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for x in rows:
        lines.append(f"| {x['candidate']} | ${x['net_pnl']:,.2f} | ${x['delta_from_control']:+,.2f} | ${x['costs']:,.2f} | {x['max_drawdown']:.2%} | ${x['sndk_net_pnl']:,.2f} | ${x['sndk_sep4_net_pnl']:,.2f} | ${x['last_four']:,.2f} |")
    lines+=['','后四日资金承接前五日，未重置本金。全部六组在执行前列入候选；这些日期此前已反复研究，不是未见测试。',
        '', '## 实际修改的模型逻辑','',
        '代码：`backend/app/research/direction_policy.py`。历史重算：`scripts/run_direction_research.py`。未来模拟接口：`scripts/shadow_direction_policy.py`。Lab 增加“四股方向模型修改”研究入口。',
        '', '1. **保持四股彼此特征不变，再加入明确参考。** SPY用于市场输入；SNDK/NVDA参考SOXX，TSLA参考QQQ，MSTR参考IBIT。参考资产不参与交易，也不把ETF当作完整官方行业成分股数据。',
        '2. **增加相对强弱输入。** 参考资产的5/15/60分钟收益、日内累计收益、VWAP距离、时段量能，以及个股相对参考收益、过去估计beta后的残差、截至当时的回撤与反弹。VWAP仍是五分钟典型价乘成交量近似，不是真实逐笔VWAP。',
        '3. **改变训练目标并做对照。** 在保留5分钟目标的基础上，分别训练30分钟树/Ridge、60分钟树。标签从下一根开盘到对应未来K线收盘，只能用此前交易日内已成熟标签训练。没有用9月4日上涨作为目标方向覆盖。',
        '4. **实现30分钟多期配置。** Ridge分别预测5分钟与30分钟累计收益，之后五段收益用两者差额均分形成近似期限结构；优化六步持仓和换仓，计入中间换手与假设的期末退出成本，只执行第一步。下一根K线再预测和规划。',
        '5. **对齐风险与持仓序列。** 单周期方案使用相应周期历史标签协方差；多期方案用过去交易日连续六段、跨四股的收益协方差，保留时间和股票间关系。临近15:55按剩余可交易区间缩短计划，不延长到隔夜。',
        '', '多期交易的目标、只执行第一步和滚动重算参考 [Boyd 等的凸优化框架](https://arxiv.org/abs/1705.00109)。该论文也明确不提供解决市场预测本身的方法；采用优化框架不代表Alpha已经有效。',
        '', '## 为什么仍不能说大方向解决了','',
        '- 9月4日SNDK涨约9.73%是事后事实。当日模型10:20和10:45出现少数强烈看空预测，其余多数仅约+1.3 bps；旧组合有60个空头持仓区间。这里的空头是做空，不是无仓位。此前审计见 `reports/direction_audit_20260913_v2/`。',
        '- 5分钟预测看涨与全天上涨是不同命题；本轮改变预测周期后仍出现较大亏损，说明预测泛化能力还不足，不能把问题全部归因于费用或执行。',
        '- 新市场输入让SNDK两周贡献改善，但也改变其他股票的预测和联合配仓，因此总收益下降。不能事后只给赚钱股票选新模型、给其他股票留旧模型，再声称验证成功。',
        '- 多期配置在合成测试中能退出单周期成本目标继续保留的空头，但真实历史的总收益仍为负。正确实现一种机制，不等于证明整套策略盈利。',
        '', '## 近似与未验证条件','',
        '- 将5分钟与30分钟预测差额均分，只是期限结构近似；不能称为已训练的每个未来转折点预测。',
        '- 优化在当前净值比例上规划未来仓位，不能预知未来价格、净值与成交。终端退出只计入规划目标，不是新增每30分钟强制平仓规则。',
        '- 六段风险估计用逐段开盘至收盘收益，未精确包含所有相邻K线价格间隙；实际股数账本仍按真实后续报价路径记账。',
        '- 风险系数50、总目标95%、单股上限70%沿用对照。没有新增按亏损锁仓、时间禁买、强制做多或降低成本等规则。']+['- '+x for x in r['unverified_assumptions']]
    lines+=['','## 逐股贡献','', '| 模型 | SNDK | TSLA | MSTR | NVDA |','|---|---:|---:|---:|---:|']
    for name,t in lookup.items():lines.append('| '+name+' | '+' | '.join(f"${t['per_symbol'][s]['net_pnl']:,.2f}" for s in ('SNDK','TSLA','MSTR','NVDA'))+' |')
    lines+=['','## 复现与模拟','', '```bash',
        'OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/run_direction_research.py --output reports/direction_research_NEW',
        'python3 scripts/report_direction_research.py --bundle reports/direction_research_NEW --output reports/direction_report_NEW',
        'python3 scripts/shadow_direction_policy.py register --bundle reports/direction_research_NEW --directory reports/direction_forward_NEW --candidate market_curve_ridge',
        'python3 scripts/shadow_direction_policy.py record --directory reports/direction_forward_NEW --bars /path/to/fresh_8_asset_bars --instruments /path/to/instruments.json --account-snapshot /path/to/paper_account.json',
        '```','',
        '模拟快照须含 simulation=true、当前带时区时间、equity 和四股全部 shares。参考资产也须保留完整训练历史与同步已完成行情。记录器只输出目标和计划，不生成虚构成交或账户盈利。',
        'live_runner.py 与默认实盘模型未切换。此次代码是可审查的模型修改和研究/模拟接入；新版本尚不具备优于旧模型的整体验证证据。']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    fig,ax=plt.subplots(figsize=(11,5))
    for name,d in daily.items():ax.plot(range(10),[100000,*d.ending_equity],marker='.',label=name)
    ax.set(title='Revised direction models | USD 100,000 | 5 bps per side',xlabel='Session (Aug 31 to Sep 11, 2026)',ylabel='Simulated equity (USD)')
    ax.grid(alpha=.2);ax.legend(fontsize=8);fig.tight_layout();fig.savefig(output/'equity.png',dpi=150);plt.close(fig)
    (output/'validation.json').write_text(json.dumps(dict(bundle_sha256=digest(bundle/'registry.json'),artifact_pnl_and_training_checks='passed',orders_submitted=0),indent=2)+'\n')
    print(json.dumps(dict(best_new='market_tree_h1',best_new_net=selected['summary']['net_pnl'],improvement=delta),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();report(a.bundle,a.output)
