#!/usr/bin/env python3
"""Fixed cloud-suitable numeric text ablations; no news, network, or broker API.

This is a retrospective diagnostic, not a parameter search. Metadata/intercept
arms retain the full model's fitted coefficients; they are decomposition arms,
not independently refitted models or isolated causal sentiment effects.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.quant_policy import integer_targets, normalize_bars
from app.research.policy_replay import ExecutionConfig,ShareLedger,complete_universe,replay_day,summarize
from app.research.sentiment_alpha_candidate import PriceCandidate,TextReturnAdjustment,FIXED_SPEC

TRADED=('NVDA','SNDK','TSLA')
INPUTS=(*TRADED,'MSTR')
ARMS=('C','B_full','metadata_only','constant_intercept','B_expiring')
COSTS=(5.0,2.0)  # Primary executable cost stress first; planning cost stays frozen at 2 bps.
METADATA_FEATURES=frozenset(('news_log_count','futu_log_count','unique_text_fraction',
    'mean_publication_age_fraction','mean_receipt_age_fraction','any_text_missing','news_missing','futu_missing'))
SEMANTIC_FEATURES=frozenset(('news_stance_balance','futu_stance_balance','news_scored_fraction','futu_scored_fraction'))
CAP=.0005


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite(value):
    result=float(value)
    if not math.isfinite(result):raise ValueError('Nonfinite numeric input')
    return result


def aware(value):
    result=pd.Timestamp(value)
    if result.tz is None:raise ValueError('Require timezone-aware decision clocks')
    return result.tz_convert('America/New_York')


def normalize_decisions(frame,dates):
    required={'date','decision_at','symbol','C_mu','text_adjustment_full_30m',
              'has_text','text_fallback','feature_vector','event_ids'}
    if not required<=set(frame.columns):raise ValueError('Missing numeric decision/event-ID fields')
    result={}
    for original in frame.to_dict(orient='records'):
        row=dict(original);at=aware(row['decision_at']);date=pd.Timestamp(row['date']).date().isoformat()
        if date!=at.date().isoformat() or date not in dates or row['symbol'] not in TRADED:
            raise ValueError('Unexpected decision date/company')
        row.update(date=date,decision_at=at.isoformat(),C_mu=finite(row['C_mu']),
                   text_adjustment_full_30m=finite(row['text_adjustment_full_30m']))
        if type(row['has_text']) is not bool:raise ValueError('Require boolean text availability')
        if row['text_fallback'] is None or (isinstance(row['text_fallback'],float) and math.isnan(row['text_fallback'])):
            row['text_fallback']=None
        elif not isinstance(row['text_fallback'],str):raise ValueError('Unexpected fallback value')
        ids=row['event_ids']
        if not isinstance(ids,list) or any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids):
            raise ValueError('Require distinct anonymous source-event IDs, not raw text')
        if not isinstance(row['feature_vector'],list):raise ValueError('Require numeric feature vector')
        row['feature_vector']=[finite(x) for x in row['feature_vector']]
        key=(date,at.isoformat(),row['symbol'])
        if key in result:raise ValueError('Duplicate company-decision row')
        result[key]=row
    return result


def decomposition(row,calibration):
    """Same eligibility and cap for all arms; no calibration is fit here."""
    full=row['text_adjustment_full_30m']
    if not row['has_text'] or row['text_fallback'] is not None:
        if abs(full)>1e-15:raise ValueError('Fallback carries a nonzero frozen correction')
        return {'C':0.0,'B_full':0.0,'metadata_only':0.0,'constant_intercept':0.0},False
    if (calibration['status']!='fitted_development_only' or calibration['target_horizon_minutes']!=30
            or calibration['mode']!='strict_received' or aware(calibration['training_cutoff'])>=aware(row['decision_at'])):
        raise ValueError('Unavailable/mismatched/future text calibration')
    names=calibration['feature_names']
    if set(names)!=METADATA_FEATURES|SEMANTIC_FEATURES or len(names)!=12:
        raise ValueError('Unsupported frozen feature schema')
    vectors=[row['feature_vector'],calibration['means'],calibration['scales'],calibration['weights']]
    if any(len(x)!=12 for x in vectors):raise ValueError('Mismatched feature dimensions')
    intercept=finite(calibration['intercept']);raw=intercept;metadata=intercept
    for name,value,mean,scale,weight in zip(names,*vectors):
        scale=finite(scale)
        if scale<=0:raise ValueError('Invalid feature scale')
        contribution=(finite(value)-finite(mean))/scale*finite(weight)
        raw+=contribution
        if name in METADATA_FEATURES:metadata+=contribution
    clip=lambda x:max(-CAP,min(CAP,x))
    # Original decisions use pandas' JSON floating precision, while coefficients
    # retain ordinary Python JSON precision. Do not silently replace frozen B.
    if abs(clip(raw)-full)>2e-10:raise ValueError('Frozen full correction cannot be reconstructed')
    return {'C':0.0,'B_full':full,'metadata_only':clip(metadata),'constant_intercept':clip(intercept)},True


class EventExpiry:
    """30 minutes from first eligible nonzero correction, not every bar refresh.

    IDs exclude content-version hashes. They are source-event proxies, not a
    claim of independently verified economic events. At expiry the affected
    name is flattened once; following decisions may trade its price-only C.
    """
    def __init__(self):
        self.seen={s:set() for s in TRADED};self.until={s:None for s in TRADED}
        self.previous={s:None for s in TRADED}

    def step(self,row,eligible):
        s=row['symbol'];at=aware(row['decision_at']);full=row['text_adjustment_full_30m']
        previous=self.previous[s]
        if previous is not None and at<=previous:raise ValueError('Expiry decisions must be chronological')
        # The common ledger already liquidated yesterday. Do not impose a
        # redundant zero target on the next day's price-only opening decision.
        if previous is not None and at.date()!=previous.date():self.until[s]=None
        self.previous[s]=at
        fresh=set(row['event_ids'])-self.seen[s]
        if eligible and abs(full)>1e-15 and not row['event_ids']:
            raise ValueError('An active correction needs an anonymous source-event ID')
        if eligible and abs(full)>1e-15 and fresh:
            self.seen[s].update(row['event_ids'])
            self.until[s]=min(at+pd.Timedelta(minutes=30),at.replace(hour=15,minute=55,second=0,microsecond=0))
            return full,False,'new_source_event_activation'
        deadline=self.until[s]
        if deadline is not None and at>=deadline:
            self.until[s]=None
            return 0.0,True,'expired_force_flat_once'
        if deadline is not None and eligible:
            return full,False,'within_original_event_lifetime'
        return 0.0,False,'price_only_no_new_source_event'


def comparison_to_frozen(daily,fills,summary,folder):
    """A failed reproduction is disclosed, never accepted as identical."""
    old_summary=json.loads((folder/'summary.json').read_text())
    old_daily=pd.read_csv(folder/'daily.csv.gz').to_dict(orient='records')
    old_fills=pd.read_csv(folder/'fills.csv.gz').to_dict(orient='records')
    if [r['date'] for r in daily]!=[r['date'] for r in old_daily]:raise ValueError('Frozen date coverage differs')
    keys=('date','fill_time','symbol','quantity','shares_after','reason')
    first=None;matching=0
    numeric=('reference_price','fill_price','cost','notional')
    for i,(new,old) in enumerate(zip(fills,old_fills)):
        same_identity=all(str(new[k])==str(old[k]) for k in keys) or all(new[k]==old[k] for k in keys)
        same_execution=all(math.isclose(finite(new[k]),finite(old[k]),rel_tol=1e-12,abs_tol=1e-8) for k in numeric)
        if same_identity and same_execution:matching+=1
        elif first is None:first={'row_index':i,'new':{k:new[k] for k in keys},'frozen':{k:old[k] for k in keys}}
    if first is None and len(fills)!=len(old_fills):first={'row_index':min(len(fills),len(old_fills)),'reason':'fill_count_difference'}
    daily_differences=[{'date':n['date'],'net_pnl_difference':finite(n['net_pnl'])-finite(o['net_pnl']),
                       'cost_difference':finite(n['costs'])-finite(o['costs'])} for n,o in zip(daily,old_daily)]
    maximum=max(abs(r['net_pnl_difference']) for r in daily_differences)
    exact=first is None and maximum<=1e-6 and abs(summary['costs']-old_summary['costs'])<=1e-6
    return {'status':'reproduced_within_1e_6_usd' if exact else 'reproduction_difference',
        'exact_fill_identity':first is None,'matching_fill_rows':matching,'first_different_fill':first,
        'net_pnl_difference':summary['net_pnl']-old_summary['net_pnl'],
        'cost_difference':summary['costs']-old_summary['costs'],
        'maximum_absolute_daily_net_pnl_difference':maximum,'daily_differences':daily_differences,
        'input_sha256':{n:digest(folder/n) for n in ('summary.json','daily.csv.gz','fills.csv.gz')},
        'note':'If differences occur, ablation comparisons use the common numeric-input replay; do not relabel them as the original frozen execution.'}


def run_ablations(frames,decisions_dataframe,training_receipts,dates,output,frozen_root=None):
    """Run five fixed arms at 5/2 bps; fit C once/day solely for covariance.

    Frames: four original 5m OHLCV series including prior warmup, aware index.
    Decisions: date, aware decision_at, symbol, C_mu, full30m correction,
    has_text, text_fallback, feature_vector, event_ids (anonymous source IDs).
    Receipts: original per-date price/text numeric calibration audits.
    Output must be new. No raw headline, URL, credential, or broker is consumed.
    """
    output=Path(output)
    if output.exists():raise ValueError('Choose a new private ablation output directory')
    dates=[pd.Timestamp(d).date().isoformat() for d in dates]
    if dates!=sorted(set(dates)) or not dates:raise ValueError('Require ordered distinct dates')
    if set(frames)!=set(INPUTS):raise ValueError('Require all four fixed input symbols')
    frames={s:normalize_bars(frames[s]) for s in INPUTS}
    sessions,_,coverage=complete_universe(frames,dates)
    decisions=normalize_decisions(decisions_dataframe,dates)
    training={pd.Timestamp(r['date']).date().isoformat():r for r in training_receipts}
    if set(training)!=set(dates) or len(training_receipts)!=len(dates):raise ValueError('Training receipt coverage differs')
    plan={};expiry=EventExpiry();adjustment_rows=[]
    for day in dates:
        index=sessions[TRADED[0]][day].index
        for i in range(76):
            at=(index[i]+pd.Timedelta(minutes=5)).isoformat()
            for s in TRADED:
                key=(day,at,s)
                if key not in decisions:raise ValueError('Missing company decision')
                row=decisions[key];adjustments,eligible=decomposition(row,training[day]['text'])
                expiration,force,reason=expiry.step(row,eligible)
                adjustments['B_expiring']=expiration
                plan[key]=(adjustments,force)
                adjustment_rows.append({'date':day,'decision_at':at,'symbol':s,'C_mu':row['C_mu'],
                    **adjustments,'B_expiring_force_flat':force,'expiry_action':reason})
    if len(plan)!=len(decisions):raise ValueError('Extra decision rows')
    output.mkdir(parents=True,mode=0o700);(output/'.gitignore').write_text('*\n')
    frame_hashes={s:hashlib.sha256(pd.util.hash_pandas_object(f,index=True).values.tobytes()).hexdigest() for s,f in frames.items()}
    registration={'schema_version':1,'registered_at':datetime.now(timezone.utc).isoformat(),
        'evaluation_kind':'retrospective_development_ablation','arms':list(ARMS),'dates':dates,
        'starting_equity':50000.0,'gross_limit':.95,'symbol_limit':.70,
        'primary_cost_bps_per_side':5.0,'secondary_cost_bps_per_side':2.0,'planning_cost_bps':2.0,
        'horizon_minutes':30,'text_cap_bps':5.0,'covariance':'One original PriceCandidate.fit per prior-only day; shared by all arms/costs. Frozen numeric C_mu is never refit or replaced.',
        'metadata_features':sorted(METADATA_FEATURES),'metadata_method':'Frozen full-model coefficient decomposition, not a refit.',
        'expiry':'First eligible nonzero source-event correction starts30min. New source ID may renew; same source ID/content updates cannot. Expiry forces name flat once, then permits price-only C. Ledger remains flat overnight.',
        'frame_fingerprints':frame_hashes,
        'decisions_sha256':hashlib.sha256(decisions_dataframe.to_json(orient='records',date_format='iso',double_precision=15).encode()).hexdigest(),
        'training_sha256':hashlib.sha256(json.dumps(training_receipts,sort_keys=True).encode()).hexdigest(),
        'source_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),ROOT/'backend/app/quant_policy.py',ROOT/'backend/app/research/policy_replay.py',ROOT/'backend/app/research/sentiment_alpha_candidate.py']},
        'parameter_search':False,'promoted':False}
    write(output/'registration.json',registration);write(output/'coverage.json',coverage)
    pd.DataFrame(adjustment_rows).to_csv(output/'adjustments.csv.gz',index=False,compression='gzip')
    states={(cost,arm):{'ledger':ShareLedger(list(TRADED),ExecutionConfig(starting_equity=50000,slippage_bps=cost,gross_limit=.95,symbol_limit=.70)),'daily':[]}
            for cost in COSTS for arm in ARMS}
    fit_audits=[]
    status={'status':'running','completed_dates':[],'promoted':False}
    write(output/'progress.json',status)
    try:
        for day in dates:
            candidate=PriceCandidate.fit(frames,day,traded_symbols=TRADED)
            fit_audits.append({'date':day,'covariance_fit_audit':candidate.audit,
                              'frozen_price_receipt':training[day]['price'],'forecast_source':'frozen numeric C_mu'})
            bars={s:sessions[s][day] for s in TRADED};index=bars[TRADED[0]].index
            for cost in COSTS:
                for arm in ARMS:
                    state=states[(cost,arm)]
                    def decide(i,current):
                        at=(index[i]+pd.Timedelta(minutes=5)).isoformat()
                        mu={s:decisions[(day,at,s)]['C_mu'] for s in TRADED}
                        delta={s:plan[(day,at,s)][0][arm] for s in TRADED}
                        adjustment=None if arm=='C' else TextReturnAdjustment(returns=delta,available_at=at,horizon_bars=6)
                        weights=candidate.weights(index[i],current,mu,shortable=dict.fromkeys(TRADED,True),text_adjustment=adjustment)
                        if arm=='B_expiring':
                            for s in TRADED:
                                if plan[(day,at,s)][1]:weights[s]=0.0
                        return weights
                    state['daily'].append(replay_day(state['ledger'],bars,day,decide,
                        lambda w,p,e:integer_targets(w,p,e,FIXED_SPEC)))
            status['completed_dates'].append(day);write(output/'progress.json',status)
            print(json.dumps({'completed_day':day,'primary_daily_net_pnl':{a:states[(5.0,a)]['daily'][-1]['net_pnl'] for a in ARMS}}),flush=True)
        results={};reproduction={}
        for (cost,arm),state in states.items():
            folder=output/f'cost_{cost:g}bps'/arm
            folder.mkdir(parents=True)
            for kind,rows in [('daily',state['daily']),('fills',state['ledger'].fills),('marks',state['ledger'].marks)]:
                pd.DataFrame(rows).to_csv(folder/f'{kind}.csv.gz',index=False,compression='gzip')
            result=summarize(state['daily'],state['ledger'].marks)
            net=[d['net_pnl'] for d in state['daily']]
            result.update(pnl_excluding_best_day=sum(net)-max(net),promoted=False)
            write(folder/'summary.json',result);results[f'{cost:g}bps_{arm}']=result
            if frozen_root is not None and arm in ('C','B_full'):
                frozen_name='B' if arm=='B_full' else 'C'
                reproduction[f'{cost:g}bps_{arm}']=comparison_to_frozen(state['daily'],state['ledger'].fills,result,
                    Path(frozen_root)/f'cost_{cost:g}bps'/frozen_name)
        write(output/'covariance_fits.json',fit_audits)
        report={**registration,'status':'complete','completed_at':datetime.now(timezone.utc).isoformat(),
            'results':results,'frozen_reproduction':reproduction,
            'frozen_reproduction_passed':all(r['status']=='reproduced_within_1e_6_usd' for r in reproduction.values()) if reproduction else None,
            'adjustment_counts':{a:sum(abs(r[a])>1e-15 for r in adjustment_rows) for a in ARMS},
            'expiry_actions':dict(Counter(r['expiry_action'] for r in adjustment_rows)),
            'limitations':['Historical development data already inspected; not a blind profitability test.',
                'Numeric frozen predictions may have serialization rounding; reproduction differences are reported explicitly.',
                'Source-event hashes prevent same-source updates renewing lifetime but do not certify independent economic events.',
                'Metadata/intercept arms retain full-model coefficients and correlated feature centering; they are not refitted causal controls.',
                'Costs are execution assumptions, not observed brokerage fees or spreads.',
                'Expiry can reduce or worsen PnL; no result-driven expiry or risk parameter search is performed.']}
        write(output/'summary.json',report);status['status']='complete';write(output/'progress.json',status)
        return report
    except Exception as exc:
        status.update(status='failed',error_type=type(exc).__name__,reason=str(exc))
        write(output/'progress.json',status);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();packet=args.input
    frames={s:pd.read_parquet(packet/f'{s}.parquet') for s in INPUTS}
    decisions=pd.read_json(packet/'decisions.jsonl.gz',lines=True)
    training=json.loads((packet/'training.json').read_text())
    run_ablations(frames,decisions,training,[r['date'] for r in training],args.output,frozen_root=packet/'baseline')
