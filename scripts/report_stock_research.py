#!/usr/bin/env python3
"""Verified non-crypto comparison, including failed attempts and model choices."""
import argparse
import json
import sys
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.research.artifacts import load_platform_results, digest


def report(bundle, output):
    bundle, output = Path(bundle), Path(output)
    checked = load_platform_results(bundle)
    if checked['status'] != 'complete':
        raise ValueError(checked.get('reason'))
    r = checked['research']; output.mkdir(parents=True, exist_ok=False)
    trials = {t['candidate']['name']: t for t in r['trials']}
    baseline = trials['noncrypto_context_tree']['summary']['net_pnl']
    rows, daily = [], {}
    for name, t in trials.items():
        daily[name] = pd.read_csv(bundle / f'{name}_cost5/daily.csv')
        rows.append(dict(candidate=name, **t['summary'], improvement=t['summary']['net_pnl']-baseline))
    pd.DataFrame(rows).to_csv(output / 'comparison.csv', index=False)
    training = json.loads((bundle / 'noncrypto_stock_selector_cost5/training.json').read_text())
    choices = []
    for day in training:
        selection = day['selection']
        assert all(t['last_train'] < day['day'] for t in day['training'])
        assert all(f['last_train'] < f['validation_day'] < day['day'] for f in selection['folds'])
        for s, choice in selection['selections'].items():
            folds = [f for f in selection['folds'] if f['symbol'] == s and f['model'] == choice['model']]
            zero = sum(f['zero_forecast_mse_bps2'] for f in folds) / len(folds)
            error = choice['scores_mse_bps2'][choice['model']]
            choices.append(dict(day=day['day'], symbol=s, model=choice['model'], validation_start=selection['validation_dates'][0],
                                validation_end=selection['validation_dates'][-1], mse_bps2=error, zero_mse_bps2=zero,
                                relative_mse_improvement=1-error/zero if zero else None))
    pd.DataFrame(choices).to_csv(output / 'stock_selections.csv', index=False)
    selector = trials['noncrypto_stock_selector']; pnl = selector['summary']['net_pnl']
    best = max(trials.values(), key=lambda t: t['summary']['net_pnl'])
    lines = ['# 非加密股票：独立模型选择与统一资金分配', '',
             '**全部数字为历史模拟，不是账户已赚金额。** 2026-08-31 至 2026-09-11，九个交易日，起始 $100,000，单边成本 5 bps。', '',
             '交易池为 SNDK、TSLA、PLTR、NVDA；SPY、QQQ、SOXX 仅提供参考输入。MSTR 与 IBIT 完全不进入本轮特征、训练和风险估计。', '',
             f'逐股模型选择净盈亏 ${pnl:,.2f}，相对同股票池基础树模型改善 ${pnl-baseline:+,.2f}。四组事后最高为 `{best["candidate"]["name"]}`，净盈亏 ${best["summary"]["net_pnl"]:,.2f}；排名不构成未来优势证明。', '',
             '| 方法 | 净盈亏 | 相对基础树模型 | 成本 | 最大回撤 | 成交笔数 |', '|---|---:|---:|---:|---:|---:|']
    for x in rows:
        lines.append(f'| {x["candidate"]} | ${x["net_pnl"]:,.2f} | ${x["improvement"]:+,.2f} | ${x["costs"]:,.2f} | {x["max_drawdown"]:.2%} | {x["fill_count"]} |')
    lines += ['', '## 模型实际如何区别每只股票', '',
              '旧代码已经为每只股票单独拟合模型，本次新增的是逐股选择模型类型和输入组。三种候选为量价/时段树模型、大盘/行业树模型、大盘/行业 Ridge；所有预测目标统一为下一根可执行五分钟收益。',
              '每个交易日开盘前，对此前五个完整交易日分别做一次过去训练、随后一天验证。每只股票独立选择日均平方预测误差最低的候选，再用当天以前的数据重新拟合。每个验证日的训练截止必须早于验证日；选择不使用当天标签或当天盈亏。候选和规则在本轮计算前已写入 preregistration.json。',
              '五日窗口、树深度3/叶子40、Ridge正则10属于明确的实验参数，并非已证实最优参数或量化公司的统一标准。五日验证统计量很不稳定；模型选择也可能增加过拟合。',
              '股票可以选中相同模型，并不强迫各股不同。没有按9月4日上涨编写SNDK强制做多，也没有按某股亏损添加锁仓。行业映射只是输入分类，不是指定买卖方向。',
              '配仓统一优化四股预测收益、历史协方差与换手成本；沿用风险系数50、总目标敞口95%、单股目标上限70%。每股并不各自拿一份十万美元。实际股数按下一根开盘价与成本后的资金预算计算；市场波动可使持有中的比例偏离目标。',
              '将预测与组合优化分开的依据可参考 [Boyd 等的交易凸优化框架](https://arxiv.org/abs/1705.00109)；论文也明确不解决收益预测本身。独立模型、优化器和更多指标都不自动构成 Alpha。', '',
              '## 逐股净贡献', '', '| 方法 | '+' | '.join(r['traded_symbols'])+' |', '|---|'+'---:|'*len(r['traded_symbols'])]
    for name, t in trials.items():
        lines.append('| '+name+' | '+' | '.join(f'${t["per_symbol"][s]["net_pnl"]:,.2f}' for s in r['traded_symbols'])+' |')
    lines += ['', '## 逐股选择模型的逐日模拟', '', '| 日期 | 四股净盈亏 | '+' | '.join(r['traded_symbols'])+' |', '|---|---:|'+'---:|'*len(r['traded_symbols'])]
    for _, row in daily['noncrypto_stock_selector'].iterrows():
        lines.append(f'| {row["date"]} | ${row["net_pnl"]:,.2f} | '+' | '.join(f'${row[s+"_net_pnl"]:,.2f}' for s in r['traded_symbols'])+' |')
    lines += ['', '## 验证边界与接入状态', '',
              '- `stock_selections.csv` 保留每天每股的模型选择、验证日期及与零收益预测的误差比较。三种候选中误差最低，不等于已经比零预测更好，更不等于交易净利润最高。',
              '- 此前不交易MSTR的约+$347实验仍保留MSTR特征，不能作为本轮完全排除加密相关输入的基准。原四股+$11,758.86也不是新股票池业绩。',
              '- 这九天已反复研究，不是冻结的未见测试集。每日仅使用过去数据避免了直接未来泄露，但不能消除研究者反复查看这段历史造成的选择偏差。',
              '- 代码已接入只读Lab，默认打开非加密股票实验；模拟决策记录器使用同一模型实现并保存逐股选择证据。未切换live_runner或下单；未来记录没有实际成交时不输出虚构PnL。']
    lines += ['- '+x for x in r['unverified_assumptions']]
    lines += ['', '## 复现', '', '```bash',
              'OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/run_stock_research.py --output reports/stock_research_NEW',
              'python3 scripts/report_stock_research.py --bundle reports/stock_research_NEW --output reports/stock_report_NEW',
              'python3 scripts/shadow_stock_policy.py register --bundle reports/stock_research_NEW --directory reports/stock_forward_NEW',
              'python3 scripts/shadow_stock_policy.py record --directory reports/stock_forward_NEW --bars /path/to/seven_asset_bars --instruments /path/to/instruments.json --account-snapshot /path/to/paper_account.json',
              '```', '', '未来输入需包含七个标的的完整历史与同步已完成行情；账户快照必须明确simulation=true，并含带时区时间、equity及四股全部shares。证券属性须在决策前已知。']
    (output / 'REPORT.md').write_text('\n'.join(lines)+'\n')
    fig, ax = plt.subplots(figsize=(10, 5))
    for name, d in daily.items():
        ax.plot(range(len(d)+1), [100000, *d.ending_equity], marker='.', label=name)
    ax.set(title='Non-crypto stocks | USD 100,000 | 5 bps per side', xlabel='Session (Aug 31 to Sep 11, 2026)', ylabel='Simulated equity (USD)')
    ax.grid(alpha=.2); ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(output/'equity.png', dpi=150); plt.close(fig)
    (output/'validation.json').write_text(json.dumps(dict(bundle_sha256=digest(bundle/'registry.json'), artifact_and_training_checks='passed', orders_submitted=0), indent=2)+'\n')
    print(json.dumps(dict(selector_net_pnl=pnl, improvement=pnl-baseline, best=best['candidate']['name']), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args(); report(args.bundle, args.output)
