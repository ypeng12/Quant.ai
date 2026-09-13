#!/usr/bin/env python3
"""Build actual feature matrices and optional trained artifacts; no PnL or orders."""
from __future__ import annotations
import argparse
import json
from importlib.metadata import version
from pathlib import Path
import sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.alpha.paper_bar_alpha import BarAlphaSpec,bar_alpha_panel,STOCKS,REFERENCES,FAMILIES
from app.alpha.paper_l1_alpha import enhanced_l1_features,PAPER_L1_FEATURES
from app.alpha.l1_state_models import QueueImbalanceModel,TransitionMicroprice
from app.market_data.alpaca_l1_capture import load_real_l1_events
from app.research.paper_models import PaperForecast,fit_l1_ridge,combine_bar_l1
from app.research.paper_catalog import ENTRIES,digest
from app.research.data_audit import input_provenance
from app.quant_policy import PolicySpec,labeled_frame


def write(path,value): path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def run(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    requested=tuple(dict.fromkeys(args.symbols+list(REFERENCES)))
    if any(not s.replace('.','').isalnum() for s in requested): raise ValueError('Invalid symbol')
    files={s:Path(args.bars)/f'{s}.parquet' for s in requested}
    missing=[s for s,p in files.items() if not p.exists()]
    files={s:p for s,p in files.items() if p.exists()}
    frames={s:pd.read_parquet(p) for s,p in files.items()}
    sources=[Path(__file__),*[ROOT/'backend/app'/p for p in ('alpha/paper_bar_alpha.py','alpha/paper_l1_alpha.py',
             'alpha/l1_state_models.py','alpha/real_l1_alpha.py','research/paper_models.py','quant_policy.py',
             'market_data/alpaca_l1_capture.py','research/data_audit.py')]]
    source_hashes={str(p.relative_to(ROOT)):digest(p) for p in sources}
    l1_hashes={str(p.relative_to(args.l1_dir)):digest(p) for p in Path(args.l1_dir).rglob('*.jsonl')} if args.l1_dir else {}
    report=dict(schema_version=1,status='running',registered_at=pd.Timestamp.now(tz='UTC').isoformat(),
                task='feature_implementation_and_training_no_backtest',performance_verified=False,selected_for_live=None,
                library_versions={n:version(n) for n in ('numpy','pandas','scipy','scikit-learn','lightgbm','pyarrow')},
                entries=list(ENTRIES),requested_symbols=list(requested),symbols=list(files),missing_symbols=missing,
                data_hashes={s:digest(p) for s,p in files.items()},features={},models=[],l1={},
                data_provenance=input_provenance(args.bars,list(files)),
                unverified_assumptions=['因子实现与训练完成不代表样本外 Alpha 或盈利。',
                    'Alpha158 / Alpha101 是五分钟、日内重置适配，不复制原论文日频收益。',
                    '固定当前研究池，不代表历史成分股；此命令不选股下单。',
                    '成本、期初库存、账户净值、入出金仍未以官方账单核验。',
                    '历史中间价标签不包含报价送达延迟、可成交数量或真实交易成本。'])
    write(out/'registry.json',report)
    if not frames: raise ValueError('No local bars. Supply --bars with retained parquet data.')
    cutoff=pd.Timestamp(args.train_before) if args.train_before else None
    if cutoff is not None and cutoff.tzinfo is None: raise ValueError('--train-before requires timezone')
    bar_library=None
    for family in FAMILIES:
        panel=bar_alpha_panel(frames,BarAlphaSpec(family=family))
        if family=='paper_library': bar_library=panel
        folder=out/family;folder.mkdir();report['features'][family]={}
        for s,features in panel.items():
            features.to_parquet(folder/f'{s}.parquet')
            report['features'][family][s]=dict(rows=len(features),columns=list(features.columns),
                observed_rows=int(features.notna().any(axis=1).sum()),complete_rows=int(features.notna().all(axis=1).sum()),
                availability={n:int(features[n].notna().sum()) for n in features},contract=features.attrs)
            if cutoff is None or s in REFERENCES: continue
            _,target=labeled_frame(frames[s],PolicySpec('paper_training',horizon_bars=args.horizon_bars))
            target=target.reindex(features.index)
            end=pd.Series(features.index+pd.Timedelta(minutes=5*(args.horizon_bars+1)),index=features.index)
            for estimator in args.models:
                record=dict(symbol=s,family=family,estimator=estimator)
                try:
                    model=PaperForecast().fit(features,target,label_end=end,before=cutoff,estimator=estimator)
                    model.artifact.update(symbol=s,horizon_bars=args.horizon_bars,target='next_open_to_horizon_close_return')
                    name=f'{family}/{s}_{estimator}.json';model.save(out/name)
                    record.update(status='trained_unvalidated',artifact=name,rows=model.artifact['rows'],
                                  trained_before=model.artifact['trained_before'],unused_features=model.artifact['unused_features'])
                except (ValueError,ImportError) as exc: record.update(status='unavailable',reason=str(exc))
                report['models'].append(record)
        print(f'{family}: feature matrices built',flush=True)
    for symbol in args.l1_symbols:
        record=dict(status='unavailable',reason='未提供真实 L1 留存目录；未生成模拟报价')
        if args.l1_dir:
            try:
                events=load_real_l1_events(args.l1_dir,symbol)
                if events.empty: raise ValueError('No real captured L1 events')
                folder=out/'l1'/symbol;folder.mkdir(parents=True)
                book=enhanced_l1_features(events)
                book.to_parquet(folder/'features_5min.parquet')
                record=dict(status='features_built',events=len(events),models=[])
                if cutoff is not None:
                    tasks=[('qi_logistic',lambda:QueueImbalanceModel().fit(events,before=cutoff)),
                           ('transition_microprice',lambda:TransitionMicroprice().fit(events,before=cutoff,tick_size=args.tick_size))]
                    tasks += [(f'ofi_ridge_{h}',lambda h=h:fit_l1_ridge(events,before=cutoff,horizon=h)) for h in ('1s','5s','30s','1min','5min')]
                    for name,fit in tasks:
                        try:
                            fitted=fit();fitted.save(folder/f'{name}.json')
                            record['models'].append(dict(name=name,status='trained_unvalidated'))
                        except ValueError as exc: record['models'].append(dict(name=name,status='unavailable',reason=str(exc)))
                    if symbol in bar_library:
                        combined=combine_bar_l1(bar_library[symbol],events)
                        _,target=labeled_frame(frames[symbol],PolicySpec('paper_l1_training',horizon_bars=args.horizon_bars))
                        target=target.reindex(combined.index)
                        end=pd.Series(combined.index+pd.Timedelta(minutes=5*(args.horizon_bars+1)),index=combined.index)
                        try:
                            fitted=PaperForecast().fit(combined,target,label_end=end,before=cutoff)
                            fitted.artifact.update(symbol=symbol,horizon_bars=args.horizon_bars,target='next_open_to_horizon_close_return',
                                                   input_kind='bar_plus_real_l1')
                            fitted.save(folder/'bar_plus_l1_ridge.json')
                            record['models'].append(dict(name='bar_plus_l1_ridge',status='trained_unvalidated'))
                        except ValueError as exc:
                            record['models'].append(dict(name='bar_plus_l1_ridge',status='unavailable',reason=str(exc)))
            except (ValueError,OSError) as exc: record=dict(status='unavailable',reason=str(exc))
        report['l1'][symbol]=record
    report['l1_input_hashes']={str(p.relative_to(args.l1_dir)):digest(p) for p in Path(args.l1_dir).rglob('*.jsonl')} if args.l1_dir else {}
    if report['l1_input_hashes']!=l1_hashes:
        raise ValueError('L1 capture changed during the build; use a frozen copy')
    report['source_hashes']={str(p.relative_to(ROOT)):digest(p) for p in sources}
    if report['source_hashes']!=source_hashes:
        raise ValueError('Source files changed during the build; rerun from a stable checkout')
    if report['data_hashes']!={s:digest(p) for s,p in files.items()}:
        raise ValueError('Input files changed during the build')
    for p in sources:
        target=out/'source'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
    report.update(status='complete',finished_at=pd.Timestamp.now(tz='UTC').isoformat())
    report['artifact_hashes']={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='registry.json'}
    write(out/'registry.json',report);(out/'registry.sha256').write_text(digest(out/'registry.json')+'\n')
    print(f"{out}: {len(report['models'])} model attempts recorded; no backtest or orders",flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bars',default=str(ROOT/'reports/platform_universe30_bars_20260913'))
    parser.add_argument('--symbols',nargs='+',default=list(STOCKS))
    parser.add_argument('--output',required=True)
    parser.add_argument('--train-before',help='Exclusive timestamp with timezone; omitted means features only')
    parser.add_argument('--models',nargs='+',choices=['ridge','tree','lightgbm'],default=['ridge','tree','lightgbm'])
    parser.add_argument('--horizon-bars',type=int,choices=[1,3,6],default=1)
    parser.add_argument('--l1-dir');parser.add_argument('--l1-symbols',nargs='+',default=['SNDK','TSLA','PLTR','NVDA'])
    parser.add_argument('--tick-size',type=float,default=.01)
    run(parser.parse_args())
