#!/usr/bin/env python3
"""Predeclared causal Alpha extensions; exclusive output, no broker access."""
import argparse
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
import sys
import json
import gzip
import traceback
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.research.strategy_extensions import EXTENSIONS, FOUR, REFERENCES, ResearchRuntime, ResearchSpec
from app.research.policy_replay import ExecutionConfig,ShareLedger,complete_universe,replay_day,summarize
from app.research.attribution import ledger_attribution
from app.research.artifacts import digest
from app.research.data_audit import audit_bars,input_provenance
from app.quant_policy import integer_targets

UNVERIFIED=[
    '[未验证] 成本：2/5 bps 是单边成交金额的模拟扣减，未核实实际价差、延迟、冲击、规费、借券及融资费用。',
    '[未验证] 期初库存：模拟以零仓位开始并每日 15:55 平仓；真实账户的期初/隔夜库存未核实。',
    '[未验证] 净值与出入金：固定 $100,000 是模拟资金，未与真实账户净值及入出金对齐。',
    '现选股票池、已探索日期、无退市股，存在选股与多重尝试偏差；后四日也不是未接触过的最终测试集。',
    '下一根开盘成交是理想化延迟假设；空头假设可借，未验证历史可借数量或借券费。',
]
UNAVAILABLE={
    'real_l1_prediction':'没有真实留存报价/成交样本，无法验证 L1 与 ML 的增量收益。',
    'l1_limit_execution':'没有逐笔报价、订单响应、排队和真实成交数据；不能假定限价必成交或把成本降到 1 bps。',
    'earnings_pead':'没有当时可见的财报、预期、指引及公告时间历史，不能回填今天的数据制造历史 Alpha。',
    'index_rebalance':'没有带公告/生效时点和当时成分股的事件历史。',
    'premarket_0925':'本次只有正常交易时段 K 线；可运行的替代实验是 09:35 首根完成后选择，非盘前扫描。',
}

def write(path,obj):path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+'\n')

def run(output,only=None,retry_solver=False):
    candidates=tuple(c for c in EXTENSIONS if only is None or c.name in only)
    if not candidates or (only and set(only)-{c.name for c in candidates}):raise ValueError('Unknown or empty candidate subset')
    if retry_solver:
        from app.research import strategy_extensions
        from app.research.solver_retry import retry_target_weights
        strategy_extensions.target_weights=retry_target_weights
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    files={p.stem:p for p in sorted((ROOT/'reports/platform_universe30_bars_20260913').glob('*.parquet'))}
    files.update({s:ROOT/'reports/quant_audit_20260912/bars'/f'{s}.parquet' for s in FOUR})
    files['IBIT']=ROOT/'reports/extended_reference_bars_20260913/IBIT.parquet'
    frames={s:pd.read_parquet(p) for s,p in files.items()}
    dates,audit=audit_bars(frames,'2026-08-31','2026-09-11')
    sessions,_,coverage=complete_universe(frames,dates)
    sources=[Path(__file__).resolve(),*[ROOT/'backend/app'/p for p in ['quant_policy.py','research/strategy_extensions.py','research/platform.py','research/policy_replay.py','research/causal_week_replay.py','research/attribution.py','research/data_audit.py','research/artifacts.py']]]
    if retry_solver:sources.append(ROOT/'backend/app/research/solver_retry.py')
    registry=dict(schema_version=1,status='running',registered_at=pd.Timestamp.now(tz='UTC').isoformat(),
        interpretation='retrospective_exploration_not_untouched_holdout',evaluation_dates=dates,symbols=list(frames),
        starting_equity=100000,cost_bps_per_side=[2,5],candidates=[asdict(c) for c in candidates],
        portfolio_solver='osqp_or_exact_scalar_pair',selected_for_live=None,
        selection_rule='Highest first-five-session net PnL at 5 bps, ties by name; evaluate remaining four already-explored sessions separately.',
        selection_dates=dates[:5],subsequent_dates=dates[5:],unverified_assumptions=UNVERIFIED,
        gross_limit=.95,symbol_limit=.7,risk_aversion=50,reference_risk_multiplier=1,
        source_membership='Contemporary research panel, not point-in-time constituents',
        data_audit=audit,data_paths={s:str(p.relative_to(ROOT)) for s,p in files.items()},data_hashes={s:digest(p) for s,p in files.items()},
        data_provenance={str(d.relative_to(ROOT)):input_provenance(d,[s for s,p in files.items() if p.parent==d]) for d in set(p.parent for p in files.values())},
        sources={str(p.relative_to(ROOT)):digest(p) for p in sources},numerical_retry='osqp_then_slsqp_same_objective' if retry_solver else None,
        library_versions={n:version(n) for n in ['numpy','pandas','scipy','scikit-learn','lightgbm','osqp','exchange-calendars']},trials=[])
    write(output/'preregistration.json',registry)
    for p in sources:
        target=output/'source'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
    pd.DataFrame(coverage).to_csv(output/'coverage.csv',index=False)
    runtime=ResearchRuntime(frames)
    for candidate in candidates:
        symbols=runtime.symbols(candidate)
        for cost in (2,5):
            tag=f'{candidate.name}_cost{cost}';folder=output/tag;folder.mkdir()
            print('RUN',tag,flush=True)
            trial=dict(candidate=asdict(candidate),cost_bps=cost,status='running')
            ledger=ShareLedger(list(symbols),ExecutionConfig(slippage_bps=cost));daily=[];decisions=[];training=[]
            spec=ResearchSpec(tag,horizon_bars=candidate.horizon,cost_bps=cost)
            try:
                for day in dates:
                    bars={s:sessions[s][day] for s in symbols};index=bars[symbols[0]].index
                    opening=None;target=None
                    if candidate.model=='equal':opening=dict.fromkeys(symbols,.95/len(symbols))
                    else:
                        context=runtime.prepare(candidate,day,index)
                        training.append(dict(day=day,training=context['training'],selection=context['selection'],selected=context['selected']))
                        def target(i,current):
                            weights=runtime.target(context,i,current,spec)
                            decisions.append(dict(available_at=(index[i]+pd.Timedelta(minutes=5)).isoformat(),weights=weights,
                                forecast={s:float(p[i]) for s,p in context['predictions'].items()}))
                            return weights
                    daily.append(replay_day(ledger,bars,day,target,lambda w,p,e:integer_targets(w,p,e,spec),opening))
                summary=summarize(daily,ledger.marks)
                if not np.isclose(summary['costs'],summary['turnover_dollars']*cost/10000,atol=1e-7):raise AssertionError('Cost mismatch')
                if candidate.name=='four_tree_h1':
                    expected={2:6101.525699507285,5:11758.860434193033}[cost]
                    if abs(summary['net_pnl']-expected)>1e-6:raise AssertionError(f'Original control mismatch: {summary["net_pnl"]} != {expected}')
                attribution,detail=ledger_attribution(pd.DataFrame(ledger.marks),pd.DataFrame(ledger.fills),symbols,100000)
                for label,records in [('daily',daily),('fills',ledger.fills)]:pd.DataFrame(records).to_csv(folder/f'{label}.csv',index=False)
                pd.DataFrame(ledger.marks).to_csv(folder/'marks.csv.gz',index=False,compression='gzip')
                detail.to_csv(folder/'attribution.csv.gz',index=False,compression='gzip')
                with gzip.open(folder/'decisions.json.gz','wt') as handle:json.dump(decisions,handle,allow_nan=False)
                write(folder/'training.json',training)
                trial.update(status='complete',summary=summary,attribution=attribution,
                    per_symbol={s:dict(net_pnl=sum(d[f'{s}_net_pnl'] for d in daily),costs=sum(d[f'{s}_costs'] for d in daily)) for s in symbols},
                    selection_period=summarize(daily[:5],ledger.marks),subsequent_period=summarize(daily[5:],ledger.marks))
                print('DONE',tag,round(summary['net_pnl'],2),flush=True)
            except Exception as exc:
                trial.update(status='failed',reason=str(exc));(folder/'failure.txt').write_text(traceback.format_exc())
                print('FAILED',tag,str(exc),flush=True)
            write(folder/'summary.json',trial);registry['trials'].append(trial)
            write(output/'progress.json',registry)
    for name,reason in (UNAVAILABLE.items() if only is None else []):
        for cost in (2,5):registry['trials'].append(dict(candidate=dict(name=name),cost_bps=cost,status='unavailable',reason=reason))
    complete=[t for t in registry['trials'] if t['status']=='complete' and t['cost_bps']==5]
    chosen=sorted(complete,key=lambda t:(-t['selection_period']['net_pnl'],t['candidate']['name']))[0]
    best=max(complete,key=lambda t:t['summary']['net_pnl'])
    registry.update(status='complete',finished_at=pd.Timestamp.now(tz='UTC').isoformat(),
        selected_for_future_paper=chosen['candidate']['name'],retrospective_best=best['candidate']['name'],
        failed_trials=sum(t['status']=='failed' for t in registry['trials']))
    registry['artifact_hashes']={str(p.relative_to(output)):digest(p) for p in output.rglob('*') if p.is_file() and p.name not in ('registry.json','registry.sha256','progress.json')}
    write(output/'registry.json',registry);(output/'registry.sha256').write_text(digest(output/'registry.json')+'\n')
    print('FINISHED',registry['selected_for_future_paper'],registry['retrospective_best'],flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--only',nargs='+');parser.add_argument('--retry-solver',action='store_true')
    args=parser.parse_args();run(args.output,args.only,args.retry_solver)
