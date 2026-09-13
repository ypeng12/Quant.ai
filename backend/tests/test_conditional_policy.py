import numpy as np
import pandas as pd
from test_stock_policy import panel, metadata, LiquidityRules
from app.research.stock_policy import StockCandidate, StockRuntime, STOCKS
from app.research.conditional_policy import ConditionalRuntime


def test_state_features_horizon_predictions_and_targets_are_prefix_causal():
    f=panel();cut=pd.Timestamp('2026-08-31 10:30',tz='America/New_York');index=pd.DatetimeIndex([cut])
    rules=LiquidityRules(min_adv=1,min_market_cap=0)
    a=ConditionalRuntime(f,rules,metadata(f));b=ConditionalRuntime({s:x.loc[:cut] for s,x in f.items()},rules,metadata(f))
    for s in STOCKS:pd.testing.assert_frame_equal(a.state_x[s].loc[:cut],b.state_x[s])
    for h in (1,6):
        c=StockCandidate('test',model='state_ridge',horizon=h)
        x=a.prepare(c,'2026-08-31',index);y=b.prepare(c,'2026-08-31',index)
        assert all(t['last_train']<'2026-08-31' and t['horizon']==h for t in x['training'])
        for s in STOCKS:np.testing.assert_allclose(x['mu'][s],y['mu'][s])
        wa,_=a.target(c,x,0,{});wb,_=b.target(c,y,0,{})
        np.testing.assert_allclose(list(wa.values()),list(wb.values()),atol=1e-7)


def test_control_keeps_original_predictions_and_portfolio():
    f=panel();rules=LiquidityRules(min_adv=1,min_market_cap=0);index=f['SNDK'].loc['2026-08-31'].index
    a=ConditionalRuntime(f,rules,metadata(f));b=StockRuntime(f,rules,metadata(f))
    c=StockCandidate('control',model='market_ridge')
    x=a.prepare(c,'2026-08-31',index);y=b.prepare(c,'2026-08-31',index)
    wa,_=a.target(c,x,12,{});wb,_=b.target(c,y,12,{})
    np.testing.assert_allclose(list(wa.values()),list(wb.values()),atol=1e-7)
