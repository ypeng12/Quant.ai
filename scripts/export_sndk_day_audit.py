#!/usr/bin/env python3
"""Export a human-auditable SNDK day: bars, factors, forecasts, L1 and fills."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.quant_policy import PolicyModel,normalize_bars,target_weights,feature_frame
from app.research.holding_policy import HoldingSpec,holding_features,executable_labels,DEFAULT_SYMBOLS,REFERENCES
from app.research.holding_l1 import HoldingL1Residual


def safe_name(text):return str(text).replace('/','_').replace(' ','_')


def description(name):
    exact={
      'open':'本根5分钟开盘价','high':'本根最高价','low':'本根最低价','close':'本根收盘价','volume':'本根成交量',
      'seasonal_rvol':'当前成交量/过去同一时刻平均成交量-1；分母不含今天',
      'trend_efficiency_12':'过去12根净价格变化/路径绝对变化','volume_x_return':'同时间量能×最近5分钟收益',
      'volume_x_efficiency':'同时间量能×趋势效率','overnight_gap':'今日开盘/前一交易日收盘-1',
      'session_fraction':'从09:30至当前的交易日进度','l1_spread_bps':'IEX买一卖一价差，相对中间价bps',
      'l1_quote_imbalance':'(买一数量-卖一数量)/(两边数量和)','l1_microprice_bps':'盘口数量加权微价相对中间价bps',
      'l1_ofi_normalized':'Cont OFI/该桶盘口深度','l1_signed_trade_imbalance':'对齐先前报价后的主动成交方向失衡',
      'l1_quote_updates':'该5分钟IEX报价更新数','l1_ofi_raw':'该5分钟原始OFI和',
      'l1_mean_half_depth':'该桶平均单边盘口深度','l1_ofi_depth':'原始OFI/平均单边深度',
      'l1_ofi_x_spread':'深度归一OFI×价差','l1_ofi_x_session_sin':'OFI×日内正弦位置',
      'l1_ofi_x_session_cos':'OFI×日内余弦位置'}
    if name in exact:return exact[name]
    if name.startswith('momentum_'):return name.split('_')[-1]+'根5分钟日内动量'
    if '_return_' in name:return '参考标的截至当前的日内收益'
    if '_relative_' in name:return 'SNDK收益减参考标的同期收益'
    if name.startswith('a158_'):return 'Alpha158风格的因果量价特征；精确定义见 paper_bar_alpha.py'
    if name.startswith('a101_'):return 'Alpha101子集的因果特征；精确定义见 paper_bar_alpha.py'
    if name.startswith('xs_'):return '同一已完成时点的四股截面/同行相对特征'
    if name in {'return_1','return_3','return_12'}:return name[-1]+'根收益（仅同一交易日连续K线）'
    if name=='session_return':return '从今日开盘至当前收盘的收益'
    if name=='bar_relative_volume':return '本根成交量/今日此前每根平均成交量-1'
    return '因果量价特征；精确定义见源代码与数据字典 source_file'


def model_rows(root,model_name):
    decisions=json.loads((root/model_name/'decisions.json').read_text())
    rows={}
    for d in decisions:
        stamp=pd.Timestamp(d['time'])
        rows[stamp]={
          f'{model_name}_raw_5m_bps':d['raw_cumulative_forecast_bps']['SNDK']['5'],
          f'{model_name}_raw_15m_bps':d['raw_cumulative_forecast_bps']['SNDK']['15'],
          f'{model_name}_raw_30m_bps':d['raw_cumulative_forecast_bps']['SNDK']['30'],
          f'{model_name}_raw_60m_bps':d['raw_cumulative_forecast_bps']['SNDK']['60'],
          f'{model_name}_cal_5m_bps':d['cumulative_forecast_bps']['SNDK']['5'],
          f'{model_name}_cal_15m_bps':d['cumulative_forecast_bps']['SNDK']['15'],
          f'{model_name}_cal_30m_bps':d['cumulative_forecast_bps']['SNDK']['30'],
          f'{model_name}_cal_60m_bps':d['cumulative_forecast_bps']['SNDK']['60'],
          f'{model_name}_target_weight':d['targets']['SNDK'],
          f'{model_name}_action':d['actions']['SNDK'],
        }
    return pd.DataFrame.from_dict(rows,orient='index').sort_index()


def contribution_rows(model_path,features):
    artifact=json.loads(Path(model_path).read_text());result=[]
    for horizon in (1,3,6,12):
        m=artifact['models']['SNDK'][str(horizon)];names=m['features'];coef=np.asarray(m['state']['coefficient'])
        means=pd.Series(m['mean'],index=names);scales=pd.Series(m['scale'],index=names)
        for stamp,row in features.iterrows():
            values=row.reindex(names).fillna(means)
            z=((values-means)/scales).to_numpy(dtype=float)
            pieces=coef*z*10000;order=np.argsort(np.abs(pieces))[::-1][:8]
            result.append(dict(time=stamp.isoformat(),raw_horizon_minutes=horizon*5,
                raw_forecast_bps=float(pieces.sum()+m['state']['intercept']*10000),
                top_contributions=[dict(feature=names[i],contribution_bps=float(pieces[i]),value=float(values[names[i]])) for i in order]))
    return result


def run(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    lab=Path(args.lab);bar_root=lab/'bars';symbols=(*DEFAULT_SYMBOLS,*REFERENCES)
    frames={s:normalize_bars(pd.read_parquet(bar_root/f'{s}.parquet')) for s in symbols}
    day=args.day;bars=frames['SNDK'].loc[frames['SNDK'].index.strftime('%Y-%m-%d')==day]
    paper=holding_features(frames,DEFAULT_SYMBOLS,HoldingSpec(family='paper'))['SNDK'].reindex(bars.index)
    context=holding_features(frames,DEFAULT_SYMBOLS,HoldingSpec())['SNDK'].reindex(bars.index)
    timeline=bars.copy()
    timeline.columns=['bar_'+c for c in timeline.columns]
    timeline['bar_return_bps']=bars.close.pct_change(fill_method=None)*10000
    timeline['session_return_bps']=(bars.close/bars.open.iloc[0]-1)*10000
    for horizon in (1,3,6,12):
        y,_=executable_labels(frames['SNDK'],horizon)
        timeline[f'realized_next_{horizon*5}m_bps']=y.reindex(bars.index)*10000
    timeline=timeline.join(paper.add_prefix('alpha31__')).join(context[[c for c in context if c not in paper]].add_prefix('context__'))
    for name in ('calibrated_legacy_curve','calibrated_context_curve','calibrated_legacy_curve_policy_cost5'):
        timeline=timeline.join(model_rows(lab,name))

    # Exact currently deployed frozen model, which is distinct from today's research candidates.
    frozen=Path(args.frozen);deployed=PolicyModel.load(args.deployed_model)
    deployed_bars={s:normalize_bars(pd.read_parquet(frozen/f'{s}.parquet')) for s in deployed.symbols}
    allowed=('NVDA','SNDK','TSLA');indices=[deployed.symbols.index(s) for s in allowed];current=dict.fromkeys(deployed.symbols,0.)
    drows={}
    for i,stamp in enumerate(bars.index[:76]):
        forecast=deployed.forecast({s:deployed_bars[s].iloc[:i+1] for s in deployed.symbols})
        weights=dict.fromkeys(deployed.symbols,0.)
        weights.update(target_weights({s:forecast.mu[s] for s in allowed},forecast.covariance.take(indices,0).take(indices,1),
            {s:current[s] for s in allowed},deployed.spec,shortable=dict.fromkeys(allowed,True),symbols=allowed))
        drows[stamp]=dict(deployed_expected_5m_bps=forecast.mu['SNDK']*10000,deployed_target_weight=weights['SNDK'])
        current=weights
    timeline=timeline.join(pd.DataFrame.from_dict(drows,orient='index'))

    l1_root=Path(args.l1);l1=pd.read_parquet(l1_root/f'SNDK_{day}_features.parquet').reindex(bars.index)
    timeline=timeline.join(l1.add_prefix('l1__'))
    residual=HoldingL1Residual.load(l1_root/'SNDK.json');adjustments={}
    for stamp in bars.index:
        try:adjustments[stamp]=residual.adjustment(l1,stamp+pd.Timedelta(minutes=5))*10000
        except ValueError:adjustments[stamp]=np.nan
    timeline['l1_learned_residual_5m_bps']=pd.Series(adjustments)
    # Joining fixed-offset decision timestamps can normalize the shared index to
    # UTC. The audit is explicitly an America/New_York trading-session view.
    timeline.index=timeline.index.tz_convert('America/New_York')
    timeline.index.name='signal_bar_open_et'
    timeline.insert(0,'information_available_et',(timeline.index+pd.Timedelta(minutes=5)).astype(str))
    timeline.insert(1,'earliest_simulated_fill_et',(timeline.index+pd.Timedelta(minutes=5)).astype(str))
    timeline.to_csv(out/'SNDK_20260914_COMPLETE_TIMELINE.csv')

    # One file per simulated strategy; signs are signed position changes.
    fills=[]
    sources=[('deployed_frozen',frozen/'equity47006.42_cost5_fills.csv'),
             ('calibrated_legacy_curve',lab/'calibrated_legacy_curve/fills.csv'),
             ('calibrated_context_curve',lab/'calibrated_context_curve/fills.csv'),
             ('calibrated_legacy_curve_policy_cost5',lab/'calibrated_legacy_curve_policy_cost5/fills.csv'),
             ('l1_base',l1_root/'base_fills.csv'),('l1_plus',l1_root/'plus_l1_fills.csv')]
    for strategy,path in sources:
        f=pd.read_csv(path);f=f.loc[f.symbol.eq('SNDK')].copy();f.insert(0,'strategy',strategy);fills.append(f)
    pd.concat(fills,ignore_index=True).to_csv(out/'SNDK_20260914_SIMULATED_FILLS.csv',index=False)

    actual=json.loads(Path(args.actual).read_text())['today'];actual=[{k:r.get(k) for k in ('time','ticker','action','shares','price','pnl','pnl_complete','accounting_basis')} for r in actual]
    pd.DataFrame(actual).to_csv(out/'SNDK_TSLA_20260914_ACTUAL_BROKER_FILLS.csv',index=False)

    contributions=contribution_rows(lab/'models/calibrated_context_curve.json',context)
    with (out/'SNDK_CONTEXT_MODEL_TOP_CONTRIBUTIONS.jsonl').open('w') as handle:
        for row in contributions:handle.write(json.dumps(row,allow_nan=False)+'\n')

    candidate=pd.concat([paper,context[[c for c in context if c not in paper]],l1],axis=1)
    assoc=[]
    for feature in candidate:
        for horizon in (1,3,6,12):
            target=timeline[f'realized_next_{horizon*5}m_bps'];pair=pd.concat([candidate[feature],target],axis=1).dropna()
            assoc.append(dict(feature=feature,horizon_minutes=horizon*5,rows=len(pair),pearson=pair.iloc[:,0].corr(pair.iloc[:,1]),
                spearman=pair.iloc[:,0].corr(pair.iloc[:,1],method='spearman'),
                min_time=pair.iloc[:,0].idxmin().isoformat() if len(pair) else None,max_time=pair.iloc[:,0].idxmax().isoformat() if len(pair) else None))
    pd.DataFrame(assoc).to_csv(out/'SNDK_20260914_FACTOR_FORWARD_ASSOCIATIONS.csv',index=False)
    pd.DataFrame([dict(feature=c,description=description(c),source_file='paper_bar_alpha.py / holding_policy.py' if c not in l1 else 'paper_l1_alpha.py',
        data_clock=l1.attrs.get('clock') if c in l1 else 'completed_5m_bar') for c in candidate]).to_csv(out/'SNDK_FACTOR_DICTIONARY.csv',index=False)

    decisions=model_rows(lab,'calibrated_context_curve');sign=np.sign(decisions.calibrated_context_curve_target_weight)
    turns=decisions.loc[sign.ne(sign.shift())|decisions.calibrated_context_curve_target_weight.diff().abs().gt(.1)]
    selected=timeline.loc[timeline.index.intersection(turns.index)]
    lines=['# SNDK 2026-09-14 全流程审计','',
      '时间列是美东时间。每行信号使用该行 5 分钟 K 线及此前数据，信息到下一行所示 available 时间才完整；最早模拟成交为下一根开盘。',
      '当前线上冻结模型、今日研究模型和 L1 诊断是三套不同结果。真实账户成交也单列，不能混成同一个策略。','',
      '## 先看关键结论','',
      f'- SNDK 当日从开盘 {bars.open.iloc[0]:.2f} 到 15:55 收盘 {bars.close.iloc[-1]:.2f}，变化 {(bars.close.iloc[-1]/bars.open.iloc[0]-1)*100:.2f}%。',
      '- 当前线上冻结模型在 09:35 附近预测约 -11.12 bps，先做空；它当天 SNDK 模拟毛利约 $79.66，但 5 bps 假设摩擦约 $94.46，净亏 $14.80。',
      '- 真实账户 09:30—09:33 买入 35 股，20:00 卖出，SNDK 成交价差盈利 $1,317.10。这不是当前冻结模型的订单路径。',
      '- 真实 IEX L1 当日仅作历史诊断；SNDK 加 L1 后单因子预测 MSE 反而变差，不能据单日组合结果宣称 SNDK L1 已有效。','',
      '## 校准扩展模型的显著仓位变化','',
      '|信号K线|可用时间|收盘|5m预测bps|15m预测bps|30m预测bps|60m预测bps|目标权重|动作|','|---|---|---:|---:|---:|---:|---:|---:|---|']
    for stamp,row in selected.iterrows():
        lines.append(f"|{stamp.strftime('%H:%M')}|{(stamp+pd.Timedelta(minutes=5)).strftime('%H:%M')}|{row.bar_close:.2f}|{row.calibrated_context_curve_cal_5m_bps:.2f}|{row.calibrated_context_curve_cal_15m_bps:.2f}|{row.calibrated_context_curve_cal_30m_bps:.2f}|{row.calibrated_context_curve_cal_60m_bps:.2f}|{row.calibrated_context_curve_target_weight:.3f}|{row.calibrated_context_curve_action}|")
    lines += ['','## 你应如何找关联','',
      '1. 先用 COMPLETE_TIMELINE 看模型预测和目标权重，再对照后面的 realized_next_*；真实结果只用于事后诊断。',
      '2. 用 TOP_CONTRIBUTIONS 看每个时刻哪些输入把原始 Ridge 预测推高或压低。贡献相加加上截距等于原始预测，不是校准后预测。',
      '3. 用 FACTOR_FORWARD_ASSOCIATIONS 排查同日相关，但只有一天、特征很多，极易出现偶然相关，不能据此直接加规则。',
      '4. OFI、QI、Microprice 都是 IEX L1 买一卖一信息，看不到机构身份和完整市场挂单。',
      '5. SIMULATED_FILLS 对照不同模型；ACTUAL_BROKER_FILLS 是账户真实成交。','',
      '## 文件','',
      '- `SNDK_20260914_COMPLETE_TIMELINE.csv`：78 根 K 线的全部可见字段。',
      '- `SNDK_FACTOR_DICTIONARY.csv`：每个因子的含义和数据时钟。',
      '- `SNDK_CONTEXT_MODEL_TOP_CONTRIBUTIONS.jsonl`：每时点、每期限最大的模型输入贡献。',
      '- `SNDK_20260914_FACTOR_FORWARD_ASSOCIATIONS.csv`：事后相关诊断。',
      '- `SNDK_20260914_SIMULATED_FILLS.csv`：六套策略的模拟成交。',
      '- `SNDK_TSLA_20260914_ACTUAL_BROKER_FILLS.csv`：已核对的真实账户成交，不含订单 ID。','',
      '原始 L1 来源为 Alpaca 历史 IEX，quote_size_unit=round_lots，clock=historical_exchange_latency_unverified。5 bps 是模拟执行摩擦，不是已核实券商手续费。','']
    (out/'REPORT.md').write_text('\n'.join(lines))
    hashes={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    (out/'SHA256SUMS.json').write_text(json.dumps(hashes,indent=2)+'\n')
    print(json.dumps(dict(rows=len(timeline),columns=len(timeline.columns),files=len(hashes)+1,output=str(out))))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lab',default='reports/holding_today_lab_20260914');p.add_argument('--l1',default='reports/holding_l1_evidence_20260914')
    p.add_argument('--frozen',default='/Users/yuliangpeng/.local/share/quant-l1/reports/frozen_policy_day_20260914')
    p.add_argument('--deployed-model',default='reports/quant_research_20260913/selected_policy.json')
    p.add_argument('--actual',default='/Users/yuliangpeng/.local/share/quant-l1/reports/today_actual_20260914/deployment_verified.json')
    p.add_argument('--day',default='2026-09-14');p.add_argument('--output',required=True);run(p.parse_args())
