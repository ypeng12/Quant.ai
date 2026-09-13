import numpy as np
import pandas as pd
from test_stock_policy import panel,metadata,LiquidityRules
from app.research.stock_policy import StockCandidate,STOCKS
from app.research.conditional_policy import ConditionalRuntime
from app.research.incremental_policy import IncrementalRuntime


def test_new_features_ignore_unobserved_prices_and_same_day_future_labels():
    f=panel();cut=pd.Timestamp('2026-08-31 10:30',tz='America/New_York')
    rules=LiquidityRules(min_adv=1,min_market_cap=0)
    a=IncrementalRuntime(f,rules,metadata(f));b=IncrementalRuntime({s:x.loc[:cut] for s,x in f.items()},rules,metadata(f))
    for family in a.extra_x:
        for s in STOCKS:pd.testing.assert_frame_equal(a.extra_x[family][s].loc[:cut],b.extra_x[family][s])
    c=StockCandidate('test',model='all');idx=pd.DatetimeIndex([cut])
    x=a.prepare(c,'2026-08-31',idx);y=b.prepare(c,'2026-08-31',idx)
    assert all(t['last_train']<'2026-08-31' for t in x['training'])
    wa,_=a.target(c,x,0,{});wb,_=b.target(c,y,0,{})
    np.testing.assert_allclose(list(wa.values()),list(wb.values()),atol=1e-7)


def test_frozen_control_and_intraday_range_boundaries():
    f=panel();rules=LiquidityRules(min_adv=1,min_market_cap=0)
    a=IncrementalRuntime(f,rules,metadata(f));b=ConditionalRuntime(f,rules,metadata(f))
    c=StockCandidate('control',model='state_ridge');idx=f['SNDK'].loc['2026-08-31'].index
    x=a.prepare(c,'2026-08-31',idx);y=b.prepare(c,'2026-08-31',idx)
    for s in STOCKS:
        np.testing.assert_allclose(x['mu'][s],y['mu'][s])
        assert pd.isna(a.extra_x['range'][s].loc[idx[0],'distance_prior_high'])
        assert np.isfinite(a.extra_x['slot'][s].loc[idx[0],'prior_5_same_slot_mean'])
