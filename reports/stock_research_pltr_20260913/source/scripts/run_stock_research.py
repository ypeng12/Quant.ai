#!/usr/bin/env python3
"""Non-crypto stock models versus per-stock prior-session selection."""
import argparse,json,gzip
from dataclasses import asdict
from pathlib import Path
from importlib.metadata import version
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.research.liquid_policy import LiquidityRules,LiquidLedger
from app.research.stock_policy import StockRuntime as LiquidRuntime,STOCK_CANDIDATES as LIQUID_CANDIDATES,REFERENCES,STOCKS as FOUR
from app.research.strategy_extensions import ResearchSpec
from app.research.policy_replay import complete_universe,ShareLedger,ExecutionConfig,replay_day,summarize
from app.research.data_audit import audit_bars,input_provenance
from app.research.attribution import ledger_attribution
from app.research.artifacts import digest
from app.quant_policy import integer_targets

def write(p,value):p.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')

def load_inputs():
    primary=ROOT/'reports/quant_audit_20260912/bars'
    expanded=ROOT/'reports/platform_universe30_bars_20260913'
    files={s:(primary/f'{s}.parquet' if (primary/f'{s}.parquet').exists() else expanded/f'{s}.parquet') for s in FOUR}
    files.update({s:ROOT/'reports/platform_universe30_bars_20260913'/f'{s}.parquet' for s in REFERENCES if s!='IBIT'})
    return files,{s:pd.read_parquet(p) for s,p in files.items()}

def run(output):
    root=Path(output);root.mkdir(parents=True,exist_ok=False)
    files,frames=load_inputs();dates,audit=audit_bars(frames,'2026-08-31','2026-09-11')
    sessions,_,coverage=complete_universe(frames,dates)
    instrument_path=ROOT/'reports/liquid_instrument_audit_20260913/instruments_largecap.json'
    instruments=json.loads(instrument_path.read_text())['records']
    runtime=LiquidRuntime(frames,LiquidityRules(min_market_cap=0),instruments=instruments,research_membership=True)
    sources=[Path(__file__).resolve(),*[ROOT/'backend/app'/p for p in ('research/stock_policy.py','research/liquid_policy.py','research/strategy_extensions.py','research/platform.py','research/data_audit.py','research/policy_replay.py','research/causal_week_replay.py','research/attribution.py','research/artifacts.py','quant_policy.py')]]
    r=dict(schema_version=1,status='running',registered_at=pd.Timestamp.now(tz='UTC').isoformat(),evaluation_dates=dates,symbols=list(files),starting_equity=100000,
        cost_bps_per_side=[5],selected_for_live=None,interpretation='retrospective_exploration_not_untouched_holdout',
        candidates=[asdict(c) for c in LIQUID_CANDIDATES],liquidity_rules=asdict(runtime.rules),
        instrument_metadata=dict(path=str(instrument_path.relative_to(ROOT)),sha256=digest(instrument_path),historical_membership_verified=False),
        calibration='Per-stock selector uses the preceding five daily out-of-sample MSE folds; zero-forecast error is retained as a diagnostic',
        traded_symbols=list(FOUR),reference_symbols=list(REFERENCES),excluded_inputs=['MSTR','IBIT'],
        selection_rule=dict(validation_sessions=5,metric='mean_daily_mse_bps2',tie_break='declared_menu_order',update='once_per_session_before_open',horizon_bars=1),
        integrated_risk='One shared four-stock portfolio with prior-session Ledoit-Wolf covariance and turnover costs',
        risk_preferences=dict(risk_aversion=50,gross_limit=.95,symbol_limit=.7,execution='Next bar open, integer shares, predeclared intraday liquidation'),
        unverified_assumptions=['[未验证] 5 bps 为模拟成本，未核实实际价差、规费、冲击、借券和融资成本。',
            '[未验证] $100,000 及每日平仓为模拟条件，实际期初库存、净值和出入金未对账。',
            '[未验证] 当前挑选的股票池与当前证券属性不构成历史逐时点成分股证明；仅价格、量能筛选和模型输入采用当时可用数据。',
            '本段历史已反复研究，不能作为未见过的最终测试集；风险偏好及阈值是实验配置，不是机构统一标准。',
            '日均成交额采用五分钟收盘价乘成交量近似，缺少真实逐笔成交额；次根开盘成交未计实际延迟。'],
        data_audit=audit,data_paths={s:str(p.relative_to(ROOT)) for s,p in files.items()},data_hashes={s:digest(p) for s,p in files.items()},
        data_provenance={str(d.relative_to(ROOT)):input_provenance(d,[s for s,p in files.items() if p.parent==d]) for d in set(p.parent for p in files.values())},
        sources={str(p.relative_to(ROOT)):digest(p) for p in sources},library_versions={n:version(n) for n in ('numpy','pandas','scipy','scikit-learn','osqp','exchange-calendars')},trials=[])
    write(root/'preregistration.json',r)
    (root/'instrument_snapshot.json').write_bytes(instrument_path.read_bytes())
    for p in sources:
        target=root/'source'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
    pd.DataFrame(coverage).to_csv(root/'coverage.csv',index=False)
    for c in LIQUID_CANDIDATES:
        print('RUN',c.name,flush=True);folder=root/f'{c.name}_cost5';folder.mkdir()
        symbols=runtime.symbols(c);cfg=ExecutionConfig(slippage_bps=5,symbol_limit=c.symbol_limit)
        spec=ResearchSpec(c.name,cost_bps=5,symbol_limit=c.symbol_limit)
        ledger=ShareLedger(list(symbols),cfg) if c.control else LiquidLedger(list(symbols),cfg,runtime.rules)
        daily=[];decisions=[];training=[]
        for day in dates:
            bars={s:sessions[s][day] for s in symbols};index=bars[symbols[0]].index;context=runtime.prepare(c,day,index)
            calibration=context.get('calibration');training.append(dict(day=day,eligibility=context['eligibility'],training=context.get('training'),selection=context.get('selection'),
                calibration=None if calibration is None else {k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in calibration.items()}))
            opening=None;target=None
            if c.benchmark:
                selected=[s for s in symbols if context['eligibility'][s]['eligible']]
                opening={s:spec.gross_limit/len(selected) for s in selected} if selected else {}
            else:
                def target(i,current):
                    weights,explanation=runtime.target(c,context,i,current)
                    decisions.append(dict(available_at=(index[i]+pd.Timedelta(minutes=5)).isoformat(),weights=weights,**explanation))
                    return weights
            daily.append(replay_day(ledger,bars,day,target,lambda w,p,e:integer_targets(w,p,e,spec),opening))
        summary=summarize(daily,ledger.marks)
        attribution,detail=ledger_attribution(pd.DataFrame(ledger.marks),pd.DataFrame(ledger.fills),symbols,100000)
        for name,rows in [('daily',daily),('fills',ledger.fills)]:pd.DataFrame(rows).to_csv(folder/f'{name}.csv',index=False)
        pd.DataFrame(ledger.marks).to_csv(folder/'marks.csv.gz',index=False,compression='gzip');detail.to_csv(folder/'attribution.csv.gz',index=False,compression='gzip')
        with gzip.open(folder/'decisions.json.gz','wt') as handle:json.dump(decisions,handle,allow_nan=False)
        write(folder/'training.json',training)
        trial=dict(candidate=asdict(c),cost_bps=5,status='complete',summary=summary,attribution=attribution,
            per_symbol={s:dict(net_pnl=sum(d[f'{s}_net_pnl'] for d in daily),costs=sum(d[f'{s}_costs'] for d in daily)) for s in symbols},
            subsequent_period=summarize(daily[5:],ledger.marks))
        write(folder/'summary.json',trial);r['trials'].append(trial);write(root/'progress.json',r)
        print('DONE',c.name,round(summary['net_pnl'],2),flush=True)
    r.update(status='complete',finished_at=pd.Timestamp.now(tz='UTC').isoformat(),
        retrospective_best=max(r['trials'],key=lambda t:t['summary']['net_pnl'])['candidate']['name'])
    r['artifact_hashes']={str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file() and p.name!='progress.json'}
    write(root/'registry.json',r);(root/'registry.sha256').write_text(digest(root/'registry.json')+'\n')
    print('FINISHED',r['retrospective_best'],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);run(p.parse_args().output)
