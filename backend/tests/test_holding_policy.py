import json
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from app.research.holding_policy import HoldingSpec,HoldingModel,holding_features,executable_labels,curve_from_cumulative,DEFAULT_SYMBOLS,REFERENCES
from app.research.execution_cost_audit import audit_fills_against_quotes,cost_scenarios


@pytest.fixture
def frames():
    rng=np.random.default_rng(32)
    days=pd.bdate_range('2026-08-03',periods=6)
    index=pd.DatetimeIndex([t for d in days for t in pd.date_range(str(d.date())+' 09:30',periods=78,freq='5min',tz='America/New_York')])
    result={}
    for s in (*DEFAULT_SYMBOLS,*REFERENCES):
        p=100*np.exp(np.cumsum(rng.normal(0,.001,len(index))))
        result[s]=pd.DataFrame(dict(open=p,high=p+.3,low=p-.3,close=p+.05,volume=1e6),index=index)
    return result


def test_future_rows_cannot_change_factors_or_seasonal_volume(frames):
    before=pd.Timestamp('2026-08-10 11:00',tz='America/New_York')
    original=holding_features(frames)
    modified={s:f.copy() for s,f in frames.items()}
    for f in modified.values(): f.loc[f.index>=before,['open','high','low','close','volume']]*=2
    changed=holding_features(modified)
    for s in DEFAULT_SYMBOLS:
        pd.testing.assert_frame_equal(original[s].loc[original[s].index<before],changed[s].loc[changed[s].index<before])
    # Current volume does not leak into its own seasonal denominator.
    assert original['SNDK'].loc[before,'seasonal_rvol']==0


def test_labels_execute_at_next_open_and_never_cross_day(frames):
    b=frames['SNDK'];y,end=executable_labels(b,3)
    assert y.iloc[0]==pytest.approx(b.open.iloc[4]/b.open.iloc[1]-1)
    assert end.iloc[0]==b.index[4]
    assert y.loc[b.index.strftime('%H:%M')>='15:40'].isna().all()


def test_curve_preserves_cumulative_forecasts():
    c=np.array([[.001],[.003],[.006],[.012]])
    curve=curve_from_cumulative(c,(1,3,6,12),12)
    product=np.cumprod(1+curve[:,0])-1
    assert np.allclose(product[[0,2,5,11]],c[:,0])


def test_frozen_model_roundtrip_and_unseen_day(frames,tmp_path):
    spec=HoldingSpec(horizons=(1,3),seasonal_sessions=2)
    model=HoldingModel.fit(frames,pd.Timestamp('2026-08-10',tz='America/New_York'),spec)
    path=tmp_path/'model.json';model.save(path);restored=HoldingModel.load(path)
    assert set(restored.models)==set(DEFAULT_SYMBOLS) and 'MSTR' not in restored.models
    now=pd.Timestamp('2026-08-10 10:35',tz='America/New_York')
    prefix={s:f.loc[f.index+pd.Timedelta(minutes=5)<=now] for s,f in frames.items()}
    kwargs=dict(allowed=DEFAULT_SYMBOLS,shortable=dict.fromkeys(DEFAULT_SYMBOLS,True),as_of=now)
    a,_=model.live_target(prefix,dict.fromkeys(DEFAULT_SYMBOLS,0.),**kwargs)
    b,explanation=restored.live_target(prefix,dict.fromkeys(DEFAULT_SYMBOLS,0.),**kwargs)
    assert a==pytest.approx(b,abs=1e-7)
    assert explanation['active_features']>31
    assert not explanation['l1_contributes']
    assert sum(abs(v) for v in b.values())<=spec.gross_limit+1e-8


def test_holding_plan_respects_borrow_and_preserves_strong_trend(frames):
    model=HoldingModel.fit(frames,pd.Timestamp('2026-08-10',tz='America/New_York'),HoldingSpec(horizons=(1,3),seasonal_sessions=2))
    forecasts={s:{1:.01,3:.03} for s in DEFAULT_SYMBOLS}
    current=dict.fromkeys(DEFAULT_SYMBOLS,.1)
    w,_=model.allocation(forecasts,current,pd.Timestamp('2026-08-10 10:00',tz='America/New_York'),shortable=dict.fromkeys(DEFAULT_SYMBOLS,False))
    assert min(w.values())>=0 and sum(w.values())>0
    negative={s:{1:-.01,3:-.03} for s in DEFAULT_SYMBOLS}
    w,_=model.allocation(negative,current,pd.Timestamp('2026-08-10 10:00',tz='America/New_York'),shortable=dict.fromkeys(DEFAULT_SYMBOLS,False))
    assert min(w.values())>=0 and max(w.values())<1e-7


def test_fee_unknown_and_quote_causality():
    fills=[dict(fill_id='1',symbol='SNDK',side='buy',qty=2,price=100.02,timestamp='2026-09-14T10:00:00Z')]
    quotes=[dict(symbol='SNDK',bid=100,ask=100.02,timestamp='2026-09-14T09:59:59.9Z',feed='sip'),
            dict(symbol='SNDK',bid=200,ask=201,timestamp='2026-09-14T10:00:01Z',feed='sip')]
    r=audit_fills_against_quotes(fills,quotes)
    assert r['matched']==1 and r['actual_explicit_fees'] is None
    assert r['weighted_effective_half_spread_bps']==pytest.approx(.01/100.01*10000)
    assert cost_scenarios(100,10000)[2]['assumed_execution_friction']==5
    assert cost_scenarios(100,10000)[2]['actual_broker_fees'] is None


def test_exchange_early_close_shortens_the_plan(frames):
    model=HoldingModel.fit(frames,pd.Timestamp('2026-08-10',tz='America/New_York'),HoldingSpec(horizons=(1,3),seasonal_sessions=2))
    forecasts={s:{1:.01,3:.03} for s in DEFAULT_SYMBOLS}
    stamp=pd.Timestamp('2026-08-10T12:50:00-04:00')
    weights,info=model.allocation(forecasts,dict.fromkeys(DEFAULT_SYMBOLS,.1),stamp,
        liquidation_at=pd.Timestamp('2026-08-10T12:55:00-04:00'))
    assert not any(weights.values()) and info['reason']=='scheduled_session_close'
