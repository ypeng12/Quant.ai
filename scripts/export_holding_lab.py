#!/usr/bin/env python3
"""Publish all declared holding experiments with reconciled ledgers and hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.research.attribution import ledger_attribution
from app.research.artifacts import load_platform_results


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export(inputs, output):
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    trials=[];seen=set();first=None;sources={}
    for number, source in enumerate(map(Path,inputs)):
        registry=json.loads((source/'registry.json').read_text())
        if registry['status']!='complete':raise ValueError('Incomplete source experiment')
        if first is None:
            first=registry;shutil.copytree(source/'bars',out/'bars')
        if any(digest(source/'bars'/f'{s}.parquet')!=digest(out/'bars'/f'{s}.parquet') for s in first['inputs']):
            raise ValueError('Candidate input snapshots differ')
        archive=out/'experiments'/str(number);archive.mkdir(parents=True)
        shutil.copy2(source/'registry.json',archive/'registry.json')
        for relative, expected in registry['sources'].items():
            path=source/'source'/relative
            if digest(path)!=expected:raise ValueError('Missing exact experimental source snapshot')
            destination=archive/'source'/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,destination);sources[str(destination.relative_to(ROOT))]=expected
        for name, summary in registry['results'].items():
            if name in seen:continue
            seen.add(name);folder=out/name;shutil.copytree(source/name,folder)
            model=source/'models'/f'{name}.json'
            if model.exists():
                (out/'models').mkdir(exist_ok=True);shutil.copy2(model,out/'models'/model.name)
            marks=pd.read_csv(folder/'marks.csv');fills=pd.read_csv(folder/'fills.csv')
            attr,detail=ledger_attribution(marks,fills,registry['symbols'],registry['capital'])
            detail.to_csv(folder/'attribution.csv',index=False)
            if abs(attr['net_pnl']-summary['net_pnl'])>1e-6:raise ValueError('Experiment ledger mismatch')
            candidate=next((c for c in registry['candidates'] if c['name']==name),None)
            trials.append(dict(candidate=dict(name=name,features=candidate['family'] if candidate else 'benchmark',
                model='Ridge with prior calibration' if name.startswith('calibrated') else 'Ridge' if candidate else 'No ML',
                portfolio='costed return curve' if candidate and candidate['planning'] else 'single interval or benchmark'),
                status='complete',cost_bps=5,summary=summary,attribution=attr,
                per_symbol={s:{k:v for k,v in r.items() if k!='symbol'} for r in attr['by_symbol'] for s in [r['symbol']]},
                experiment_registry=str((archive/'registry.json').relative_to(out)),policy_cost_bps=candidate['cost_bps'] if candidate else None))
    days=pd.read_csv(out/trials[0]['candidate']['name']/'daily.csv')['date'].tolist()
    report=dict(status='complete',registered_at=first['created_at'],evaluation_dates=days,
        symbols=first['symbols']+first['references'],traded_symbols=first['symbols'],starting_equity=first['capital'],
        cost_bps_per_side=[5],cost_description='成交账本统一按单边 5 bps 模拟。默认候选内部规划成本为 2 bps；标注“规划 5 bps”的候选同时按 5 bps 规划。两者均非券商实际手续费。',
        trials=trials,selected_for_live=None,performance_verified=False,default_display_candidate='calibrated_legacy_curve',
        unverified_assumptions=first['limitations']+[first['evaluation']],sources=sources,
        data_paths={s:str((out/'bars'/f'{s}.parquet').relative_to(ROOT)) for s in first['inputs']},
        data_hashes={s:digest(out/'bars'/f'{s}.parquet') for s in first['inputs']})
    report['artifact_hashes']={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}
    (out/'registry.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    (out/'registry.sha256').write_text(digest(out/'registry.json')+'\n')
    checked=load_platform_results(out)
    if not checked['success']:raise ValueError(checked['reason'])
    print(json.dumps(dict(output=str(out),trials=len(trials),verified=True)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--inputs',nargs='+',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();export(a.inputs,a.output)
