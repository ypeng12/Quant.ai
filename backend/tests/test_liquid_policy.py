from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import pytest
from app.research.liquid_policy import LiquidityRules,daily_eligibility,instrument_admission,allocate,LiquidRuntime,LiquidCandidate,LiquidLedger
from app.research.strategy_extensions import FOUR,ResearchSpec
from app.quant_policy import target_weights
from test_quant_policy import session

def histories():
    dates=pd.bdate_range('2026-08-03','2026-08-31')
    return {s:pd.concat([session(str(d.date()),i+j) for j,d in enumerate(dates)]) for i,s in enumerate((*FOUR,'SPY'))}

def metadata(symbols):
    return {s:dict(known_at='2026-08-01T00:00Z',exchange='NMS',quote_type='EQUITY',instrument_type='common_stock',leveraged=False,market_cap=100e9) for s in symbols}

def test_price_and_volume_use_only_prior_full_sessions():
    frames=histories();rules=LiquidityRules(min_adv=1)
    a=daily_eligibility(frames,FOUR,'2026-08-31',rules)
    changed={s:f.copy() for s,f in frames.items()}
    for f in changed.values():f.loc['2026-08-31':,['Open','High','Low','Close','Volume']]*=100
    assert a==daily_eligibility(changed,FOUR,'2026-08-31',rules)
    assert all(x['eligible'] and x['history_end']=='2026-08-28' for x in a.values())
    changed['TSLA']=changed['TSLA'].drop(changed['TSLA'].index[4])
    assert daily_eligibility(changed,FOUR,'2026-08-31',rules)['TSLA']['reason']=='incomplete_prior_sessions'
    small={s:f.copy() for s,f in frames.items()}
    small['SNDK'].loc[:,['Open','High','Low','Close']]/=100
    assert daily_eligibility(small,FOUR,'2026-08-31',rules)['SNDK']['reason']=='low_price'
    assert not daily_eligibility(frames,FOUR,'2026-08-31',LiquidityRules(min_adv=1e20))['MSTR']['eligible']

def test_calendar_window_can_begin_on_weekend():
    rows=daily_eligibility(histories(),FOUR,'2026-09-01',LiquidityRules(min_adv=1))
    assert all(r['eligible'] and r['sessions']==20 and r['history_end']=='2026-08-31' for r in rows.values())

@pytest.mark.parametrize('field,value',[('exchange','PNK'),('quote_type','ETF'),('instrument_type','warrant'),('leveraged',True),('known_at','2027-01-01T00:00Z')])
def test_unknown_otc_products_and_future_metadata_cannot_pass(field,value):
    record=metadata(['X'])['X'];record[field]=value
    assert not instrument_admission(record,'2026-09-01T00:00Z')[0]
    assert not instrument_admission(None,'2026-09-01T00:00Z')[0]

def test_joint_allocator_reconciles_ineligible_holdings_and_matches_original_when_eligible():
    cov=np.array([[.0002,.00005],[.00005,.0001]]);mu={'a':.003,'b':.002};old={'a':.3,'b':.1};spec=ResearchSpec('test')
    w,_=allocate(mu,cov,old,spec,('a','b'),dict(a=True,b=True))
    original=target_weights(mu,cov,old,spec,symbols=('a','b'),solver='osqp')
    np.testing.assert_allclose(list(w.values()),list(original.values()),atol=1e-7)
    restricted,explanation=allocate(mu,cov,old,spec,('a','b'),dict(a=False,b=True))
    assert restricted['a']==0 and abs(restricted['b'])<=.7
    assert explanation['estimated_turnover_cost']>=.3*.0005
    with pytest.raises(ValueError,match='All current exposure'):
        allocate(mu,cov,dict(old,c=.1),spec,('a','b'),dict(a=True,b=True))

def test_calibration_and_dynamic_risk_ignore_future_bars():
    frames=histories();meta=metadata(frames);rules=LiquidityRules(min_adv=1)
    c=LiquidCandidate('test',universe='four',calibration=True,integrated_risk=True)
    cut=pd.Timestamp('2026-08-31 10:00',tz='America/New_York');index=frames['TSLA'].loc[cut.normalize():cut].index
    a=LiquidRuntime(frames,rules,meta);b=LiquidRuntime({s:f.loc[:cut] for s,f in frames.items()},rules,meta)
    # Four symbols use SOXX/IBIT references in integrated risk, so provide real
    # synthetic reference fixtures independently of membership in this unit test.
    for runtime in (a,b):
        runtime.returns['SOXX']=runtime.returns['SPY'];runtime.returns['IBIT']=runtime.returns['SPY']
    x=a.prepare(c,'2026-08-31',index);y=b.prepare(c,'2026-08-31',index)
    np.testing.assert_allclose(x['calibration']['coef'],y['calibration']['coef'])
    assert x['calibration']['validation_dates'][-1]=='2026-08-28'
    assert all(f['training_last_session']<f['validation_day'] for f in x['calibration']['folds'])
    wa,_=a.target(c,x,len(index)-1,{});wb,_=b.target(c,y,len(index)-1,{})
    np.testing.assert_allclose(list(wa.values()),list(wb.values()))

def test_market_cap_and_metadata_dates_are_distinct_from_historical_price_admission():
    frames=histories();meta=metadata(frames);meta['MSTR']['market_cap']=1e9;meta['TSLA']['known_at']='2026-09-13T00:00Z'
    c=LiquidCandidate('test',universe='four');index=frames['TSLA'].loc['2026-08-31'].index
    strict=LiquidRuntime(frames,LiquidityRules(min_adv=1),meta).prepare(c,'2026-08-31',index)
    assert not strict['eligibility']['MSTR']['eligible'] and not strict['eligibility']['TSLA']['eligible']
    research=LiquidRuntime(frames,LiquidityRules(min_adv=1),meta,research_membership=True).prepare(c,'2026-08-31',index)
    assert research['eligibility']['TSLA']['eligible']
    assert research['eligibility']['TSLA']['membership_basis']=='contemporary_selected_panel_not_historical_proof'

def test_gap_below_price_floor_does_not_open_penny_position_but_can_close_inventory():
    from app.research.policy_replay import ExecutionConfig
    ledger=LiquidLedger(['A'],ExecutionConfig(),LiquidityRules())
    stamp=pd.Timestamp('2026-08-31 09:35',tz='America/New_York')
    ledger.execute_targets({'A':100},{'A':9},stamp,None,'2026-08-31')
    assert ledger.shares['A']==0
    ledger.execute_targets({'A':100},{'A':12},stamp,None,'2026-08-31')
    assert ledger.shares['A']==100
    ledger.execute_targets({'A':0},{'A':9},stamp,None,'2026-08-31')
    assert ledger.shares['A']==0
