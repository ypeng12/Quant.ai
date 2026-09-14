"""Read-only classic dashboards: retained market history and labelled rule views.

This display adapter neither trains a model nor imports the trading runner.
Legacy cache numbers retain their provenance; they are not live win rates.
"""
from pathlib import Path
import json
import re
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]


def symbol_name(ticker):
    symbol=str(ticker).strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}',symbol): raise ValueError('Invalid ticker')
    return symbol


def ml_snapshot(ticker,root=ROOT):
    symbol=symbol_name(ticker)
    path=Path(root)/'backend/data/ml_predictions_cache.json'
    data=json.loads(path.read_text()) if path.exists() else {}
    if symbol not in data:
        return dict(success=False,status='demo_available',ticker=symbol,result=None,
                    error='此股票没有归档模型快照，可查看通用交互演示。')
    return dict(success=True,status='archived_demo',ticker=symbol,result=data[symbol],
                data_provenance=dict(source='legacy_ml_predictions_cache',as_of=None,
                                     label='经典模型展示 · 归档数值（日期未记录）',
                                     score_kind='uncalibrated_legacy_output',is_live=False))


def build_wave_data(frame,ticker,date,source):
    """Same legacy factor formulas, explicitly named as OHLCV-derived scores."""
    from .lob_microstructure_ml import MicrostructureWaveAlphaEngine
    b=frame.copy();b.columns=[str(c).title() for c in b.columns]
    b=b[['Open','High','Low','Close','Volume']].astype(float)
    b=b.loc[b.index.strftime('%Y-%m-%d')==date]
    if b.empty: raise ValueError('No bars for requested date')
    engine=MicrostructureWaveAlphaEngine()
    features=engine.build_microstructure_features(b)
    probability=np.array(engine.predict_microstructure_alpha(b))
    # Preserve the old rule transformation as a display score, not calibration.
    scores=(probability-.5)*200
    times=b.index.strftime('%H:%M').tolist();signals=[];last=-100;direction=None
    ofi=features.feature_ofi.fillna(0).to_numpy()
    drift=(features.feature_micro_drift_bps if 'feature_micro_drift_bps' in features else features.feature_micro_drift*100).fillna(0).to_numpy()
    for i,score in enumerate(scores):
        side='LONG' if score>15 else 'SHORT' if score < -15 else None
        if side and (side!=direction or i-last>=5):
            row=b.iloc[i];is_long=side=='LONG'
            signals.append(dict(index=i,time=times[i],direction=side,coord_x=times[i],
                coord_y=round(float(row.Low*.9985 if is_long else row.High*1.0015),2),
                price=round(float(row.Close),2),high=float(row.High),low=float(row.Low),
                p_win=round(float(probability[i] if is_long else 1-probability[i])*100,1),
                expected_ret=round(abs(float(probability[i]-.5))*1.8,2),ofi=round(float(ofi[i]),3),
                micro_drift=round(float(drift[i]),2),alpha=round(float(score),1)))
            direction=side;last=i
    values=lambda v:[round(float(x),3) for x in v]
    volume=b.Volume.cumsum().replace(0,np.nan)
    weighted=(b.Close*b.Volume).cumsum()/volume
    return dict(times=times,kline=[[float(r.Open),float(r.Close),float(r.Low),float(r.High)] for r in b.itertuples()],
                volume=values(b.Volume),ema9=values(b.Close.ewm(span=9,adjust=False).mean()),
                ema21=values(b.Close.ewm(span=21,adjust=False).mean()),vwap=[float(v) if np.isfinite(v) else None for v in weighted],
                ofi=values(ofi),micro_drift=values(drift),queue_imb=values(features.feature_queue_imbalance.fillna(0)),
                sweep_vel=values(features.feature_sweep_vel.fillna(0)),wave_p_win_long=values(probability*100),
                composite_alpha=values(scores),signals=signals,
                stats=dict(open=float(b.Open.iloc[0]),close=float(b.Close.iloc[-1]),high=float(b.High.max()),low=float(b.Low.min()),
                           pnl_pct=round(float(b.Close.iloc[-1]/b.Open.iloc[0]-1)*100,2),signal_count=len(signals)),
                data_provenance=dict(bar_source=source,feature_source='ohlcv_derived',score_kind='legacy_rule_score',is_live=False))


def history(ticker,date='',root=ROOT):
    symbol=symbol_name(ticker);root=Path(root)
    if date and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date): raise ValueError('Explicit historical date required')
    cache=root/'backend/data/charts/wave_history_cache.json'
    records=json.loads(cache.read_text()).get(symbol,{}) if cache.exists() else {}
    by_day={d:v for d,v in records.get('by_day',{}).items() if re.fullmatch(r'\d{4}-\d{2}-\d{2}',d)}
    if by_day:
        day=date or sorted(by_day)[-1]
        if day not in by_day: raise ValueError('Requested historical session unavailable')
        return dict(success=True,status='historical_proxy',ticker=symbol,date=day,data=by_day[day],available_dates=sorted(by_day),
                    data_provenance=dict(bar_source='retained_wave_history',feature_source='ohlcv_derived',
                                         score_kind='archived_model_output',is_live=False))
    path=root/'reports/platform_universe30_bars_20260913'/f'{symbol}.parquet'
    if not path.exists(): raise ValueError('No retained bars for this ticker')
    b=pd.read_parquet(path);days=sorted(set(b.index.strftime('%Y-%m-%d')));day=date or days[-1]
    if day not in days: raise ValueError('Requested historical session unavailable')
    data=build_wave_data(b,symbol,day,'retained_5m_bars')
    return dict(success=True,status='historical_proxy',ticker=symbol,date=day,data=data,
                available_dates=days,data_provenance=data['data_provenance'])


def trajectory(ticker,date=None,root=ROOT):
    """Restore price/trajectory exploration using real retained bars and rules."""
    try:
        r=history(ticker,date or '',root);d=r['data'];k=np.array(d['kline']);closes=k[:,1]
        v=np.array(d['volume']);typical=(k[:,2]+k[:,3]+closes)/3
        vwap=np.divide(np.cumsum(typical*v),np.cumsum(v),out=closes.copy(),where=np.cumsum(v)>0)
        atr=pd.Series(k[:,3]-k[:,2]).rolling(14,min_periods=1).mean().to_numpy()
        alpha=np.array(d['composite_alpha'])/100
        predicted=closes+atr*alpha*1.4+(vwap-closes)*.22
        p=np.array(d['wave_p_win_long']);mature=len(closes)-3
        agreement=float(np.mean((p[:mature]>=50)==(closes[3:]>closes[:mature]))*100) if mature>0 else None
        last=pd.Timestamp(f"{r['date']} {d['times'][-1]}",tz='America/New_York')
        future_times=[];future_prices=[];future_high=[];future_low=[];point=float(closes[-1])
        for step in range(1,7):
            at=last+pd.Timedelta(minutes=5*step)
            if at.hour>=16: break
            point+=float(atr[-1]*alpha[-1]*.45*np.exp(-step/6.5))
            band=float(atr[-1]*(.55+step*.04))
            future_times.append(at.strftime('%H:%M'));future_prices.append(point);future_high.append(point+band);future_low.append(point-band)
        return dict(success=True,status='historical_rule_view',ticker=r['ticker'],date=r['date'],available_dates=sorted(r['available_dates'],reverse=True),
                    data_provenance=r['data_provenance'],times=d['times'],actual_prices=closes.tolist(),
                    opens=k[:,0].tolist(),highs=k[:,3].tolist(),lows=k[:,2].tolist(),volumes=v.tolist(),
                    predicted_prices=predicted.tolist(),predicted_highs=(np.maximum(closes,predicted)+atr*.85).tolist(),
                    predicted_lows=(np.minimum(closes,predicted)-atr*.85).tolist(),p_win_series=p.tolist(),trades=[],
                    future=dict(times=future_times,prices=future_prices,highs=future_high,lows=future_low),
                    summary=dict(current_price=float(closes[-1]),open_price=float(k[0,0]),high_price=float(k[:,3].max()),low_price=float(k[:,2].min()),
                                 day_change_pct=float((closes[-1]/k[0,0]-1)*100),ml_predicted_mfe_pct=float((np.max(predicted+atr*.85)/k[0,0]-1)*100),
                                 actual_max_gain_pct=float((k[:,3].max()/k[0,0]-1)*100),ml_p_win_pct=float(p[-1]),prediction_accuracy_pct=agreement))
    except (ValueError,OSError,KeyError) as exc:
        return dict(success=False,status='unavailable',ticker=str(ticker).strip().upper(),error=str(exc))
