#!/usr/bin/env python3
"""Expose the genuine L1 diagnostic in the existing integrity-checked Lab."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.research.artifacts import load_platform_results


def run(folder,bar_folder):
    root=Path(folder).resolve();bars=Path(bar_folder).resolve()
    if (root/'registry.json').exists():raise ValueError('Do not overwrite a published experiment')
    report=json.loads((root/'result.json').read_text())
    source_hashes=json.loads((root/'source_hashes.json').read_text())
    registration=json.loads((root/'registration.json').read_text())
    symbols=[r['symbol'] for r in report['metrics']];trials=[]
    for name,s in report['results'].items():
        trials.append(dict(candidate=dict(name='holding_l1_'+name,features='real IEX + bar context' if name=='plus_l1' else 'bar context',
            model='Ridge with prior-day residual' if name=='plus_l1' else 'Ridge',portfolio='costed return curve'),
            status='complete',cost_bps=5,summary=s,
            per_symbol={symbol:dict(net_pnl=s[f'{symbol}_net_pnl'],costs=s[f'{symbol}_costs']) for symbol in symbols}))
    inputs={p.stem:p for p in bars.glob('*.parquet')}
    inputs.update({p.stem:p for p in root.glob('*_features.parquet')})
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    registry=dict(status='complete',registered_at='2026-09-14',evaluation_dates=[report['evaluation_day']],
        symbols=symbols,traded_symbols=symbols,starting_equity=47006.42,cost_bps_per_side=[5],trials=trials,
        selected_for_live=None,performance_verified=False,default_display_candidate='holding_l1_plus_l1',
        cost_description='两个候选同资金、同日期，内部规划 2 bps，成交模拟 5 bps；实际券商费用未核实。',
        unverified_assumptions=['只有 9/11 一天训练、9/14 一天评估，不能证明未来盈利。',
            '真实 IEX 单交易所历史报价与成交；历史交易所时间模型不能直接套用实时到达时间。',
            'L1 衍生特征及行情输入附哈希；原始逐笔文件留存在本地，来源哈希见 result.json。',
            '缺失完整 L1 时使用基础模型；假设下一根开盘完全成交、15:55 平仓、期初空仓。'],
        sources={str((root/'source'/name).relative_to(ROOT)):value for name,value in source_hashes.items()},
        data_paths={k:str(p.relative_to(ROOT)) for k,p in inputs.items()},data_hashes={k:digest(p) for k,p in inputs.items()},
        artifact_hashes={str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file()},metrics=report['metrics'],
        registration=registration)
    (root/'registry.json').write_text(json.dumps(registry,indent=2,allow_nan=False)+'\n')
    (root/'registry.sha256').write_text(digest(root/'registry.json')+'\n')
    check=load_platform_results(root)
    if not check['success']:raise ValueError(check['reason'])
    print('L1 Lab bundle verified')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--folder',required=True);p.add_argument('--bars',required=True)
    a=p.parse_args();run(a.folder,a.bars)
