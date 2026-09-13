import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import pytest
from app.research.direction_policy import direction_features,planned_target,DirectionRuntime,DirectionCandidate,REFERENCES,FOUR
from app.research.liquid_policy import allocate,LiquidityRules
from app.research.strategy_extensions import ResearchSpec,feature_panel
from test_liquid_policy import histories,metadata

def panel():
    f=histories()
    for i,s in enumerate(REFERENCES):
        if s not in f:
            f[s]=f['SPY'].copy();f[s].loc[:,['Open','High','Low','Close']]*=1+i*.1
    return f

def test_reference_features_keep_original_peer_scope_and_ignore_future():
    f=panel();a=direction_features(f);cut=pd.Timestamp('2026-08-31 10:00',tz='America/New_York')
    b=direction_features({s:x.loc[:cut] for s,x in f.items()})
    old=feature_panel({s:f[s] for s in FOUR},'context')
    for s in FOUR:
        pd.testing.assert_frame_equal(a[s].loc[:cut],b[s])
        pd.testing.assert_series_equal(a[s].peer_return_1,old[s].peer_return_1)
        assert 'market_session_return' in a[s] and 'reference_relative_session_return' in a[s]

def test_multiperiod_plan_can_exit_a_short_that_myopic_cost_objective_retains():
    spec=ResearchSpec('plan');old={'a':-.5};elig={'a':True};mu=.00013
    one,_=allocate({'a':mu},np.eye(1)*1e-8,old,spec,('a',),elig)
    plan,detail=planned_target(np.full((6,1),mu),np.eye(6)*1e-8,old,('a',),elig,spec)
    assert one['a']<-.49 and plan['a']>=-1e-6
    assert detail['estimated_plan_turnover_cost']>=.5*.0005-1e-8
    assert detail['estimated_terminal_cost']>=0
    assert all(abs(w[0])<=.7+1e-8 for w in detail['planned_weights'])
    with pytest.raises(ValueError,match='All current exposure'):
        planned_target(np.zeros((2,1)),np.eye(2),{'unknown':.1},('a',),elig,spec)

def test_planned_risk_and_predictions_use_only_prior_sessions():
    f=panel();cut=pd.Timestamp('2026-08-31 10:00',tz='America/New_York');idx=pd.DatetimeIndex([cut])
    a=DirectionRuntime(f,LiquidityRules(min_adv=1),metadata(f))
    b=DirectionRuntime({s:x.loc[:cut] for s,x in f.items()},LiquidityRules(min_adv=1),metadata(f))
    c=DirectionCandidate('test',model='ridge',horizon=6,planning=True)
    x=a.prepare(c,'2026-08-31',idx);y=b.prepare(c,'2026-08-31',idx)
    assert all(t['last_train']<'2026-08-31' for t in x['training'])
    np.testing.assert_allclose(a.block_covariance('2026-08-31',6),b.block_covariance('2026-08-31',6))
    wa,_=a.target(c,x,0,{});wb,_=b.target(c,y,0,{})
    np.testing.assert_allclose(list(wa.values()),list(wb.values()),atol=1e-7)

def test_planner_uses_only_remaining_executable_intervals_near_close():
    f=panel();runtime=DirectionRuntime(f,LiquidityRules(min_adv=1),metadata(f))
    c=DirectionCandidate('test',model='ridge',horizon=6,planning=True)
    idx=pd.DatetimeIndex([pd.Timestamp('2026-08-31 15:45',tz='America/New_York')])
    context=runtime.prepare(c,'2026-08-31',idx)
    _,detail=runtime.target(c,context,0,{})
    assert detail['planned_steps']==1
