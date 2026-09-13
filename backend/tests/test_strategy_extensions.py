from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import pytest
from app.research.strategy_extensions import (ResearchSpec,Extension,ResearchRuntime,feature_panel,
    mature_fit,predict,opening_activity,pair_target,PairForecast)
from app.quant_policy import labeled_frame
from test_quant_policy import session

def panel():
    return {s:pd.concat([session('2026-09-08',n),session('2026-09-09',n+1),session('2026-09-10',n+2)])
        for s,n in [('SNDK',1),('TSLA',3),('MSTR',5),('NVDA',7),('SPY',9),('SOXX',11),('IBIT',13)]}

def test_sector_features_and_opening_selection_ignore_future_bars():
    frames=panel();cut=pd.Timestamp('2026-09-10 09:30',tz='America/New_York')
    full=feature_panel(frames,'sector')
    prefix=feature_panel({s:f.loc[:cut] for s,f in frames.items()},'sector')
    for s in frames:pd.testing.assert_frame_equal(full[s].loc[:cut],prefix[s])
    symbols=('SNDK','TSLA','MSTR','NVDA')
    assert opening_activity(full,symbols,'2026-09-10',2)==opening_activity(prefix,symbols,'2026-09-10',2)
    assert opening_activity(full,symbols,'2026-09-10',2)[1]['available_at'].endswith('09:35:00-04:00')

def test_pooled_training_purges_all_same_day_labels():
    frames=panel();features=feature_panel(frames,'context');symbols=('SNDK','TSLA')
    x=pd.concat([features[s] for s in symbols]);y=pd.concat([labeled_frame(frames[s],ResearchSpec('h',horizon_bars=3))[1] for s in symbols])
    a=mature_fit(x,y,'2026-09-10','ridge')
    later=x.index.strftime('%Y-%m-%d')=='2026-09-10'
    changed=x.copy();changed.iloc[np.flatnonzero(later)]=1e9
    changed_y=y.copy();changed_y.iloc[np.flatnonzero(later)]=1e9
    b=mature_fit(changed,changed_y,'2026-09-10','ridge')
    np.testing.assert_allclose(predict(a,x),predict(b,x));assert a['last_train']=='2026-09-09'

def test_sixty_minute_labels_require_every_intermediate_bar_and_intraday_maturity():
    f=session('2026-09-10',3);spec=ResearchSpec('h12',horizon_bars=12)
    _,y=labeled_frame(f,spec)
    assert y.iloc[0]==pytest.approx(f.Close.iloc[12]/f.Open.iloc[1]-1)
    assert y.iloc[-13:].isna().all()
    _,broken=labeled_frame(f.drop(f.index[5]),spec)
    assert np.isnan(broken.iloc[0])

@pytest.mark.parametrize('beta',[.5,1.5,-.5])
def test_pair_optimizer_matches_scalar_grid_and_budgets_both_legs(beta):
    cov=np.array([[.0002,.00003],[.00003,.0001]])
    spec=ResearchSpec('pair',cost_bps=5);old={'a':.1,'b':-.05};mu=.002
    result=pair_target(mu,beta,cov,old,spec,('a','b'))
    w=np.array([result['a'],result['b']]);assert w[1]==pytest.approx(-beta*w[0])
    assert abs(w).sum()<=.95+1e-9 and abs(w).max()<=.7+1e-9
    direction=np.array([1,-beta]);cap=min(.95/abs(direction).sum(),.7/abs(direction).max())
    grid=np.linspace(-cap,cap,20001)
    objective=lambda q:-mu*q+25*q*q*(direction@cov@direction)+.0005*abs(q*direction-np.array([.1,-.05])).sum()
    assert objective(w[0])<=min(map(objective,grid))+1e-10

def test_pair_model_prior_fit_does_not_use_future_price_levels():
    frames=panel();symbols=('NVDA','IBIT')
    a=PairForecast().fit(frames,symbols,'2026-09-10',3)
    changed={s:f.copy() for s,f in frames.items()}
    for f in changed.values():f.loc['2026-09-10':,['Open','High','Low','Close']]*=100
    b=PairForecast().fit(changed,symbols,'2026-09-10',3)
    assert a.beta==pytest.approx(b.beta)
    np.testing.assert_allclose(a.fitted['model'].coef_,b.fitted['model'].coef_)

def test_runtime_same_completed_bar_prediction_with_or_without_later_bars():
    frames=panel();cut=pd.Timestamp('2026-09-10 10:00',tz='America/New_York')
    candidate=Extension('pooled',pooled=True,horizon=3,model='ridge')
    index=frames['TSLA'].loc[cut.normalize():cut].index
    full=ResearchRuntime(frames).prepare(candidate,'2026-09-10',index)
    prefix=ResearchRuntime({s:f.loc[:cut] for s,f in frames.items()}).prepare(candidate,'2026-09-10',index)
    for s in full['predictions']:np.testing.assert_allclose(full['predictions'][s],prefix['predictions'][s])
    a=ResearchRuntime.target(full,len(index)-1,{},ResearchSpec('h3',horizon_bars=3))
    b=ResearchRuntime.target(prefix,len(index)-1,{},ResearchSpec('h3',horizon_bars=3))
    np.testing.assert_allclose(list(a.values()),list(b.values()))

def test_cached_risk_matches_uncached_reference_calculation():
    from app.research.strategy_extensions import horizon_covariance,reference_covariance
    frames=panel();symbols=('SNDK','TSLA','MSTR','NVDA');runtime=ResearchRuntime(frames)
    for h in (3,12):
        cov=horizon_covariance(frames,'2026-09-10',symbols,h)
        np.testing.assert_allclose(runtime.covariance(symbols,h,'2026-09-10'),cov,rtol=0,atol=0)
        ref=reference_covariance(frames,'2026-09-10',symbols,h)
        np.testing.assert_allclose(runtime.covariance(symbols,h,'2026-09-10',True),cov+ref,rtol=0,atol=0)
