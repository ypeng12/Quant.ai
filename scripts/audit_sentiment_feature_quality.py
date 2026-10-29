#!/usr/bin/env python3
"""Read-only diagnostics for frozen comparison_v1 text features; never fit models.

Source associations and literal-name matches are proxies, not semantic gold labels.
This program reads only the explicit replay and its hash-bound normalized evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
FEATURES = ("news_log_count", "futu_log_count", "news_stance_balance", "futu_stance_balance",
            "news_scored_fraction", "futu_scored_fraction", "unique_text_fraction",
            "mean_publication_age_fraction", "mean_receipt_age_fraction", "any_text_missing",
            "news_missing", "futu_missing")
GROUPS = {"lexical_direction": FEATURES[2:4], "lexical_coverage": FEATURES[4:6],
          "volume": FEATURES[:2], "title_diversity_proxy": FEATURES[6:7],
          "age": FEATURES[7:9], "missingness": FEATURES[9:]}
ALIASES = {"NVDA": r"\b(?:NVDA|NVIDIA)\b|英伟达|英偉達",
           "SNDK": r"\b(?:SNDK|SANDISK)\b|闪迪|閃迪",
           "TSLA": r"\b(?:TSLA|TESLA)\b|特斯拉"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dt(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Aware evidence clocks are required")
    return value


def stats(values):
    values = list(values)
    if not values:
        return {"n": 0, "minimum": None, "maximum": None, "mean": None,
                "std": None, "mean_absolute": None, "nonzero": 0, "distinct_rounded_10dp": 0}
    mean = sum(values) / len(values)
    return dict(n=len(values), minimum=min(values), maximum=max(values), mean=mean,
                std=math.sqrt(sum((v-mean)**2 for v in values)/len(values)),
                mean_absolute=sum(abs(v) for v in values)/len(values),
                nonzero=sum(abs(v)>1e-12 for v in values),
                distinct_rounded_10dp=len({round(v, 10) for v in values}))


def feature_stats(rows):
    return {name: stats(row["feature_vector"][i] for row in rows) for i,name in enumerate(FEATURES)}


def association(symbol, observation):
    """Literal mentions do not certify entity-specific sentiment or relevance."""
    title, body = observation["title"], observation["text"]
    pattern = ALIASES[symbol]
    return dict(target_mentioned_in_title=bool(re.search(pattern,title,re.I)),
                target_mentioned_in_title_or_excerpt=bool(re.search(pattern,title+" "+body,re.I)),
                source_symbol_count=len(observation["symbols"]),
                multi_ticker_tokens=len(set(re.findall(r"\(([A-Z][A-Z0-9.\-]*)\.US\)", title+" "+body))),
                semantic_relevance_verified=False)


def key(e):
    return (e["source"], e["source_id"], e["content_hash"])


def full_horizon(row):
    at = dt(row["decision_at"]).astimezone(NY)
    return at + timedelta(minutes=30) <= at.replace(hour=15,minute=55)


def training_rows(rows, cutoff):
    cutoff = dt(cutoff)
    return [r for r in rows if r["has_text"] and full_horizon(r)
            and dt(r["decision_at"])+timedelta(minutes=30) < cutoff]


def nonoverlap_count(rows):
    ends, count = {}, 0
    for row in sorted(rows,key=lambda r:(dt(r["decision_at"]),r["symbol"])):
        at, symbol = dt(row["decision_at"]), row["symbol"]
        if symbol not in ends or at >= ends[symbol]:
            count += 1
            ends[symbol] = at+timedelta(minutes=30)
    return count


def dependence(rows):
    batches, exposure, source_company, evidence_sets = Counter(), Counter(), Counter(), set()
    receipt_dates, versions, symbol_versions, decisions_by_date = set(), set(), set(), Counter()
    adjacent, unchanged = 0, 0
    previous = {}
    for row in sorted(rows,key=lambda r:(dt(r["decision_at"]),r["symbol"])):
        es = row["evidence"]
        version_set = tuple(sorted(key(e) for e in es))
        evidence_sets.add((row["symbol"],version_set))
        at=dt(row["decision_at"]); old=previous.get(row["symbol"])
        if old and at-old[0]==timedelta(minutes=5):
            adjacent += 1
            unchanged += old[1]==version_set
        previous[row["symbol"]]=(at,version_set)
        for e in es:
            receipt_dates.add(dt(e["received_at"]).astimezone(NY).date().isoformat())
            versions.add(key(e)); symbol_versions.add((row["symbol"],key(e)))
            exposure["|".join(key(e)[:2])] += 1
        for batch in {e["provenance"]["response_file"] for e in es}:
            batches[batch] += 1
        source_company[(row["symbol"],"+".join(sorted({e["source"] for e in es})))] += 1
        decisions_by_date[row["date"]] += 1
    weights=list(batches.values())
    return dict(rows=len(rows),decision_dates=dict(decisions_by_date),receipt_dates=sorted(receipt_dates),
                retained_response_batches=len(batches),batch_decision_exposures=dict(batches),
                capture_weight_concentration_equivalent_batches=(sum(weights)**2/sum(v*v for v in weights) if weights else None),
                unique_document_versions=len(versions),unique_company_document_associations=len(symbol_versions),
                unique_company_evidence_sets=len(evidence_sets),
                consecutive_five_minute_pairs=adjacent,consecutive_pairs_same_evidence_set=unchanged,
                company_source_rows=[dict(company=s,source=src,rows=n) for (s,src),n in sorted(source_company.items())],
                most_reused_documents=[dict(source_id=k,decision_exposures=n) for k,n in exposure.most_common(10)],
                independent_semantic_events=None,
                interpretation="Distinct responses/dates and concentration are descriptive, not certified independent events or statistical effective sample sizes.")


def rank(matrix, tolerance=1e-8):
    a=[list(row) for row in matrix]; row=0
    for col in range(len(a[0]) if a else 0):
        pivot=max(range(row,len(a)),key=lambda i:abs(a[i][col]),default=None)
        if pivot is None or abs(a[pivot][col]) <= tolerance: continue
        a[row],a[pivot]=a[pivot],a[row]; scale=a[row][col]
        a[row]=[v/scale for v in a[row]]
        for i in range(row+1,len(a)):
            scale=a[i][col];a[i]=[x-scale*y for x,y in zip(a[i],a[row])]
        row+=1
        if row==len(a):break
    return row


def collinearity(rows):
    columns=list(zip(*(r["feature_vector"] for r in rows)))
    means=[sum(c)/len(c) for c in columns]
    scales=[math.sqrt(sum((v-m)**2 for v in c)/len(c)) for c,m in zip(columns,means)]
    z=[[((v-m)/s if s>1e-9 else 0) for v,m,s in zip(r["feature_vector"],means,scales)] for r in rows]
    corr=[[sum(v[i]*v[j] for v in z)/len(z) for j in range(len(FEATURES))] for i in range(len(FEATURES))]
    return dict(constant_features=[n for n,s in zip(FEATURES,scales) if s<=1e-9],
                near_perfect_pairs=[dict(left=FEATURES[i],right=FEATURES[j],correlation=corr[i][j])
                                    for i in range(len(FEATURES)) for j in range(i+1,len(FEATURES)) if abs(corr[i][j])>=.98],
                centered_standardized_gram_rank=rank(corr),rank_tolerance=1e-8)


def contributions(row, calibration, cap_bps=5):
    pieces={name:10000*w*(v-m)/s for name,v,m,s,w in zip(FEATURES,row["feature_vector"],
              calibration["means"],calibration["scales"],calibration["weights"])}
    intercept=calibration["intercept"]*10000
    raw=intercept+sum(pieces.values()); clipped=max(-cap_bps,min(cap_bps,raw))
    saved=row["text_adjustment_full_30m"]*10000
    if abs(saved-clipped)>2e-6:
        raise ValueError("Contribution arithmetic does not reconcile with saved delta")
    return dict(symbol=row["symbol"],decision_at=row["decision_at"],intercept_bps=intercept,
                raw_bps=raw,saved_bps=saved,clip_bps=clipped-raw,
                groups_bps={group:sum(pieces[n] for n in names) for group,names in GROUPS.items()},
                features_bps=pieces)


def audit(root, comparison):
    inputs={}
    def read(path):
        inputs[str(path.resolve())]=digest(path)
        return json.loads(path.read_text())
    registry=read(comparison/'registry.json'); source=read(comparison/'text_source_audit.json')
    training=read(comparison/'training.json')
    path=comparison/'decisions.jsonl.gz';inputs[str(path.resolve())]=digest(path)
    with gzip.open(path,'rt') as f: rows=[json.loads(line) for line in f]
    versions={name:dict(expected=h,actual=digest(root/name)) for name,h in registry['source_hashes'].items()}
    if any(v['expected']!=v['actual'] for v in versions.values()):
        raise ValueError('Run-bound source differs; do not reinterpret frozen features with changed code')
    module_path=root/'research/financial_sentiment_using_prices/quant_signal_adapter.py'
    spec=importlib.util.spec_from_file_location('frozen_feature_adapter',module_path)
    adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    assert tuple(adapter.FEATURE_NAMES)==FEATURES
    cache, observations, associations={}, {}, {}
    for row in rows:
        for e in row['evidence']:
            p=Path(e['provenance']['normalized_file']).resolve()
            if not p.is_relative_to((root/'reports').resolve()) or str(p) not in source['input_sha256']:
                raise ValueError('Evidence source is outside retained allowlist')
            if p not in cache:
                if digest(p)!=source['input_sha256'][str(p)]:raise ValueError('Evidence input hash mismatch')
                cache[p]=read(p)
            original=cache[p][e['provenance']['normalized_row']]
            title=original.get('headline',original.get('title',''))
            text=original.get('text',original.get('excerpt',''))
            obs=adapter.make_observation(source=e['source'],source_id=e['source_id'],
                symbols=original['symbols'] if e['source']=='news' else [original['query_symbol']],
                title=title,text=text,published_at=e['published_at'],updated_at=e['updated_at'],
                received_at=e['received_at'],receipt_verified=e['receipt_verified'])
            if obs['content_hash']!=e['content_hash']:raise ValueError('Evidence version content changed')
            observations[key(e)]=obs
            score,known=adapter._stance(obs)
            associations[(row['symbol'],key(e))]=dict(symbol=row['symbol'],source=e['source'],source_id=e['source_id'],
                title=obs['title'][:180],source_symbols=obs['symbols'],stance_known=known,stance=score if known else None,
                **association(row['symbol'],obs))
    text_rows=[r for r in rows if r['has_text']]
    for row in text_rows:
        snap=adapter.build_asof_features([observations[key(e)] for e in row['evidence']],row['symbol'],row['decision_at'])
        if any(abs(a-b)>1e-9 for a,b in zip(snap['feature_vector'],row['feature_vector'])):
            raise ValueError('Saved feature values differ from frozen extraction semantics')
    applied=[r for r in rows if r['text_fallback'] is None]
    calibrations={t['date']:t['text'] for t in training}
    training_checks=[]
    for t in training:
        c=t['text']; used=training_rows(rows,c['training_cutoff'])
        if len(used)!=c['training_text_rows'] or len({r['date'] for r in used})!=c['training_sessions'] or nonoverlap_count(used)!=c['nonoverlapping_intervals_per_company_total']:
            raise ValueError('Training cohort reconstruction does not match frozen receipt')
        if c['status']=='fitted_development_only':
            for i in range(len(FEATURES)):
                if abs(sum(r['feature_vector'][i] for r in used)/len(used)-c['means'][i])>1e-9:
                    raise ValueError('Training feature mean mismatch')
            training_checks.append(dict(date=t['date'],status=c['status'],intercept_bps=c['intercept']*10000,
                 gates=c['gates'],recorded_nonoverlap_intervals=c['nonoverlapping_intervals_per_company_total'],
                 dependency=dependence(used),collinearity=collinearity(used),features=feature_stats(used)))
    first_date=min(r['date'] for r in applied);first_used=training_rows(rows,calibrations[first_date]['training_cutoff'])
    train_keys={key(e) for r in first_used for e in r['evidence']}
    applied_keys={key(e) for r in applied for e in r['evidence']}
    explained=[contributions(r,calibrations[r['date']]) for r in applied]
    source_relevance=[]
    for symbol in registry['traded_symbols']:
        for src in ('news','futu'):
            matches=[v for v in associations.values() if v['symbol']==symbol and v['source']==src]
            source_relevance.append(dict(symbol=symbol,source=src,unique_company_document_associations=len(matches),
                title_target_mentions=sum(v['target_mentioned_in_title'] for v in matches),
                title_or_excerpt_target_mentions=sum(v['target_mentioned_in_title_or_excerpt'] for v in matches),
                multi_source_symbol_tags=sum(v['source_symbol_count']>1 for v in matches),
                stance_known=sum(v['stance_known'] for v in matches)))
    bc={}
    for cost in (2,5):
        b,c=(registry['results'][f'{cost}bps_{m}'] for m in ('B','C'))
        bc[str(cost)]=dict(net_pnl_difference=b['net_pnl']-c['net_pnl'],gross_pnl_difference=b['gross_pnl']-c['gross_pnl'],
                          incremental_costs=b['costs']-c['costs'],incremental_fills=b['fill_count']-c['fill_count'])
    return dict(schema_version=1,diagnostic_only=True,models_fit=0,orders_sent=0,existing_replay_modified=False,
        source_version_verification=versions,input_sha256=inputs,frozen_archive_counts={k:source[k] for k in ('normalized_rows_before_deduplication','retained_versions','versions_with_verified_receipt')},
        coverage=dict(decisions=len(rows),text_rows=len(text_rows),applied_rows=len(applied),
                      fallback_counts=dict(Counter(str(r['text_fallback']) for r in rows)),text_dependency=dependence(text_rows)),
        feature_meaning={name:next(group for group,names in GROUPS.items() if name in names) for name in FEATURES},
        features_text_available=feature_stats(text_rows),features_applied=feature_stats(applied),
        source_relevance_proxies=source_relevance,company_document_audit=list(associations.values()),
        fitted_training_cohorts=training_checks,
        applied_evidence_reuse=dict(unique_document_versions=len(applied_keys),already_in_first_training=len(applied_keys&train_keys),
            new_versions=len(applied_keys-train_keys),applied_rows_without_known_news_or_futu_stance=sum(r['feature_vector'][4]==0 and r['feature_vector'][5]==0 for r in applied),
            associations=[v for (_,k),v in associations.items() if k in applied_keys]),
        applied_arithmetic=dict(intercept_bps=stats(r['intercept_bps'] for r in explained),
            raw_bps=stats(r['raw_bps'] for r in explained),saved_bps=stats(r['saved_bps'] for r in explained),
            clipped_count=sum(abs(r['raw_bps'])>5 for r in explained),
            groups_bps={g:stats(r['groups_bps'][g] for r in explained) for g in GROUPS},
            features_bps={n:stats(r['features_bps'][n] for r in explained) for n in FEATURES},rows=explained),
        B_minus_C_saved_portfolio_results=bc,
        limitations=[
            'No retraining or ablation portfolio replay was performed. Contribution magnitudes are arithmetic, not causal PnL attribution.',
            'Name mentions and vendor tags are reproducible relevance proxies; no independent human entity/event/stance gold labels exist.',
            'Response batches and article IDs are not verified independent semantic events; adjacent/overlapping labels and repeated evidence create dependence.',
            'A nonzero standardized contribution can exist when an observed stance is zero because the training mean is nonzero; this is not current bullish/bearish evidence.',
            'Age, volume, source coverage, missingness, exact-title diversity and intercept are not financial sentiment. Lexical stance is a narrow rule, not calibrated NLP.',
            'The inspected historical sample is development evidence. It cannot validate a new event threshold or establish future alpha.'],
        proposed_repairs=[
            'Before assigning company stance, bind claim subject/object to company or sector; separate broad market articles and cross-company spillovers from direct company evidence.',
            'Add event ID/version and receipt capture group. Gate calibration on distinct validated events and receipt days, with per-event weight caps and company/source coverage; default C until fixed preregistered coverage is met.',
            'Freeze language-specific entity, negation/question, sarcasm/ambiguity and explicit horizon labels; uncertain posts remain unknown. Chinese question particles such as 嗎 must not become bullish votes merely because they contain 買入.',
            'Separate 30-minute surprise/short-lived events from 5/10/20-session thesis hypotheses; do not force 48-hour-old metadata onto a 30-minute expected return without prospective evidence.',
            'Keep a separately estimated prior-only intercept/price residual control and explicit source/company terms so stale-source effects are not marketed as sentiment.',
            'Do not reverse Futu blindly: test company-specific contrarian stance versus momentum with fixed horizons, event grouping and equal risk/cost rules.'],
        fixed_ablation_protocol=dict(status='proposed_not_executed',
            arms=['C exact price-only','C plus prior-only constant residual/intercept',
                  'C plus missingness/age only','C plus nonsemantic metadata: count, diversity, missingness, age',
                  'C plus entity-validated semantic features and fixed coverage flags','C plus all frozen eligible features',
                  'C plus semantic features shuffled within training company/source/horizon and capture-event blocks using fixed seeds'],
            controls=['Register every arm, exact event eligibility, horizon, penalties, clip and seeds before collecting the next untouched interval; publish all arms.',
                      'Use identical C forecasts, calendar, outcome horizon, missing fallback, starting cash, risk constraints, transaction/borrow assumptions and execution timing for every arm.',
                      'Fit preprocessing and residual parameters only on earlier mature training outcomes. Group split by event/version/capture across companies and purge overlapping label windows; do not bar-shuffle.',
                      'Shuffle only training semantic-feature assignments among comparable independent event groups; preserve test clocks, missingness, age, volume, company and source. Keep test feature assignment unchanged as the registered null.',
                      'Report all held-out forecast metrics, B-minus-C returns/costs/exposure/turnover and cluster-bootstrap intervals by event/capture and day. Include failures and negative results.',
                      'Require new independent prospective event/capture coverage; the two old receipt dates cannot support convincing significance or tuning.']))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=ROOT)
    parser.add_argument('--comparison',type=Path,default=ROOT/'reports/quant_logic_review_20261028/comparison_v1')
    parser.add_argument('--output',type=Path,default=ROOT/'reports/quant_logic_review_20261028/followup_signal_diagnostics/data_quality.json')
    args=parser.parse_args()
    if args.output.resolve().is_relative_to(args.comparison.resolve()):raise ValueError('Frozen comparison is read-only')
    if args.output.exists():raise ValueError('Use a new diagnostics output; existing evidence is not overwritten')
    result=audit(args.repo.resolve(),args.comparison.resolve())
    result['diagnostic_generator_sha256']=digest(Path(__file__))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    args.output.chmod(0o600)
    print(json.dumps(dict(output=str(args.output),decisions=result['coverage']['decisions'],
                         applied=result['coverage']['applied_rows'],clipped=result['applied_arithmetic']['clipped_count'])))


if __name__=='__main__':main()
