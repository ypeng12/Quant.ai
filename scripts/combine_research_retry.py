#!/usr/bin/env python3
"""Combine successful numerical repairs, retaining every original failed attempt."""
import argparse
import json
import shutil
from pathlib import Path
import sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.research.artifacts import load_platform_results,digest

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base','retry','output'):p.add_argument('--'+name,required=True)
    args=p.parse_args();base=Path(args.base);retry=Path(args.retry);output=Path(args.output)
    a=load_platform_results(base);b=load_platform_results(retry)
    if a['status']!='complete' or b['status']!='complete':raise ValueError('Both source registries must verify')
    original=a['research'];repair=b['research']
    for key in ('data_hashes','evaluation_dates','starting_equity','library_versions','cost_bps_per_side','risk_aversion','gross_limit','symbol_limit'):
        if original[key]!=repair[key]:raise ValueError(f'Retry changes experiment conditions: {key}')
    if repair.get('numerical_retry')!='osqp_then_slsqp_same_objective':raise ValueError('Unrecognized numerical repair')
    keys=lambda t:(t['candidate']['name'],t['cost_bps'])
    repaired={keys(t):t for t in repair['trials']}
    failed={keys(t):t for t in original['trials'] if t['status']=='failed'}
    if set(repaired)!=set(failed):raise ValueError('Repair must address exactly the failed trials')
    for key,t in repaired.items():
        if t['status']!='complete' or t['candidate']!=failed[key]['candidate']:raise ValueError('Candidate parameters changed or retry failed')
    shutil.copytree(base,output,ignore=shutil.ignore_patterns('progress.json','registry.json','registry.sha256'))
    shutil.copytree(retry,output/'numerical_retry')
    shutil.copy2(base/'registry.json',output/'prior_base_registry.json')
    (output/'prior_attempts').mkdir()
    for key,t in repaired.items():
        tag=f'{key[0]}_cost{key[1]:g}'
        (output/tag).rename(output/'prior_attempts'/tag)
        shutil.copytree(retry/tag,output/tag)
        t['source_registry']='numerical_retry/registry.json'
    original['trials']=[repaired.get(keys(t),t) for t in original['trials']]
    complete=[t for t in original['trials'] if t['status']=='complete' and t['cost_bps']==5]
    original.update(selected_for_future_paper=sorted(complete,key=lambda t:(-t['selection_period']['net_pnl'],t['candidate']['name']))[0]['candidate']['name'],
        retrospective_best=max(complete,key=lambda t:t['summary']['net_pnl'])['candidate']['name'],failed_trials=0,
        initial_failed_trials=len(failed),numerical_retry_candidates=sorted({key[0] for key in repaired}),
        assembled_at=pd.Timestamp.now(tz='UTC').isoformat(),
        provenance_note='Original completed trials retain base sources. Only failed QPs were retried with identical predictions, costs and risk objective; all failures retained.',
        parent_registries={str(base):digest(base/'registry.json'),str(retry):digest(retry/'registry.json')})
    original.pop('source_matches_workspace',None)
    destination=output/'assembly_source/scripts/combine_research_retry.py';destination.parent.mkdir(parents=True);destination.write_bytes(Path(__file__).read_bytes())
    original['artifact_hashes']={str(p.relative_to(output)):digest(p) for p in output.rglob('*') if p.is_file()}
    (output/'registry.json').write_text(json.dumps(original,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    (output/'registry.sha256').write_text(digest(output/'registry.json')+'\n')
    checked=load_platform_results(output)
    if checked['status']!='complete':raise ValueError(checked.get('reason'))
    print(json.dumps(dict(status='complete',completed=sum(t['status']=='complete' for t in original['trials']),retained_failures=len(failed),best=original['retrospective_best'],selected=original['selected_for_future_paper'])))

if __name__=='__main__':main()
