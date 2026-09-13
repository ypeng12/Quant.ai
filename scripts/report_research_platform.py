#!/usr/bin/env python3
"""Build a portable report from reconciled immutable research bundles."""
from pathlib import Path
import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.research.artifacts import ROOT,load_platform_results
from app.research.catalog import BUNDLES


def main():
    root=ROOT/'reports/platform_audit_20260913';root.mkdir(exist_ok=True)
    runs={}
    for key,bundle in BUNDLES.items():
        payload=load_platform_results(ROOT/'reports'/bundle)
        if payload['status']!='complete':raise ValueError(f'{bundle}: '+payload['reason'])
        runs[key]=payload['research']
    find=lambda key,name,cost:next(t for t in runs[key]['trials'] if t['candidate']['name']==name and t['cost_bps']==cost)
    def table(key):
        lines=['| Candidate | Net at 2 bps | Net at 5 bps | Costs at 5 bps | Drawdown at 5 bps |','|---|---:|---:|---:|---:|']
        for c in runs[key]['candidates']:
            a=find(key,c['name'],2);b=find(key,c['name'],5)
            if a['status']!='complete' or b['status']!='complete':lines.append(f"| {c['name']} | unavailable | unavailable | — | — |")
            else:
                x=a['summary'];y=b['summary'];lines.append(f"| {c['name']} | ${x['net_pnl']:,.2f} | ${y['net_pnl']:,.2f} | ${y['costs']:,.2f} | {y['max_drawdown']:.2%} |")
        return '\n'.join(lines)
    text='''# Quant platform audit and experiments — 2026-09-13

The implementation now includes actual-data ingestion, corrected L1 OFI, causal
research comparisons, joint portfolio ablations, reconciled PnL attribution, and
read-only Lab results. **All dollar results below are simulations starting with
$100,000, not money earned in the user's account.** No real account balance was
assumed from broker access. No live strategy was promoted, no orders were placed,
and no commit or push was performed.

Each comparison predeclares 12 candidate configurations and two single-side costs:
20 complete trials and four unavailable L1 trials. Models train on earlier
sessions only, use completed five-minute bars, fill at the next open, and flatten
at 15:55. The periods have already been explored; these are not untouched holdouts.

## Foundation audit and corrections

- Fixed OFI when bid/ask prices worsen: disappearing prior depth now contributes;
  resets occur per New York session. Stable event ordering is retained.
- Trade direction uses strictly earlier same-day quotes with an explicit 30-second
  tolerance. Unknown direction, no quotes, incomplete buckets, or absent L1 remain
  missing rather than becoming an invented feature.
- Historical imports preserve feed, source, original timestamps, size units, raw
  pages and normalized-file checksums. Interrupted pagination remains incomplete.
- Independent XNYS session checks detect an entirely missing trading day instead
  of silently shrinking the evaluated interval. Early closes are explicitly unsupported.
- The 30-symbol SLSQP run failed on a feasible convex allocation problem. Research
  and shadow now use OSQP for the same objective; live defaults are preserved.
  All final experiments were rerun with this solver; the failed run is retained.
- Fixed a prior **5 bps optimizer / 2 bps execution-ledger mismatch** in peer ablation.
  Its old reoptimized figures are withdrawn; see the ERRATA in the old bundle.
  Matching cost rates and symbol/cash PnL identities are now verified on every trial.
- Newly queried Yahoo history covers 30 symbols, each with 2,652 bars over 34 sessions
  (79,560 rows). Original SNDK/TSLA/MSTR/NVDA OHLCV and timestamps match the fresh query
  exactly. This is a same-vendor consistency check, not independent market-data proof.
- Yahoo returned four dividend events and no splits. Dividends are not credited to
  intraday-flat portfolios. Ex-dividend gaps remain unadjusted contextual features.
- Alpaca key/secret were absent in the local credential probe. No historical Alpaca
  entitlement or actual L1 performance is therefore established.

## Four symbols, two weeks: Aug 31–Sep 11 (9 sessions)

'''+table('four_two_weeks')+'''

## Four symbols, recent week: Sep 8–11 (4 sessions), reset to $100,000

'''+table('four_recent_week')+'''

All three final tables use the same OSQP portfolio solver. The earlier four-symbol
SLSQP tree result (+$11,055.32 over two weeks; +$4,170.78 in the recent week) is
retained in its original source-versioned bundle. The final values in these tables
supersede those interim comparisons. No fixed weekly profit has been established.
Changing the cost parameter also changes orders: fixed-order repricing is reported
separately and must not be confused with reoptimization.

The unified price Ridge uses the new common research fit/risk implementation and
is not an exact rerun of the previously frozen live-policy artifact's $4,102.05.

## Expanded 30-symbol panel, same two-week interval

'''+table('thirty_two_weeks')+'''

This broadens cross-sectional evidence, not time-series evidence. The dates are
still reused, the panel was selected today, and there are no delisted constituents.
SPY-based residual features are available here; they were absent in the four-symbol
experiment. Comparing panel totals therefore changes both available features and
portfolio opportunities and is not a pure feature ablation.

## What the portfolio changes actually do

All context Ridge portfolio variants share the same forecasts. Joint allocation
trades off expected return against shrunk covariance risk, turnover cost, and
optional forecast-error / statistical common-risk penalties. No hand-assigned
indicator score or win probability is used. Coefficients are explicit research
specifications rather than alleged universal institutional settings.

Compare the context Ridge row with the uncertainty-only, common-risk-only and
combined variants for allocation effects, holding the forecasts fixed. Lower
costs or drawdown may be accompanied by lower net returns. Ridge uncertainty is
approximate and is not a calibrated profit probability.

'''
    for name in ['context_tree','context_robust']:
        t=find('four_two_weeks',name,5)
        text+=f'### {name}, four symbols, 5 bps: per-symbol attribution\n\n| Symbol | Gross PnL | Costs | Net PnL |\n|---|---:|---:|---:|\n'
        for symbol,row in t['per_symbol'].items():
            text+=f"| {symbol} | ${row['net_pnl']+row['costs']:,.2f} | ${row['costs']:,.2f} | ${row['net_pnl']:,.2f} |\n"
        text+='\n'
    text+='''Detailed bundles also contain daily/hour/long/short attribution, decisions,
forecast errors, risk contributions, every fill, marked equity, data/source hashes,
training metadata, frozen sources and library versions. The API verifies these
artifacts before display. Hash consistency does not independently authenticate
vendor data or make exploratory results statistically conclusive.

## Forward work that is ready, and what has not happened

Three four-symbol candidates (context Ridge, shallow tree, combined portfolio)
were frozen on 2026-09-13 for future observations at 5 bps. All have **zero future
observations**. The recorder accepts fresh completed observations after the
registration time, archives inputs, and maintains a checked append-only hash chain.
It records decisions, not fictitious fills or equity. Actual/paper account PnL and
fill TCA have separate import tools. No collector, scheduled recorder, broker API
server or trading process was started by this implementation.

Remaining evidence: genuine quote/trade history and collection with configured
credentials; reconciled account exports; longer and untouched validation; actual
spread/latency/impact/borrow and funding costs; point-in-time corporate/universe data;
industry-factor analysis. Four weeks of future time cannot be generated today.

## Validation and use

99 relevant backend/replay tests and 8 subtests passed. Updated shadow tests
also passed after input archival was added. Frontend TypeScript/Vite build passed.
See `docs/quant_research_platform.md` for the 12-area status, commands, data schemas,
and resume wording supported by the implementation. Warnings include a websockets
deprecation and the existing frontend bundle-size warning.

Alpaca documents free live IEX and historical SIP with an end at least 15 minutes
old: https://docs.alpaca.markets/us/docs/market-data-faq . Account access still needs
verification. The OFI definition is based on Cont, Kukanov and Stoikov:
https://arxiv.org/abs/1011.6402 . Calendar implementation:
https://github.com/gerrymanoim/exchange_calendars . QP solver API:
https://osqp.org/docs/interfaces/python.html .
'''
    (root/'REPORT.md').write_text(text)
    names={'cash':'现金','equal_weight':'日内等权','price_ridge':'基础量价 Ridge','peer_ridge':'同组相对收益 Ridge','context_ridge':'时段/隔夜/量能 Ridge','context_tree':'时段/隔夜/量能决策树','context_lightgbm':'时段/隔夜/量能 LightGBM','context_uncertainty':'Ridge + 不确定性配置','context_common_risk':'Ridge + 共同风险配置','context_robust':'Ridge + 两项组合调整','l1_ridge':'真实 L1 Ridge','combined_robust':'真实 L1 + 量价 + 组合调整'}
    chinese='# Quant 项目：本次实现与最终复算\n\n已完成本地可以实施的研究、组合、归因和展示代码。真实 L1、实际账户盈亏及未来表现仍需真实数据。\n\n下面均为 **10 万美元起始资金的历史模拟**，并非账户已经赚到的钱。使用下一根开盘成交、假设成本和日内平仓；日期已经用于探索，不能算未见过的最终测试集。\n\n'
    for key,title in [('four_two_weeks','四只股票，两周：8 月 31 日至 9 月 11 日，9 个交易日'),('four_recent_week','四只股票，最近一周：9 月 8 日至 11 日，重新从 10 万美元起算'),('thirty_two_weeks','扩展至 30 只股票，同一两周')]:
        chinese+='## '+title+'\n\n| 候选 | 单边 2 bps 净盈亏 | 单边 5 bps 净盈亏 | 5 bps 最大回撤 |\n|---|---:|---:|---:|\n'
        for c in runs[key]['candidates']:
            a=find(key,c['name'],2);b=find(key,c['name'],5)
            if a['status']!='complete' or b['status']!='complete':chinese+=f"| {names[c['name']]} | 无真实 L1，无法评估 | 无法评估 | — |\n"
            else:chinese+=f"| {names[c['name']]} | ${a['summary']['net_pnl']:,.2f} | ${b['summary']['net_pnl']:,.2f} | {b['summary']['max_drawdown']:.2%} |\n"
        chinese+='\n'
    ridge=find('four_two_weeks','context_ridge',5)['summary'];robust=find('four_two_weeks','context_robust',5)['summary']
    tree=find('four_two_weeks','context_tree',5);week=find('four_recent_week','context_tree',5)
    chinese+=f"## 这些结果说明什么\n\n四股决策树两周模拟净赚 ${tree['summary']['net_pnl']:,.2f}，最近一周 ${week['summary']['net_pnl']:,.2f}。没有证明每周至少赚一万美元，更没有真实账户盈利记录。两周决策树结果中，MSTR 的净贡献为 ${tree['per_symbol']['MSTR']['net_pnl']:,.2f}，需关注收益集中在少数股票的问题。\n\n保持 Ridge 预测不变，加入两项组合调整后，两周成本由 ${ridge['costs']:,.2f} 降到 ${robust['costs']:,.2f}，最大回撤从 {abs(ridge['max_drawdown']):.2%} 降到 {abs(robust['max_drawdown']):.2%}，但净收益由 ${ridge['net_pnl']:,.2f} 降到 ${robust['net_pnl']:,.2f}。这体现了收益、风险与交易成本之间的取舍。\n\n"
    chinese+='成本 2 bps 是每笔成交金额的 0.02%，5 bps 是 0.05%，买入和卖出都计入。它们是模拟费率，不能当作经纪商实际扣费。改变成本参数会改变配仓和订单路径；应区分“同一订单追加成本”与“按新成本重新配仓”。\n\n## 做了什么\n\n1. 修正 OFI，保留真实报价/成交来源与时间，避免用过期或未来报价判断成交方向。\n2. 按交易所日历核对缺失交易日；历史下载保留分页、原始文件和校验值。\n3. 修复旧实验中“优化用 5 bps，账本只扣 2 bps”的错误，旧结果已附更正说明。\n4. 下载 30 只股票、34 个完整交易日，共 79,560 根五分钟行情；原四股与重新下载的数据一致。\n5. 建立 12 组候选与两档成本的统一实验，保留失败与不可用结果。\n6. 加入相关性、共同风险、预测不确定性与换手成本的联合配仓及独立对照。\n7. 为 30 股研究改用凸二次规划求解器，解决通用优化器的数值失败；最终三份表都用相同组合目标。\n8. 逐股、逐日、时段和多空方向分解毛盈亏、成本和净盈亏，并与现金账本核对。\n9. Lab 可以切换四股一周、四股两周、30 股两周，查看核验后的真实研究产物。\n10. 加入未来决策记录、输入归档和校验链；三个候选已冻结，未来观察数仍为 0。\n11. 实际账户对账与成交成本分析工具已实现，需要账户净值、资金流和真实成交导出。\n12. 复现命令、全部 12 项实施状态和可用于简历的准确表述见 `docs/quant_research_platform.md`。\n\n99 项相关测试、8 项子测试通过，前端构建通过。新候选没有自动接管实盘，没有提交或推送 Git。未来记录工具尚未作为服务运行。\n\n仍未完成的证据包括：Alpaca 实际 L1 权限与行情、真实费用和借券/冲击成本、账户策略级盈亏、长期样本外与未来结果、历史成分股和行业因子验证。Alpaca 本地凭证缺失；请在本地 `backend/.env` 配置，勿发送到聊天或提交 Git。\n\n免费实时 IEX 与历史 SIP 的权限条件参见 [Alpaca 官方 FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)。实际权限尚待账户验证。OFI 参见 [原论文](https://arxiv.org/abs/1011.6402)。\n'
    (root/'结论.md').write_text(chinese)
    fig,axes=plt.subplots(1,2,figsize=(13,4.5))
    for ax,key,title in zip(axes,['four_two_weeks','thirty_two_weeks'],['Four symbols','30 symbols']):
        for name in ['equal_weight','context_ridge','context_tree','context_robust']:
            p=ROOT/'reports'/BUNDLES[key]/f'{name}_cost5'/'daily.csv'
            f=pd.read_csv(p);ax.plot(range(len(f)+1),[100000,*f.ending_equity],marker='.',label=name)
        ax.set_title(title+' — simulated equity, 5 bps per side');ax.set_xlabel('Session (Aug 31–Sep 11)');ax.set_ylabel('USD');ax.grid(alpha=.2);ax.legend(fontsize=8)
    fig.suptitle('Retrospective exploration; not live PnL or an untouched holdout',fontsize=11)
    fig.tight_layout();fig.savefig(root/'equity_comparison.png',dpi=180);plt.close(fig)
    print(root/'REPORT.md')
if __name__=='__main__':main()
