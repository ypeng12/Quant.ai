#!/usr/bin/env python3
"""Explain archived forecasts against their actual horizon; never trade or refit to test outcomes."""
import argparse,gzip,json,sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app.research.artifacts import load_platform_results,digest
from app.research.strategy_extensions import FOUR,ResearchSpec,feature_panel,mature_fit,predict
from app.quant_policy import labeled_frame

def leaf_paths(fitted):
    tree=fitted['model'].tree_;paths={}
    def visit(node,rules):
        feature=int(tree.feature[node])
        if feature<0:
            paths[node]=dict(rules=rules,prediction_bps=float(tree.value[node].ravel()[0]*10000),training_rows=int(tree.n_node_samples[node]));return
        name=fitted['names'][feature]
        threshold=float(tree.threshold[node]*fitted['scale'][feature]+fitted['mean'][feature])
        visit(tree.children_left[node],rules+[dict(feature=name,operator='<=',threshold=threshold)])
        visit(tree.children_right[node],rules+[dict(feature=name,operator='>',threshold=threshold)])
    visit(0,[]);return paths

def run(bundle,output):
    bundle=Path(bundle);output=Path(output)
    result=load_platform_results(bundle)
    if result['status']!='complete':raise ValueError(result.get('reason'))
    research=result['research'];output.mkdir(parents=True,exist_ok=False)
    frames={s:pd.read_parquet(ROOT/research['data_paths'][s]) for s in FOUR}
    references={s:pd.read_parquet(ROOT/research['data_paths'][s]) for s in ('SPY','SOXX')}
    folder=bundle/'four_tree_control_cost5';daily=pd.read_csv(folder/'daily.csv');marks=pd.read_csv(folder/'marks.csv.gz')
    marks=marks.loc[marks.phase=='bar_close'].copy();marks['timestamp']=pd.to_datetime(marks.timestamp)
    with gzip.open(folder/'decisions.json.gz','rt') as f:decisions=json.load(f)
    features=feature_panel(frames,'context');labels={s:labeled_frame(frames[s],ResearchSpec('audit'))[1] for s in FOUR}
    dates=['2026-09-04','2026-09-08','2026-09-09','2026-09-10','2026-09-11']
    summary=[];observations=[];models=[];chart={}
    for day in dates:
        signal=[r for r in decisions if r['available_at'].startswith(day)]
        index=pd.DatetimeIndex([pd.Timestamp(r['available_at'])-pd.Timedelta(minutes=5) for r in signal])
        for s in FOUR:
            bars=frames[s].loc[day];mu=np.array([r['forecast'][s] for r in signal]);y=labels[s].reindex(index).to_numpy()
            if not np.isfinite(y).all():raise ValueError('Missing matching executable labels')
            pnl=daily.loc[daily.date==day].iloc[0]
            held=marks.loc[marks.date==day].set_index('timestamp')
            exposure=held.reindex(index+pd.Timedelta(minutes=10))[f'{s}_weight'].to_numpy()
            shares=held.reindex(index+pd.Timedelta(minutes=10))[f'{s}_shares'].to_numpy()
            # The decision at t+5 executes at t+5 open; t+10 close records the
            # shares held through that exact forecast horizon, not earlier ones.
            if not np.isfinite(shares).all():raise ValueError('Missing executed position attribution')
            actual_nonzero=y!=0
            summary.append(dict(day=day,symbol=s,open_to_close_return=float(bars.Close.iloc[-1]/bars.Open.iloc[0]-1),
                low=float(bars.Low.min()),low_bar=str(bars.Low.idxmin()),high=float(bars.High.max()),high_bar=str(bars.High.idxmax()),
                forecasts=len(mu),positive_forecasts=int((mu>0).sum()),negative_forecasts=int((mu<0).sum()),
                unique_forecasts=len(np.unique(mu)),forecast_min_bps=float(mu.min()*10000),forecast_max_bps=float(mu.max()*10000),
                mean_predicted_bps=float(mu.mean()*10000),mean_realized_h1_bps=float(y.mean()*10000),
                h1_sign_accuracy=float((np.sign(mu[actual_nonzero])==np.sign(y[actual_nonzero])).mean()),
                actual_up_fraction=float((y[actual_nonzero]>0).mean()),mean_abs_prediction_error_bps=float(abs(mu-y).mean()*10000),
                long_intervals=int((shares>0).sum()),short_intervals=int((shares<0).sum()),flat_intervals=int((shares==0).sum()),
                net_pnl=float(pnl[f'{s}_net_pnl']),costs=float(pnl[f'{s}_costs'])))
            for i,t in enumerate(index):
                observations.append(dict(symbol=s,available_at=(t+pd.Timedelta(minutes=5)).isoformat(),
                    label_mature_at=(t+pd.Timedelta(minutes=10)).isoformat(),forecast_bps=float(mu[i]*10000),
                    realized_next_bar_bps=float(y[i]*10000),target_weight=signal[i]['weights'][s],executed_shares=int(shares[i]),
                    executed_close_weight=float(exposure[i]),marginal_risk_bps=signal[i]['marginal_risk'][s]*10000,
                    forecast_minus_marginal_risk_bps=(mu[i]-signal[i]['marginal_risk'][s])*10000))
        # Independently reconstruct only the prior-session SNDK model; require
        # byte-level numeric agreement with the archived forecasts before explaining it.
        fitted=mature_fit(features['SNDK'],labels['SNDK'],day)
        x=features['SNDK'].reindex(index)
        actual=np.array([r['forecast']['SNDK'] for r in signal]);pred=predict(fitted,x)
        np.testing.assert_allclose(pred,actual,rtol=0,atol=1e-12)
        z=(np.where(np.isfinite(x.to_numpy()),x.to_numpy(),fitted['mean'])-fitted['mean'])/fitted['scale']
        leaves=fitted['model'].apply(z);paths=leaf_paths(fitted)
        models.append(dict(day=day,training_last_session=fitted['last_train'],training_rows=fitted['rows'],
            training_sessions=fitted['sessions'],feature_names=list(fitted['names']),
            used_split_features=sorted({fitted['names'][i] for i in fitted['model'].tree_.feature if i>=0}),
            visited_leaves={str(int(k)):dict(visits=int((leaves==k).sum()),**paths[int(k)]) for k in np.unique(leaves)}))
        chart[day]=dict(index=index,forecast=actual,signal=signal)
    pd.DataFrame(summary).to_csv(output/'daily_diagnostics.csv',index=False)
    pd.DataFrame(observations).to_csv(output/'aligned_forecasts.csv',index=False)
    (output/'sndk_leaf_explanations.json').write_text(json.dumps(models,indent=2,allow_nan=False)+'\n')
    refs=[]
    for day in dates:
        for s,frame in references.items():
            x=frame.loc[day];refs.append(dict(day=day,symbol=s,open_to_close_return=float(x.Close.iloc[-1]/x.Open.iloc[0]-1)))
    pd.DataFrame(refs).to_csv(output/'market_context.csv',index=False)
    lines=['# SNDK：盘感、方向标签与实际仓位核对','',
        '本报告审计已存档的四股树模型模拟，未核验实盘账户；模型预测不是交易胜率。2026-09-04 单独核对，随后为 09-08 至 09-11 四个交易日。',
        '', '| 日期 | 开盘至收盘 | 5分钟看涨预测 | 不同预测值数 | 对应5分钟方向准确率 | 多/空/空仓区间数 | 模拟净盈亏 |','|---|---:|---:|---:|---:|---|---:|']
    for r in summary:
        if r['symbol']=='SNDK':lines.append(f"| {r['day']} | {r['open_to_close_return']:.2%} | {r['positive_forecasts']}/{r['forecasts']} | {r['unique_forecasts']} | {r['h1_sign_accuracy']:.1%} | {r['long_intervals']}/{r['short_intervals']}/{r['flat_intervals']} | ${r['net_pnl']:,.2f} |")
    lines+=['','方向准确率仅按预测对应的下一根开盘至收盘计算，排除实际零收益区间；不能拿全天涨跌判断每个5分钟预测对错，也不能把准确率当作净收益。多空区间使用实际模拟整数持仓，区间76个；看涨预测不代表买入。',
        '', '## 定位到的区别','',
        '- 四股 context 模型输入已有日内累计涨跌、VWAP 距离、量能、过去收益与波动，不是没有这些指标。实际树仅使用少数分裂特征，输入一个指标不意味着模型有效利用了它。',
        '- 原四股输入只包含 SNDK、TSLA、MSTR、NVDA；peer_return 指其他三股平均，不等于 SPY 大盘或 SOXX 半导体板块。其他扩池候选虽然包含 SPY，不代表这组四股模型也包含。',
        '- 此模型的目标是下一段5分钟可执行收益，不是当天剩余走势，也不是一个已经训练过的“先空后多”转向模型。',
        '- 9月10日重建的树在76个决策时刻全部访问同一叶子，输出 +1.1898725 bps。分裂使用 peer_return_1、vwap_distance、realized_volatility_12；详细阈值已还原为原特征单位，见 sndk_leaf_explanations.json。这是需要研究的表征与泛化问题，不能仅凭常数输出断言程序执行错误。',
        '- 这些小正预测可能不足以覆盖模拟成本；组合还考虑其他持仓和相关性。应分别核对预测、目标和实际持仓，不能看到绿色预测就认定已经重仓做多。',
        '- 9月4日 SNDK 开盘至收盘上涨约9.73%，SPY 约−0.23%，SOXX 约+2.06%；个股、板块和大盘并非同一方向，不能只用“大盘好”概括。',
        '- 9月4日 SNDK 的76个可交易区间中，实际模拟多头为0、空头60、无仓位16，净亏约$446.81。绝大多数预测只有+1.2981 bps，11:00时预测减边际风险惩罚约4.9278 bps，仍小于每单位仓位变化5 bps的成本。这说明弱短期预测、成本与既有空头延续有关；不是看涨就必然开多。',
        '- 值得检验的修正是对齐预测周期与计划持仓周期，以及多期持仓/换向价值；不能直接把费用调小，也不能按已知上涨日强制只做多。详细边际风险和预测差值已加入 aligned_forecasts.csv，未把它作为新的交易门槛。',
        '', '## 如何把盘感变成可检验假设','',
        '| 人的观察 | 可用已有免费数据描述 | 验证目标 |','|---|---|---|',
        '| 大盘/行业支持 | SPY 与 SOXX 的同期累计收益、过去窗口收益及量能 | 对同样四股预测是否增加信息 |',
        '| 个股比板块强 | SNDK 相对 SOXX/SPY 的收益与过去估计 beta 后残差 | 是否预测后续30/60分钟收益 |',
        '| 卖不下去/开始转强 | 截至当时的回撤、反弹、VWAP 距离变化、收益和量能变化 | 是否存在可执行的转向预测能力 |',
        '| 方向没坏继续持有 | 对齐持仓目的的剩余收益预测与持仓风险 | 继续持有、减仓和换向的净收益比较 |',
        '', '这些是待检验的假设，不是“突破VWAP必涨”或“周五必须做多”的手工规则。首要对照是保持四股、资金、成本一致，只增加真实市场/行业输入，再单独检验30/60分钟或剩余时段目标，记录全部尝试。已有长周期实验表现不佳，不能因为故事合理就推广。',
        '9月4日或上一周的事后方向可以作为诊断案例，不能再充当未见测试集。研究应预先记录假设，再用后续日期和其他股票检验。[AQR 对经济依据与样本外证据的讨论](https://www.aqr.com/insights/perspectives/lies-damned-lies-and-data-mining)。',
        '', '本次增加诊断工具与可复现证据，没有修改 live_runner、没有新增交易禁令，也没有把复盘方向写成交易信号。新方向模型尚未实现或被证明盈利。']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    fig,axes=plt.subplots(len(dates),2,figsize=(13,13))
    for i,day in enumerate(dates):
        x=frames['SNDK'].loc[day];t=x.index+pd.Timedelta(minutes=5)
        axes[i,0].plot(t,100*(x.Close/x.Open.iloc[0]-1),label='SNDK')
        for s,f in references.items():
            b=f.loc[day];axes[i,0].plot(t,100*(b.Close/b.Open.iloc[0]-1),label=s,alpha=.7)
        axes[i,0].axhline(0,color='gray',linewidth=.6);axes[i,0].set_title(day+' | return since open (%)')
        c=chart[day];a=c['index']+pd.Timedelta(minutes=5)
        axes[i,1].step(a,c['forecast']*10000,label='Next-bar forecast (bps)',where='post',color='purple')
        other=axes[i,1].twinx();other.step(a,[100*r['weights']['SNDK'] for r in c['signal']],where='post',color='teal',alpha=.7)
        other.set_ylim(-100,100);other.set_ylabel('Target weight (%)',color='teal')
        axes[i,1].set_title(day+' | forecast vs target (not fills)');axes[i,1].set_ylabel('Forecast (bps)',color='purple')
        import matplotlib.dates as mdates
        from zoneinfo import ZoneInfo
        for ax in axes[i]:ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=ZoneInfo('America/New_York')));ax.grid(alpha=.15)
    axes[0,0].legend(fontsize=8);fig.tight_layout();fig.savefig(output/'sndk_diagnostics.png',dpi=150);plt.close(fig)
    registry=dict(source=digest(Path(__file__)),bundle_sha256=digest(bundle/'registry.json'),model_predictions_reproduced=True,
        dates=dates,actual_orders_submitted=0,artifacts={p.name:digest(p) for p in output.iterdir() if p.is_file()})
    (output/'audit.json').write_text(json.dumps(registry,indent=2)+'\n')
    print(pd.DataFrame(summary).query("symbol=='SNDK'")[['day','positive_forecasts','unique_forecasts','h1_sign_accuracy','long_intervals','short_intervals','net_pnl']].to_string(index=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',default='reports/active_research_20260913');p.add_argument('--output',required=True)
    args=p.parse_args();run(args.bundle,args.output)
