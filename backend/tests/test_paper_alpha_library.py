"""Synthetic fixtures exercise causality/contracts, never trading performance."""
import json
import numpy as np
import pandas as pd
import pytest
from app.alpha.paper_bar_alpha import BarAlphaSpec,bar_alpha_panel
from app.alpha.paper_l1_alpha import quote_states,next_move_labels,forward_mid_labels,enhanced_l1_features,observed_events
from app.alpha.l1_state_models import QueueImbalanceModel,TransitionMicroprice
from app.research.paper_models import PaperForecast,fit_bar_model,fit_l1_ridge,l1_event_features,combine_bar_l1
from app.research.paper_catalog import paper_library_payload,digest


def bars():
    rng=np.random.default_rng(72);idx=pd.DatetimeIndex([])
    idx=pd.date_range('2026-09-01 09:30',periods=60,freq='5min',tz='America/New_York').append([
        pd.date_range(f'2026-09-0{day} 09:30',periods=60,freq='5min',tz='America/New_York') for day in (2,3)])
    out={}
    for i,s in enumerate(('AAA','BBB','CCC','SPY')):
        o=100+i*20+np.cumsum(rng.normal(0,.1,len(idx)));c=o+rng.normal(0,.1,len(idx))
        out[s]=pd.DataFrame(dict(open=o,close=c,high=np.maximum(o,c)+.2,low=np.minimum(o,c)-.2,
                                  volume=rng.integers(1000,10000,len(idx))),index=idx)
    return out


def quotes(n=800):
    idx=pd.date_range('2026-09-01 09:30',periods=n,freq='s',tz='America/New_York')
    mid=np.resize([100.,100.,100.01,100.01,100.,100.,100.01,100.01],n)
    size=np.resize([8,8,2,2,6,6,4,4],n)
    return pd.DataFrame(dict(event_type='quote',source='alpaca_stock_historical',symbol='AAA',feed='iex',market_depth='L1',
                             bid_price=mid-.005,ask_price=mid+.005,bid_size=size,ask_size=10-size),index=idx)


def test_bar_library_hand_calculation_and_counts():
    raw=bars();f=bar_alpha_panel(raw)['AAA'];b=raw['AAA'];t=b.index[25]
    assert len(f.columns)==31
    assert f.loc[t,'a158_ma_5']==pytest.approx(b.close.iloc[21:26].mean()/b.close.iloc[25])
    assert f.loc[t,'a158_roc_5']==pytest.approx(b.close.iloc[20]/b.close.iloc[25])
    assert f.loc[t,'a101_101']==pytest.approx((b.close.iloc[25]-b.open.iloc[25])/(b.high.iloc[25]-b.low.iloc[25]+.001))
    assert f.loc[t,'a101_012']==pytest.approx(np.sign(b.volume.diff().iloc[25])*-b.close.diff().iloc[25])
    own=b.close.pct_change().iloc[25]
    other=np.mean([raw[s].close.pct_change().iloc[25] for s in ('BBB','CCC')])
    assert f.loc[t,'xs_peer_residual']==pytest.approx(own-other)


def test_prefix_invariance_future_mutation_and_closed_bar_boundary():
    raw=bars();cut=pd.Timestamp('2026-09-02 11:00',tz='America/New_York')
    baseline=bar_alpha_panel(raw,as_of=cut)
    changed={s:b.copy() for s,b in raw.items()}
    for b in changed.values(): b.loc[b.index>=cut,['open','close','high','low']]*=100
    future=bar_alpha_panel(changed,as_of=cut)
    prefix=bar_alpha_panel({s:b.loc[b.index<cut] for s,b in raw.items()},as_of=cut)
    for s in raw:
        pd.testing.assert_frame_equal(baseline[s],future[s]);pd.testing.assert_frame_equal(baseline[s],prefix[s])
        assert baseline[s].index.max()+pd.Timedelta('5min')<=cut


def test_missing_slots_and_day_reset_do_not_compress_lookbacks():
    raw=bars();missing=raw['AAA'].index[10];raw['AAA']=raw['AAA'].drop(missing)
    f=bar_alpha_panel(raw)['AAA']
    assert np.isnan(f.loc[raw['BBB'].index[12],'a158_ma_5'])
    assert np.isnan(f.loc[raw['BBB'].index[12],'a158_roc_5'])
    assert np.isnan(f.loc[pd.Timestamp('2026-09-02 09:30',tz='America/New_York'),'a158_ma_5'])


def test_alpha101_cross_section_rank_axis():
    raw=bars();f=bar_alpha_panel(raw,BarAlphaSpec(family='alpha101_subset'))
    rank=pd.DataFrame({s:b.low for s,b in raw.items() if s!='SPY'}).rank(axis=1,pct=True)
    expected=-rank['AAA'].iloc[:9].rank(pct=True).iloc[-1]
    assert f['AAA'].a101_004.iloc[8]==pytest.approx(expected)
    assert f['SPY'].isna().all().all()


@pytest.mark.parametrize('estimator',['ridge','tree','lightgbm'])
def test_training_serialization_and_inference_use_same_engine(tmp_path,estimator):
    raw=bars();before='2026-09-03T09:30:00-04:00'
    model=fit_bar_model(raw,'AAA',before=before,estimator=estimator)
    assert pd.Timestamp(model.artifact['last_label_end'])<pd.Timestamp(before)
    path=tmp_path/'model.json';model.save(path);loaded=PaperForecast.load(path)
    pd.testing.assert_series_equal(model.forecast(raw,as_of='2026-09-03T14:30:00-04:00'),
                                   loaded.forecast(raw,as_of='2026-09-03T14:30:00-04:00'))
    with pytest.raises(ValueError,match='complete declared panel'):
        loaded.forecast({'AAA':raw['AAA']},as_of=before)
    altered={s:b.copy() for s,b in raw.items()}
    for b in altered.values(): b.loc[b.index>=pd.Timestamp(before),['open','close','high','low']]*=100
    again=fit_bar_model(altered,'AAA',before=before,estimator=estimator)
    assert again.artifact['state']==model.artifact['state']


def test_next_mid_move_target_and_maturity():
    q=quote_states(quotes(8));labels=next_move_labels(q)
    assert labels.target.tolist()[:6]==[1,1,0,0,1,1]
    assert labels.label_end.iloc[0]==q.index[2]
    assert labels.target.iloc[-2:].isna().all()
    future=forward_mid_labels(q,'2s','0s')
    assert future.target.iloc[0]==pytest.approx(.01/100)
    assert future.label_end.iloc[0]==q.index[2]


def test_l1_gaps_do_not_supply_future_labels():
    raw=quotes(8);raw.index=raw.index[:4].append(raw.index[4:]+pd.Timedelta('2h'))
    labels=next_move_labels(quote_states(raw))
    assert labels.target.iloc[2:4].isna().all()


def test_arrival_clock_excludes_unseen_and_late_events():
    raw=quotes(8);raw['source']='alpaca_stock_websocket'
    raw['received_at']=(raw.index+pd.Timedelta('2s')).astype(str)
    cutoff=raw.index[4]
    visible=observed_events(raw,as_of=cutoff)
    assert len(visible)==2
    assert visible.index.max()<cutoff
    raw.iloc[0,raw.columns.get_loc('received_at')]=(raw.index[6]+pd.Timedelta('2s')).isoformat()
    visible=observed_events(raw)
    assert visible.attrs['late_events_excluded']==1
    assert visible.attrs['clock']=='recorded_arrival'


def test_enhanced_ofi_formula_and_no_fake_trade_imbalance():
    raw=quotes(8);q=quote_states(raw);features=enhanced_l1_features(raw,'10s')
    assert len(features.columns)==12
    assert features.l1_ofi_raw.iloc[0]==pytest.approx(q.ofi.sum())
    assert features.l1_ofi_depth.iloc[0]==pytest.approx(q.ofi.sum()/5)
    assert np.isnan(features.l1_signed_trade_imbalance.iloc[0])


def test_qi_and_microprice_artifacts(tmp_path):
    raw=quotes();before=raw.index[400]
    qi=QueueImbalanceModel().fit(raw,before=before)
    assert qi.predict(raw).iloc[:400].isna().all()
    assert qi.predict(raw).iloc[400:].between(0,1).all()
    path=tmp_path/'qi.json';qi.save(path)
    pd.testing.assert_series_equal(qi.predict(raw),QueueImbalanceModel.load(path).predict(raw))
    model=TransitionMicroprice().fit(raw,before=before)
    a=model.artifact;Q=np.array(a['Q']);R=np.array(a['R']);g=np.array(a['immediate_reward'])
    np.testing.assert_allclose((np.eye(len(Q))-Q)@np.array(a['first_move_correction']),g,atol=1e-12)
    np.testing.assert_allclose((np.eye(len(Q))-Q)@np.array(a['B']),R,atol=1e-12)
    np.testing.assert_allclose((Q+R).sum(axis=1),1)
    correction=np.array(a['first_move_correction']);term=correction.copy()
    for _ in range(a['price_changes']-1): term=np.array(a['B'])@term;correction+=term
    np.testing.assert_allclose(a['correction'],correction)
    path=tmp_path/'micro.json';model.save(path)
    pd.testing.assert_frame_equal(model.predict(raw),TransitionMicroprice.load(path).predict(raw))
    unsupported=raw.copy();unsupported['ask_price']+=.10
    assert model.predict(unsupported).transition_microprice.isna().all()
    wrong=raw.copy();wrong['feed']='sip'
    with pytest.raises(ValueError,match='contract'): qi.predict(wrong)


def test_microprice_unidentified_constant_book():
    raw=quotes(80);raw[['bid_price','ask_price']]=[99.995,100.005]
    with pytest.raises(ValueError,match='Non-absorbing'):
        TransitionMicroprice().fit(raw,before=raw.index[-1])


def test_l1_ridge_mature_horizon_and_future_forecast():
    raw=quotes();before=raw.index[400]
    model=fit_l1_ridge(raw,before=before,horizon='30s')
    assert pd.Timestamp(model.artifact['last_label_end'])<before
    pred=model.predict(l1_event_features(quote_states(raw)))
    assert pred.iloc[:400].isna().all();assert pred.iloc[400:].notna().all()


def test_lab_rejects_tampered_artifact(tmp_path):
    assert paper_library_payload(tmp_path)['report_status']=='unavailable'
    data=tmp_path/'features.txt';data.write_text('retained input')
    r=tmp_path/'registry.json';r.write_text(json.dumps(dict(status='complete',artifact_hashes={'features.txt':digest(data)})))
    (tmp_path/'registry.sha256').write_text(digest(r))
    assert paper_library_payload(tmp_path)['report_status']=='complete'
    data.write_text('changed')
    assert paper_library_payload(tmp_path)['report_status']=='invalid'


def test_combined_model_requires_real_l1_at_inference(tmp_path):
    raw=bars();events=quotes(3600)
    trades=events.iloc[::10].copy();trades.index+=pd.Timedelta('500ms')
    trades['event_type']='trade';trades['price']=trades.ask_price;trades['size']=100
    events=pd.concat([events,trades]).sort_index(kind='stable')
    panel=bar_alpha_panel(raw);features=combine_bar_l1(panel['AAA'],events)
    before=pd.Timestamp('2026-09-01 10:00',tz='America/New_York')
    target=pd.Series(.001,index=features.index)
    end=pd.Series(features.index+pd.Timedelta('10min'),index=features.index)
    model=PaperForecast().fit(features,target,label_end=end,before=before)
    model.artifact.update(symbol='AAA',input_kind='bar_plus_real_l1')
    path=tmp_path/'combined.json';model.save(path);model=PaperForecast.load(path)
    actual=model.forecast(raw,as_of='2026-09-01T10:20:00-04:00',events=events)
    assert actual.iloc[-1]==pytest.approx(.001)
    with pytest.raises(ValueError,match='Real L1 required'):
        model.forecast(raw,as_of='2026-09-01T10:20:00-04:00')
    wrong=events.copy();wrong['symbol']='BBB'
    with pytest.raises(ValueError,match='contract changed'):
        model.forecast(raw,as_of='2026-09-01T10:20:00-04:00',events=wrong)
    absent=features.copy();absent['l1_ofi_raw']=np.nan
    assert model.predict(absent).isna().all()
