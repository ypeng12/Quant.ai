"""Reproduce the Sept 14 timing, raw L1 quality and filled-position audit.

Run from repository root: python3 scripts/audit_alpha_followup.py
All costs are historical simulation assumptions, not verified broker charges.
"""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.research.holding_policy import executable_labels
from app.quant_policy import normalize_bars

DAY = '2026-09-14'
OUT = ROOT / 'reports/alpha_followup_audit_20260914'
LAB = ROOT / 'reports/holding_today_lab_20260914'
L1 = ROOT / 'reports/holding_l1_evidence_20260914'
inputs = {}


def record(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    inputs[str(path)] = h.hexdigest()
    return path


def csv(path):
    return pd.read_csv(record(path))


def period(stamp):
    return 'opening' if stamp.hour < 10 or (stamp.hour == 10 and stamp.minute < 30) else ('midday' if stamp.hour < 14 else 'closing')


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    timeline = csv(ROOT/'reports/sndk_day_audit_20260914/SNDK_20260914_COMPLETE_TIMELINE.csv')
    timeline.index = pd.to_datetime(timeline.signal_bar_open_et, utc=True).dt.tz_convert('America/New_York')
    bars = normalize_bars(pd.read_parquet(record(LAB/'bars/SNDK.parquet')))
    aligned = []
    accuracy = []
    for pred, horizon in [('deployed_expected_5m_bps', 1), ('calibrated_context_curve_cal_15m_bps', 3)]:
        y, maturity = executable_labels(bars, horizon)
        target = y.reindex(timeline.index)*10000
        np.testing.assert_allclose(target, timeline[f'realized_next_{horizon*5}m_bps'], equal_nan=True, atol=1e-8)
        x = pd.DataFrame({'signal_bar_open': timeline.index, 'available_at': timeline.index+pd.Timedelta(minutes=5),
                          'label_end': maturity.reindex(timeline.index), 'prediction_bps': timeline[pred], 'future_bps': target})
        x['model'] = pred
        x['period'] = [period(t) for t in x.index]
        x['valid'] = np.isfinite(x.prediction_bps) & np.isfinite(x.future_bps)
        x['correct'] = np.where(x.valid, (np.sign(x.prediction_bps)==np.sign(x.future_bps)).astype(float), np.nan)
        aligned.append(x)
        for p, g in x.groupby('period', sort=False):
            accuracy.append(dict(model=pred, period=p, bars=len(g), valid=int(g.valid.sum()),
                                 excluded=int((~g.valid).sum()), correct=int(g.correct.sum()), accuracy=g.correct.mean()))
    pd.concat(aligned).to_csv(OUT/'direction_rows.csv', index=False)
    pd.DataFrame(accuracy).to_csv(OUT/'direction_summary.csv', index=False)

    result = json.loads(record(L1/'result.json').read_text())
    quality = []
    for symbol in ['SNDK', 'TSLA', 'PLTR', 'NVDA']:
        events = {}
        for kind in ['quote', 'trade']:
            selected = [i for i in result['inputs'] if f'/{DAY}/{symbol}.jsonl' in i['path'] and f'_{kind}s/' in i['path']]
            assert len(selected)==1, (symbol, kind)
            p = record(selected[0]['path'])
            assert inputs[str(p)] == selected[0]['sha256'], f'Raw source changed: {p}'
            cols = ['timestamp','bid_price','ask_price','bid_size','ask_size'] if kind=='quote' else ['timestamp','price','size']
            rows = []
            with p.open() as f:
                for line in f:
                    r = json.loads(line)
                    if r.get('event_type') == kind:
                        rows.append([r.get(c) for c in cols])
            d = pd.DataFrame(rows, columns=cols)
            d['timestamp'] = pd.to_datetime(d.timestamp, utc=True, format='mixed').dt.tz_convert('America/New_York')
            events[kind] = d.sort_values('timestamp', kind='stable').set_index('timestamp')
        q, t = events['quote'], events['trade']
        depth = q.bid_size+q.ask_size
        q['qi'] = (q.bid_size-q.ask_size)/depth.replace(0,np.nan)
        q['spread'] = (q.ask_price-q.bid_price)/((q.ask_price+q.bid_price)/2)*10000
        q['last_quote'] = q.index
        q['gap_seconds'] = q.index.to_series().diff().dt.total_seconds()
        f = pd.read_parquet(record(L1/f'{symbol}_{DAY}_features.parquet'))
        b = q.resample('5min')
        detail = pd.DataFrame(index=f.index)
        detail['quote_count'] = b.size().reindex(f.index).fillna(0)
        detail['raw_last_qi'] = b.qi.last().reindex(f.index)
        detail['stored_qi'] = f.l1_quote_imbalance
        detail['equal_size_quote_fraction'] = q.bid_size.eq(q.ask_size).resample('5min').mean().reindex(f.index)
        detail['last_quote_age_seconds'] = (detail.index.to_series()+pd.Timedelta(minutes=5)-b.last_quote.last().reindex(f.index)).dt.total_seconds()
        detail['max_interquote_gap_seconds'] = b.gap_seconds.max().reindex(f.index)
        detail['stored_spread_bps'] = f.l1_spread_bps
        detail['missing_features'] = f.apply(lambda r: ','.join(r.index[r.isna()]), axis=1)
        detail['last_quote_age_gt_30s'] = detail.last_quote_age_seconds.gt(30)
        detail['quote_state'] = np.where(detail.quote_count.eq(0), 'missing_quotes', np.where(detail.raw_last_qi.isna(),'undefined_depth',np.where(detail.raw_last_qi.eq(0),'equal_positive_sizes','unequal_sizes')))
        np.testing.assert_allclose(detail.raw_last_qi, detail.stored_qi, equal_nan=True, atol=1e-10)
        np.testing.assert_allclose(b.spread.median().reindex(f.index), f.l1_spread_bps, equal_nan=True, atol=1e-8)
        np.testing.assert_allclose(detail.quote_count, f.l1_quote_updates)
        m = pd.merge_asof(t.reset_index(), q[['bid_price','ask_price']].reset_index().rename(columns={'timestamp':'quote_timestamp'}),
                          left_on='timestamp',right_on='quote_timestamp',direction='backward',allow_exact_matches=False,tolerance=pd.Timedelta(seconds=30))
        m['reason'] = np.select([m.quote_timestamp.isna(),m.ask_price.le(m.bid_price),m.price.ge(m.ask_price),m.price.le(m.bid_price)],
                                ['no_prior_quote_within_30s','locked_or_crossed','at_or_above_ask','at_or_below_bid'],default='inside_spread_unclassified')
        m['bucket'] = m.timestamp.dt.floor('5min')
        reasons = m.reason.value_counts().to_dict()
        counts = m.groupby(['bucket','reason']).size().unstack(fill_value=0).reindex(f.index).fillna(0)
        detail = detail.join(counts.add_prefix('trades__'))
        signed = np.select([m.reason.eq('at_or_above_ask'),m.reason.eq('at_or_below_bid')],[1.,-1.], default=np.nan)
        num = pd.Series(signed*m['size'].to_numpy(), index=m.timestamp).resample('5min').sum(min_count=1)
        den = pd.Series(np.where(np.isfinite(signed),m['size'],np.nan), index=m.timestamp).resample('5min').sum(min_count=1)
        np.testing.assert_allclose((num/den).reindex(f.index),f.l1_signed_trade_imbalance,equal_nan=True,atol=1e-10)
        detail.to_csv(OUT/f'{symbol}_quote_quality.csv',index_label='bar_open_et')
        m[['timestamp','quote_timestamp','price','size','reason']].to_csv(OUT/f'{symbol}_trade_classification.csv',index=False)
        quality.append(dict(symbol=symbol,quote_events=int(detail.quote_count.sum()),zero_last_qi_bars=int(detail.stored_qi.eq(0).sum()),
            missing_quote_bars=int(detail.quote_count.eq(0).sum()),last_quote_older_30s_bars=int(detail.last_quote_age_gt_30s.sum()),
            median_last_quote_age_seconds=detail.last_quote_age_seconds.median(),max_last_quote_age_seconds=detail.last_quote_age_seconds.max(),
            missing_signed_trade_bars=int(f.l1_signed_trade_imbalance.isna().sum()),
            other_missing_feature_bars=int(f.drop(columns='l1_signed_trade_imbalance').isna().any(axis=1).sum()),
            trade_count=len(m),inside_spread_unclassified_trades=int(reasons.get('inside_spread_unclassified',0)),
            no_prior_quote_within_30s_trades=int(reasons.get('no_prior_quote_within_30s',0)),
            mean_bucket_median_spread_bps=f.l1_spread_bps.mean()))
        print('Verified raw L1:',symbol,flush=True)
    pd.DataFrame(quality).to_csv(OUT/'quality_summary.csv',index=False)

    paths = {'context':LAB/'calibrated_context_curve/fills.csv','hold':LAB/'equal_weight_hold/fills.csv',
             'l1_base':L1/'base_fills.csv','l1_plus':L1/'plus_l1_fills.csv'}
    summaries, intervals = [], []
    for strategy, path in paths.items():
        fills = csv(path)
        for symbol, g in fills.groupby('symbol',sort=False):
            g=g.copy();g['ts']=pd.to_datetime(g.fill_time,utc=True).dt.tz_convert('America/New_York');g=g.sort_values('ts',kind='stable')
            position=0.;previous_price=None;previous_time=None;pieces=[]
            for r in g.itertuples():
                assert r.side in ('buy','sell')
                delta=abs(r.quantity)*(1 if r.side=='buy' else -1)
                gross=0. if previous_price is None else position*(r.reference_price-previous_price)
                pieces.append(gross)
                intervals.append(dict(strategy=strategy,symbol=symbol,start=previous_time,end=r.ts,shares_held=position,
                    start_reference_price=previous_price,end_reference_price=r.reference_price,gross_pnl=gross,
                    end_fill_assumed_cost=r.cost,net_increment=gross-r.cost,shares_after=position+delta))
                position+=delta
                assert abs(position-r.shares_after)<1e-8
                previous_price=r.reference_price;previous_time=r.ts
            assert abs(position)<1e-8
            sign=g.side.map({'buy':1,'sell':-1});qty=g.quantity.abs()
            cash_net=-(sign*qty*g.fill_price).sum()-g.commission_cost.sum()
            net=sum(pieces)-g.cost.sum()
            assert abs(net-cash_net)<1e-6
            summaries.append(dict(strategy=strategy,symbol=symbol,gross_pnl=sum(pieces),assumed_cost=g.cost.sum(),net_pnl=net,
                fills=len(g),turnover_dollars=(qty*g.reference_price).sum(),cash_reconciliation_error=net-cash_net))
    pd.DataFrame(intervals).to_csv(OUT/'filled_position_intervals.csv',index=False)
    summary=pd.DataFrame(summaries);summary.to_csv(OUT/'pnl_summary.csv',index=False)
    delta=summary[summary.strategy.eq('l1_plus')].set_index('symbol')[['gross_pnl','assumed_cost','net_pnl','fills','turnover_dollars']]-summary[summary.strategy.eq('l1_base')].set_index('symbol')[['gross_pnl','assumed_cost','net_pnl','fills','turnover_dollars']]
    delta.to_csv(OUT/'l1_incremental_attribution.csv')
    # Exact filled-position marks: each row includes price PnL plus explicit modeled cost events.
    attr=csv(LAB/'calibrated_context_curve/attribution.csv')
    sndk=attr[attr.symbol.eq('SNDK')]
    np.testing.assert_allclose(sndk.net_pnl.sum(),summary.query("strategy=='context' and symbol=='SNDK'").net_pnl.iloc[0],atol=1e-6)
    gains=sndk.loc[sndk.gross_pnl>0,'gross_pnl'].sum();loss=-sndk.loc[sndk.gross_pnl<0,'gross_pnl'].sum()
    attr.groupby(['symbol','hour','direction'])[['gross_pnl','costs','net_pnl']].sum().to_csv(OUT/'context_hourly_attribution.csv')
    pf=dict(sndk_positive_mark_pnl=gains,sndk_negative_mark_pnl=loss,mark_event_gross_profit_factor=gains/loss,
            gross_pnl=gains-loss,assumed_cost=sndk.costs.sum(),net_pnl=sndk.net_pnl.sum(),
            interpretation='Gross mark-event profit factor, not closed-trade PF or average win/loss ratio.')
    (OUT/'context_profit_factor.json').write_text(json.dumps(pf,indent=2))
    report = '''# 9月14日 Alpha 后续审计

## 口径与复核
方向预测对齐下一根开盘至相应未来开盘；信号桶时间与可用时间相差5分钟。
逐行重算标签并与原始时间轴核对，缺失值排除，零收益按sign=0处理。分时段按信号桶归类。
原始历史IEX文件SHA256与原实验登记一致。逐桶重算QI、点差、报价数和成交方向失衡，均与产物一致。
30秒仅是现有成交报价对齐容忍时间和报告统计参照，不是新增交易限制；报价年龄不证明断线。
历史接口没有当时接收延迟，IEX不是全市场NBBO；本审计不能判定真实最优执行价或识别机构身份。

## 修正的方向匹配率
'''+pd.DataFrame(accuracy).to_markdown(index=False)+'''

## 原始L1质量
'''+pd.DataFrame(quality).to_markdown(index=False)+'''

零QI表示桶末最后有效报价两边数量相等。缺失signed trade不等于缺失报价；逐笔原因在trade_classification文件。
inside_spread_unclassified表示成交落在IEX买卖价之间，当前算法无法赋予方向，不能当作零净订单流。
SNDK的21个缺失桶均只缺signed_trade_imbalance，其他11列完整；对应全部21次原研究L1回退。
修复研究方向是按特征保留可用信息、显式加入成交分类覆盖率，并在过去训练数据上验证缺失处理；
不能把无法识别的成交强行标买或卖，也不能用0冒充已观测的平衡订单流。

## 实际模拟成交持仓归因
'''+summary.round(6).to_markdown(index=False)+'''

每两次成交间按上一笔成交后实际股数×参考价格变化计算毛利，再扣该笔已记录模拟成本。
所有路径尾仓为零；与成交现金流独立核对误差小于$0.000001。fill_price已含滑点，不重复扣除。
成本为原实验固定bps模拟摩擦，实际券商收费未验证。

### 加入L1的增量（plus减base）
'''+delta.round(4).to_markdown()+'''

这是两条整体策略路径的收益差，包含配仓和执行规模变化，不是隔离预测能力的因果实验。

### SNDK Context逐估值事件PF
'''+json.dumps(pf,ensure_ascii=False,indent=2)+'''

## 可用结论与边界
L1模型仅以9月11日一天训练；9月14日被反复研究，不能作为未触碰的验证集。
本次没有训练新模型、优化参数或修改下单链。先前“86%时间无盘口”“全天利润全在早盘”均不成立。
下一项策略实验应固定相同资金、成本与数据，对多期限预测、仓位平滑逐项比较；不能宣称已提高未来利润。

## 文件索引
- direction_rows.csv / direction_summary.csv：每条预测、可用时间、标签结束、匹配结果与有效样本数。
- *_quote_quality.csv：逐桶缺失字段、报价年龄、零QI及成交分类数量。
- *_trade_classification.csv：逐笔成交与前序报价匹配结果。
- filled_position_intervals.csv：实际模拟股数产生的持仓收益区间。
- context_hourly_attribution.csv：Context逐股、小时、方向归因。
- pnl_summary.csv / l1_incremental_attribution.csv：总盈亏与L1增量分解。
- registry.json：原始输入哈希和限制。重现命令：python3 scripts/audit_alpha_followup.py
'''
    (OUT/'REPORT.md').write_text(report)
    record(Path(__file__))
    (OUT/'registry.json').write_text(json.dumps(dict(status='complete',evaluation_day=DAY,inputs=inputs,
        actual_broker_fees_verified=False,live_model_changed=False,performance_verified=False,
        checks=['recomputed forward labels','raw source hashes','raw feature equality','signed trade equality','position inventory','cashflow reconciliation']),indent=2))
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.name!='SHA256SUMS.json'}
    (OUT/'SHA256SUMS.json').write_text(json.dumps(hashes,indent=2))
    print(json.dumps({'output':str(OUT),'quality':quality,'context_pf':pf},indent=2))


if __name__=='__main__':
    run()
