from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pytest
from app.research import solver_retry
from app.quant_policy import target_weights,PolicySpec

def test_retry_preserves_objective_and_never_changes_signal_or_cost(monkeypatch):
    mu={'a':.002,'b':-.001};cov=np.array([[.0001,.00002],[.00002,.0002]])
    current={'a':.1,'b':-.05};spec=PolicySpec('retry',cost_bps=5,risk_aversion=50)
    calls=[]
    def fail_qp(*args,**kwargs):
        calls.append((args,kwargs.copy()))
        if kwargs['solver']=='osqp':raise RuntimeError('Portfolio QP failed: maximum iterations reached')
        return target_weights(*args,**kwargs)
    monkeypatch.setattr(solver_retry,'target_weights',fail_qp)
    result=solver_retry.retry_target_weights(mu,cov,current,spec,symbols=('a','b'),solver='osqp')
    assert [kw['solver'] for _,kw in calls]==['osqp','slsqp']
    assert all(a[0] is mu and a[1] is cov and a[2] is current and a[3] is spec for a,_ in calls)
    original=target_weights(mu,cov,current,spec,symbols=('a','b'),solver='osqp')
    np.testing.assert_allclose(list(result.values()),list(original.values()),atol=1e-5)

def test_unrelated_runtime_failure_is_not_masked(monkeypatch):
    def fail(*args,**kwargs):raise RuntimeError('Invalid state')
    monkeypatch.setattr(solver_retry,'target_weights',fail)
    with pytest.raises(RuntimeError,match='Invalid state'):
        solver_retry.retry_target_weights({'a':0},np.eye(1),{},PolicySpec('x'),solver='osqp')
