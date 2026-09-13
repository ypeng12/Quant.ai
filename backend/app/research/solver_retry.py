"""Research-only numerical retry of the unchanged convex portfolio objective."""
import numpy as np
from ..quant_policy import target_weights

def retry_target_weights(mu,covariance,current,spec,**kwargs):
    try:return target_weights(mu,covariance,current,spec,**kwargs)
    except RuntimeError as exc:
        if kwargs.get('solver')!='osqp' or 'Portfolio QP failed:' not in str(exc):raise
        retried=dict(kwargs,solver='slsqp')
        result=target_weights(mu,covariance,current,spec,**retried)
        symbols=tuple(kwargs.get('symbols',sorted(mu)));w=np.array([result[s] for s in symbols])
        if not np.isfinite(w).all() or abs(w).sum()>spec.gross_limit+1e-8 or abs(w).max()>spec.symbol_limit+1e-8:
            raise RuntimeError('Retry returned infeasible allocation')
        old=np.array([current.get(s,0.) for s in symbols]);expected=np.array([mu[s] for s in symbols])
        # Retry is used for the extensions' plain joint objective only.
        if any(key in kwargs for key in ('uncertainty','costs_bps')):raise ValueError('Unsupported retry penalties')
        def objective(v):return -expected@v+spec.risk_aversion/2*v@covariance@v+spec.cost_bps/10000*abs(v-old).sum()
        if objective(w)>objective(np.zeros(len(w)))+1e-8:raise RuntimeError('Retry is worse than feasible cash portfolio')
        return result
