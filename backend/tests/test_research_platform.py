from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import pytest
from app.alpha.real_l1_alpha import _ofi, build_real_l1_features
from app.quant_policy import PolicySpec, target_weights, panel_feature_frames
from app.research.platform import FittedForecast, joint_risk, features_for_panel
from test_quant_policy import session


def test_ofi_counts_removed_depth_at_worsening_quotes_and_resets_day():
    q=pd.DataFrame({'bid_price':[100,99,99,100], 'ask_price':[101,102,102,101],
                    'bid_size':[10,50,55,100], 'ask_size':[20,60,65,100]},
                   index=pd.to_datetime(['2026-09-10T14:00Z','2026-09-10T14:01Z','2026-09-10T14:02Z','2026-09-11T14:00Z']))
    # bid worsens: -10; ask worsens: +20. Equal moves +5 and -5 cancel.
    assert _ofi(q).tolist()==[0,10,0,0]


def test_l1_future_and_stale_quotes_cannot_classify_trade():
    idx=pd.to_datetime(['2026-09-11T13:30:00Z','2026-09-11T13:31:00Z','2026-09-11T13:35:01Z'])
    f=pd.DataFrame(dict(event_type=['quote','trade','quote'],source=['alpaca_stock_websocket']*3,symbol=['TSLA']*3,
        market_depth=['L1','trade_print','L1'],bid_price=[100,np.nan,200],ask_price=[101,np.nan,201],
        bid_size=[10,np.nan,20],ask_size=[20,np.nan,10],price=[np.nan,101,np.nan],size=[np.nan,5,np.nan]),index=idx)
    result=build_real_l1_features(f,as_of=pd.Timestamp('2026-09-11T13:35:02Z'))
    assert len(result)==1 and np.isnan(result.iloc[0].l1_signed_trade_imbalance)
    assert result.iloc[0].l1_quote_imbalance<0


def test_uncertainty_cost_and_correlation_affect_joint_weights():
    spec=PolicySpec('test',risk_aversion=20,cost_bps=0)
    cov=np.diag([.001,.001]);mu={'a':.01,'b':.01}
    base=target_weights(mu,cov,{},spec,symbols=('a','b'))
    error=target_weights(mu,cov,{},spec,symbols=('a','b'),uncertainty=[.008,0],uncertainty_aversion=1)
    assert error['a']<base['a'] and error['b']>=base['b']
    correlated=target_weights(mu,cov+np.ones((2,2))*.001,{},spec,symbols=('a','b'))
    assert sum(correlated.values())<sum(base.values())
    costly=target_weights(mu,cov,{},spec,symbols=('a','b'),costs_bps=[100,0])
    assert costly['a']<base['a']


def test_context_and_fit_are_prefix_causal():
    frames={s:pd.concat([session('2026-09-08',n),session('2026-09-09',n+1),session('2026-09-10',n+2)]) for s,n in [('A',1),('B',5)]}
    full=features_for_panel(frames,'context');prefix=features_for_panel({s:f.iloc[:-30] for s,f in frames.items()},'context')
    for s in full:pd.testing.assert_frame_equal(prefix[s],full[s].iloc[:-30])
    labels=frames['A'].Close.pct_change().shift(-1)
    a=FittedForecast('context','ridge').fit(full['A'],labels,'2026-09-10')
    altered=full['A'].copy();altered.loc['2026-09-10':]*=10000
    b=FittedForecast('context','ridge').fit(altered,labels,'2026-09-10')
    np.testing.assert_allclose(a.model.coef_,b.model.coef_)
    np.testing.assert_allclose(a.parameter_cov,b.parameter_cov)
    assert a.last_train=='2026-09-09'


def test_peer_common_missing_bucket_is_not_shorter_horizon():
    frame=session();frame=frame.drop(frame.index[4])
    features=panel_feature_frames({'A':frame,'B':frame},'price_volume_peer')
    assert np.isnan(features['A'].peer_return_1.iloc[4])


def test_qp_solver_matches_existing_objective_and_handles_thirty_correlated_names():
    rng=np.random.default_rng(71)
    for n in (4,30):
        symbols=tuple(f'S{i}' for i in range(n))
        factor=rng.normal(size=(n,3))*.002
        covariance=factor@factor.T+np.eye(n)*1e-6
        mu=dict(zip(symbols,rng.normal(size=n)*.0005));current=dict(zip(symbols,rng.normal(size=n)*.02))
        spec=PolicySpec('solver_comparison',risk_aversion=50,cost_bps=5)
        error=np.abs(rng.normal(size=n))*.00005
        qp=target_weights(mu,covariance,current,spec,symbols=symbols,uncertainty=error,uncertainty_aversion=1,solver='osqp')
        w=np.array([qp[s] for s in symbols])
        assert abs(w).sum()<=spec.gross_limit+1e-8 and abs(w).max()<=spec.symbol_limit+1e-8
        def objective(v):
            return -np.array(list(mu.values()))@v+25*v@covariance@v+.0005*abs(v-np.array(list(current.values()))).sum()+error@abs(v)
        assert objective(w)<=objective(np.zeros(n))+1e-8
        if n==4:
            old=target_weights(mu,covariance,current,spec,symbols=symbols,uncertainty=error,uncertainty_aversion=1)
            np.testing.assert_allclose(w,list(old.values()),atol=1e-4)
            assert abs(objective(w)-objective(np.array(list(old.values()))))<1e-8
