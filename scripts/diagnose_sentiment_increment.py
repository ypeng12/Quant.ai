#!/usr/bin/env python3
"""Pure offline attribution of a frozen B minus C replay; no fitting or orders.

Reads saved decisions, fills, daily accounts, and bar marks using only stdlib.
Forward returns are retrospective diagnostics, never executable predictions.
New outputs are private and the input experiment is never changed.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import html
import json
import math
from pathlib import Path
import re
from collections import Counter, defaultdict


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Require aware timestamps')
    return result


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Nonfinite numeric input')
    return result


def close(a, b):
    if not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-6):
        raise ValueError(f'Attribution does not reconcile: {a} vs {b}')


def csv_rows(path):
    with gzip.open(path, 'rt') as stream:
        return list(csv.DictReader(stream))


def unique(rows, fields):
    result = {}
    for row in rows:
        key = tuple(row[k] for k in fields)
        if key in result:
            raise ValueError('Duplicate input identity')
        result[key] = row
    return result


def reference_path(opens, closes, at, minutes, symbol):
    """Entry at next-open clock; exit at last included bar close; no gaps."""
    at = stamp(at)
    if minutes <= 0 or minutes % 5:
        raise ValueError('Require positive five-minute intervals')
    end = at + timedelta(minutes=minutes)
    cursor = at
    while cursor < end:
        if cursor not in opens or cursor + timedelta(minutes=5) not in closes:
            return None
        cursor += timedelta(minutes=5)
    entry = number(opens[at][symbol + '_price'])
    final = number(closes[end][symbol + '_price'])
    if entry <= 0 or final <= 0:
        raise ValueError('Nonpositive reference prices')
    return (final / entry - 1) * 10000


def inventory_attribution(b_marks, c_marks, symbols, windows):
    """Exact gross delta = prior-share gap PnL + post-open-share intrabar PnL."""
    core = {}
    for name, marks in [('B', b_marks), ('C', c_marks)]:
        core[name] = unique([r for r in marks if r['phase'] in ('open_before_orders', 'bar_close')],
                            ('date', 'timestamp', 'phase'))
    if set(core['B']) != set(core['C']):
        raise ValueError('B/C bar coverage differs')
    output, prior = [], {}
    keys = sorted(k for k in core['B'] if k[2] == 'open_before_orders')
    for date, timestamp, phase in keys:
        at = stamp(timestamp); end = at + timedelta(minutes=5)
        end_key = (date, end.isoformat(), 'bar_close')
        bo, co = core['B'][(date, timestamp, phase)], core['C'][(date, timestamp, phase)]
        bc, cc = core['B'][end_key], core['C'][end_key]
        active = windows.get(date)
        if active is None:
            segment = 'day_without_revised_forecasts'
        elif at < active[0]:
            segment = 'before_first_revised_forecast'
        elif at <= active[1]:
            segment = 'revised_forecast_window'
        elif at < active[1] + timedelta(minutes=30):
            segment = 'after_last_revision_within_its_horizon'
        else:
            segment = 'after_last_revised_forecast_horizon'
        for s in symbols:
            opening, closing = number(bo[s+'_price']), number(bc[s+'_price'])
            close(opening, number(co[s+'_price'])); close(closing, number(cc[s+'_price']))
            previous = prior.get((date, s))
            qb0, qc0 = number(bo[s+'_shares']), number(co[s+'_shares'])
            qb1, qc1 = number(bc[s+'_shares']), number(cc[s+'_shares'])
            if previous:
                close(qb0, previous['B_shares']); close(qc0, previous['C_shares'])
                gap = (qb0-qc0) * (opening-previous['close_price'])
            else:
                close(qb0, 0); close(qc0, 0); gap = 0.0
            intrabar = (qb1-qc1) * (closing-opening)
            row = dict(date=date, symbol=s, bar_start=timestamp, bar_end=end.isoformat(),
                segment=segment, open_price=opening, close_price=closing,
                B_shares_before_open_orders=qb0, C_shares_before_open_orders=qc0,
                B_shares=qb1, C_shares=qc1, share_difference=qb1-qc1,
                gap_gross_pnl_difference=gap, intrabar_gross_pnl_difference=intrabar,
                gross_pnl_difference=gap+intrabar,
                abs_share_difference_dollar_minutes=abs(qb1-qc1)*opening*5)
            output.append(row); prior[(date,s)] = row
    return output


def forecast_diagnostics(decisions, training, marks):
    opens = {stamp(r['timestamp']):r for r in marks if r['phase']=='open_before_orders'}
    closes = {stamp(r['timestamp']):r for r in marks if r['phase']=='bar_close'}
    rows, contributions = [], []
    for d in decisions:
        delta = number(d['text_adjustment_full_30m']) * 10000
        if delta == 0:
            continue
        at = stamp(d['decision_at'])
        cutoff = at.replace(hour=15, minute=55, second=0, microsecond=0)
        minutes = min(30, int((cutoff-at).total_seconds()/60))
        y = reference_path(opens, closes, d['decision_at'], minutes, d['symbol'])
        c = number(d['C_mu'])*10000; effective = delta*minutes/30
        cal = training[d['date']]['text']
        if stamp(cal['training_cutoff']) >= at or d['text_fallback'] is not None:
            raise ValueError('Revised forecast lacks eligible prior calibration')
        values = dict(zip(cal['feature_names'],d['feature_vector']))
        raw = number(cal['intercept'])*10000
        for name,value,mean,scale,weight in zip(cal['feature_names'],d['feature_vector'],
                cal['means'],cal['scales'],cal['weights']):
            amount = number(weight)*(number(value)-number(mean))/number(scale)*10000
            raw += amount
            contributions.append(dict(date=d['date'],symbol=d['symbol'],decision_at=d['decision_at'],
                feature=name,value=value,contribution_bps=amount))
        close(max(-5,min(5,raw)),delta)
        residual = None if y is None else y-c
        row = dict(date=d['date'],symbol=d['symbol'],decision_at=d['decision_at'],
            realized_end_at=(at+timedelta(minutes=minutes)).isoformat(),horizon_minutes=minutes,
            C_forecast_bps=c,B_forecast_bps=c+effective,text_delta_bps=effective,
            raw_text_delta_bps=raw,intercept_bps=number(cal['intercept'])*10000,
            clip_saturated=abs(raw)>5, C_scale=d['C_scale'],
            realized_return_bps=y,realized_residual_bps=residual,
            revision_same_direction_as_residual=None if y is None else effective*residual>0,
            revision_same_direction_as_return=None if y is None else effective*y>0,
            absolute_error_B_minus_C_bps=None if y is None else abs(y-c-effective)-abs(y-c),
            squared_error_B_minus_C_bps2=None if y is None else (y-c-effective)**2-(y-c)**2,
            news_scored_fraction=values['news_scored_fraction'],
            futu_scored_fraction=values['futu_scored_fraction'],
            news_stance_balance=values['news_stance_balance'],futu_stance_balance=values['futu_stance_balance'],
            evidence_versions=len(d['evidence']),
            minimum_publication_age_hours=min((at-stamp(e['published_at'])).total_seconds()/3600 for e in d['evidence']),
            maximum_receipt_age_hours=max((at-stamp(e['received_at'])).total_seconds()/3600 for e in d['evidence']))
        rows.append(row)
    return rows, contributions


def describe_forecasts(rows):
    valid = [r for r in rows if r['realized_return_bps'] is not None]
    def mean(key):
        return sum(number(r[key]) for r in valid)/len(valid) if valid else None
    nonoverlap, ends = [], {}
    for r in sorted(valid,key=lambda x:(x['decision_at'],x['symbol'])):
        at=stamp(r['decision_at']);s=r['symbol']
        if s not in ends or at>=ends[s]:
            nonoverlap.append(r);ends[s]=stamp(r['realized_end_at'])
    return dict(rows=len(rows),valid_outcomes=len(valid),missing_outcomes=len(rows)-len(valid),
        same_direction_as_return=sum(r['revision_same_direction_as_return'] for r in valid),
        same_direction_as_residual=sum(r['revision_same_direction_as_residual'] for r in valid),
        mean_realized_return_bps=mean('realized_return_bps'),
        mean_absolute_error_B_minus_C_bps=mean('absolute_error_B_minus_C_bps'),
        mean_squared_error_B_minus_C_bps2=mean('squared_error_B_minus_C_bps2'),
        nonoverlapping_rows=len(nonoverlap),
        nonoverlapping_same_direction_as_return=sum(r['revision_same_direction_as_return'] for r in nonoverlap),
        nonoverlapping_mean_absolute_error_B_minus_C_bps=(sum(r['absolute_error_B_minus_C_bps'] for r in nonoverlap)/len(nonoverlap) if nonoverlap else None),
        independence_warning='Intervals are greedy per company; shared news and market moves remain dependent.')


def sum_rows(rows, keys, fields):
    result={}
    for row in rows:
        key=tuple(row[k] for k in keys)
        dest=result.setdefault(key,{**dict(zip(keys,key)),**dict.fromkeys(fields,0.0)})
        for field in fields:dest[field]+=number(row[field])
    return list(result.values())


def write_csv(path, rows):
    if not rows:
        path.write_text('');return
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def diagnose(comparison, output, repo):
    comparison,output,repo=Path(comparison).resolve(),Path(output).resolve(),Path(repo).resolve()
    if output.exists() or output.is_relative_to(comparison):
        raise ValueError('Choose a new output directory outside the frozen run')
    inputs={}
    def bind(path):inputs[str(path.relative_to(repo))]=sha(path);return path
    registration=read(bind(comparison/'preregistration.json'));registry=read(bind(comparison/'registry.json'))
    symbols=registration['traded_symbols']
    training={r['date']:r for r in read(bind(comparison/'training.json'))}
    with gzip.open(bind(comparison/'decisions.jsonl.gz'),'rt') as stream:
        decisions=[json.loads(line) for line in stream]
    unique(decisions,('date','symbol','decision_at'))
    source_status={}
    for name,digest in registration['source_hashes'].items():
        if sha(bind(comparison/'source'/name))!=digest:raise ValueError('Frozen source hash mismatch')
        source_status[name]={'frozen_sha256':digest,'current_sha256':sha(repo/name),
                             'current_matches_frozen':sha(repo/name)==digest}
    changed=[r for r in decisions if number(r['text_adjustment_full_30m'])!=0]
    windows={date:(min(stamp(r['decision_at']) for r in changed if r['date']==date),
                   max(stamp(r['decision_at']) for r in changed if r['date']==date)) for date in {r['date'] for r in changed}}
    forecasts=[];contributions=[];attributions=[];summary={};all_day_symbols=[]
    for cost in registration['cost_scenarios_bps_per_side']:
        model={}
        for name in ('B','C'):
            model[name]={kind:csv_rows(bind(comparison/f'cost_{cost:g}bps'/name/f'{kind}.csv.gz'))
                         for kind in ('daily','fills','marks')}
        bd,cd=(unique(model[n]['daily'],('date',)) for n in ('B','C'))
        if set(bd)!=set(cd):raise ValueError('Daily coverage mismatch')
        day_symbols=[]
        for datekey in sorted(bd):
            date=datekey[0];b,c=bd[datekey],cd[datekey]
            for s in symbols:
                values={}
                for n in ('B','C'):
                    fills=[r for r in model[n]['fills'] if r['date']==date and r['symbol']==s]
                    daily=bd[datekey] if n=='B' else cd[datekey]
                    net=-sum(number(r['quantity'])*number(r['fill_price'])+number(r['commission_cost']) for r in fills)
                    costs=sum(number(r['cost']) for r in fills)
                    if sum(number(r['quantity']) for r in fills)!=0:raise ValueError('Day not flat')
                    close(net,number(daily[s+'_net_pnl']));close(costs,number(daily[s+'_costs']))
                    values.update({n+'_net_pnl':net,n+'_costs':costs,n+'_gross_pnl':net+costs,n+'_fills':len(fills)})
                day_symbols.append(dict(cost_bps_per_side=cost,date=date,symbol=s,**values,
                    net_pnl_difference=values['B_net_pnl']-values['C_net_pnl'],
                    gross_pnl_difference=values['B_gross_pnl']-values['C_gross_pnl'],
                    cost_difference=values['B_costs']-values['C_costs'],
                    fill_count_difference=values['B_fills']-values['C_fills']))
        path=inventory_attribution(model['B']['marks'],model['C']['marks'],symbols,windows)
        gross={(r['date'],r['symbol']):r['gross_pnl_difference'] for r in sum_rows(path,['date','symbol'],['gross_pnl_difference'])}
        for r in day_symbols:close(r['gross_pnl_difference'],gross[(r['date'],r['symbol'])])
        for r in path:r['cost_bps_per_side']=cost
        attributions.extend(path);all_day_symbols.extend(day_symbols)
        fields=['net_pnl_difference','gross_pnl_difference','cost_difference','fill_count_difference']
        totals=sum_rows(day_symbols,[],fields)[0]
        for field,saved in [('net_pnl_difference','net_pnl'),('gross_pnl_difference','gross_pnl'),('cost_difference','costs'),('fill_count_difference','fill_count')]:
            close(totals[field],registry['results'][f'{cost:g}bps_B'][saved]-registry['results'][f'{cost:g}bps_C'][saved])
        summary[f'{cost:g}bps']=dict(totals=totals,by_symbol=sum_rows(day_symbols,['symbol'],fields),
            by_date=[r for r in sum_rows(day_symbols,['date'],fields) if any(abs(r[k])>1e-7 for k in fields)],
            gross_by_signal_phase=sum_rows(path,['date','segment'],['gross_pnl_difference','abs_share_difference_dollar_minutes']),
            divergent_position_bars=sum(r['share_difference']!=0 for r in path),
            divergent_position_bars_without_revised_forecasts=sum(r['share_difference']!=0 and r['date'] not in windows for r in path))
        if cost==2:forecasts,contributions=forecast_diagnostics(decisions,training,model['C']['marks'])
    evidence={}
    normalized_cache={}
    def clean(value):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',str(value or '')))).strip()
    for d in changed:
        for e in d['evidence']:
            key=e['source']+':'+e['source_id']+':'+e['content_hash']
            if key in evidence:continue
            source=Path(e['provenance']['normalized_file']).resolve()
            if not source.is_relative_to(repo/'reports'):raise ValueError('Evidence outside report archive')
            if source not in normalized_cache:normalized_cache[source]=read(bind(source))
            original=normalized_cache[source][e['provenance']['normalized_row']]
            title=clean(original.get('headline',original.get('title')));body=clean(original.get('text',original.get('excerpt')))
            if hashlib.sha256((title+'\n'+body).encode()).hexdigest()!=e['content_hash']:raise ValueError('Evidence version changed')
            evidence[key]={**{k:e[k] for k in ('source','source_id','published_at','updated_at','received_at','available_at','receipt_verified')},
                           'title':title,'vendor_symbol_tags':original.get('symbols',[])}
    training_support=[]
    for date in sorted(windows):
        cal=training[date]['text'];cutoff=stamp(cal['training_cutoff']);eligible=[]
        for d in decisions:
            at=stamp(d['decision_at']);end=at+timedelta(minutes=30)
            if d['has_text'] and end<cutoff and end<=at.replace(hour=15,minute=55,second=0,microsecond=0):eligible.append(d)
        if len(eligible)!=cal['training_text_rows']:raise ValueError('Training support count mismatch')
        ev=[e for d in eligible for e in d['evidence']]
        training_support.append(dict(prediction_date=date,training_rows=len(eligible),training_sessions=cal['training_sessions'],
            unique_received_dates=sorted({e['received_at'][:10] for e in ev}),
            unique_text_versions=len({(e['source'],e['source_id'],e['content_hash']) for e in ev}),
            rows_with_scored_news=sum(d['feature_vector'][cal['feature_names'].index('news_scored_fraction')]>0 for d in eligible),
            intercept_bps=cal['intercept']*10000,nonoverlapping_company_intervals=cal['nonoverlapping_intervals_per_company_total']))
    result=dict(schema_version=1,generated_at=datetime.now(timezone.utc).isoformat(),
        evaluation_kind='retrospective_development_diagnostic',replayed=False,models_fit=0,
        scenarios=summary,forecast_diagnostics={'all':describe_forecasts(forecasts),
            'by_symbol':{s:describe_forecasts([r for r in forecasts if r['symbol']==s]) for s in symbols},
            'all_revisions_clipped':all(r['clip_saturated'] for r in forecasts),
            'all_revisions_when_price_scale_zero':all(r['C_scale']==0 for r in forecasts),
            'rows_with_scored_news':sum(r['news_scored_fraction']>0 for r in forecasts),
            'rows_with_scored_futu':sum(r['futu_scored_fraction']>0 for r in forecasts)},
        training_support=training_support,changed_forecast_evidence=list(evidence.values()),
        contribution_mean_bps={s:{r['feature']:r['contribution_bps']/len([x for x in forecasts if x['symbol']==s])
            for r in sum_rows([x for x in contributions if x['symbol']==s],['feature'],['contribution_bps'])}
            for s in {x['symbol'] for x in forecasts}},
        source_status=source_status,input_hashes=inputs,source_sha256=sha(__file__),
        limitations=['All prices and fills are saved hypothetical replay evidence, not broker results.',
            'Overlapping labels, shared news versions and only one revised-forecast date prohibit an independence or significance claim.',
            'Feature contributions depend on centering and correlated inputs; they are not causal sentiment effects.',
            'Later-day B/C differences can persist through equity and integer sizing after text deltas become zero.',
            'Holding-horizon diagnostics do not prove that exiting sooner would improve returns.',
            'No candidate was retuned, selected, promoted, or reexecuted by this diagnostic.'])
    output.mkdir(parents=True,mode=0o700);(output/'.gitignore').write_text('*\n')
    (output/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    write_csv(output/'day_symbol_attribution.csv',all_day_symbols)
    write_csv(output/'inventory_path.csv',attributions)
    write_csv(output/'forecast_diagnostics.csv',forecasts)
    write_csv(output/'feature_contributions.csv',contributions)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parents[1]
    parser.add_argument('--repo',type=Path,default=root)
    parser.add_argument('--comparison',type=Path,default=root/'reports/quant_logic_review_20261028/comparison_v1')
    parser.add_argument('--output',type=Path,default=root/'reports/quant_logic_review_20261028/followup_signal_diagnostics/sentiment_increment_v1')
    args=parser.parse_args();result=diagnose(args.comparison,args.output,args.repo)
    print(json.dumps({'scenarios':{k:v['totals'] for k,v in result['scenarios'].items()},
                      'forecast_diagnostics':result['forecast_diagnostics']},indent=2))
