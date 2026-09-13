"""Explicit concentration experiments; no mandatory trades or broker imports."""
from dataclasses import dataclass
import numpy as np
from .liquid_policy import LiquidCandidate,LiquidRuntime,allocate
from .strategy_extensions import ResearchSpec

@dataclass(frozen=True)
class ActiveCandidate(LiquidCandidate):
    risk_aversion: float=50.
    single_stock: bool=False

ACTIVE_CANDIDATES=(
    ActiveCandidate('four_tree_control',universe='four',control=True),
    ActiveCandidate('liquid_dynamic_70'),
    ActiveCandidate('four_concentrated_95',universe='four',symbol_limit=.95),
    ActiveCandidate('liquid_single_95',symbol_limit=.95,single_stock=True),
    ActiveCandidate('liquid_dynamic_95_g25',symbol_limit=.95,risk_aversion=25.),
)

def single_stock_target(mu,covariance,current,symbols,eligible,spec):
    """Choose cash or one signed 95% target using the same mean/risk/cost utility.

    Both closing old holdings and opening a new stock incur cost. The search
    uses forecasts, not the day's realized high/low or future realized return.
    This is a discrete stress comparator, not a claim that 95% is optimal.
    """
    symbols=tuple(symbols)
    if set(mu)!=set(symbols) or any(v!=0 for s,v in current.items() if s not in symbols):raise ValueError('All current exposure must be budgeted')
    from ..quant_policy import _validated_covariance
    cov=_validated_covariance(covariance,len(symbols))
    forecast=np.array([mu[s] for s in symbols]);old=np.array([current.get(s,0.) for s in symbols])
    if not np.isfinite(forecast).all() or not np.isfinite(old).all():raise ValueError('Nonfinite input')
    cost=spec.cost_bps/10000
    def utility(w):return float(forecast@w-.5*spec.risk_aversion*w@cov@w-cost*abs(w-old).sum())
    best=np.zeros(len(symbols));best_score=utility(best)
    for i,s in enumerate(symbols):
        if not eligible.get(s,False):continue
        for sign in (1,-1):
            w=np.zeros(len(symbols));w[i]=sign*min(spec.symbol_limit,spec.gross_limit)
            score=utility(w)
            if score>best_score:best,best_score=w,score
    return dict(zip(symbols,map(float,best))),dict(solver='enumerated_cash_or_single_stock',forecast=mu,
        estimated_turnover_cost=float(cost*abs(best-old).sum()),forecast_portfolio_return=float(forecast@best),
        forecast_variance=float(best@cov@best),objective=best_score)

class ActiveRuntime(LiquidRuntime):
    def target(self,c,context,i,current,cost=5):
        symbols=context['symbols'];stamp=context['index'][i]
        spec=ResearchSpec(c.name,cost_bps=cost,symbol_limit=c.symbol_limit,risk_aversion=c.risk_aversion)
        eligible={s:context['eligibility'][s]['eligible'] and float(self.normalized[s].loc[stamp,'close'])>=self.rules.min_price for s in symbols}
        mu={s:float(context['mu'][s][i]) for s in symbols}
        fn=single_stock_target if c.single_stock else allocate
        if c.single_stock:weights,explanation=fn(mu,context['covariance'],current,symbols,eligible,spec)
        else:weights,explanation=fn(mu,context['covariance'],current,spec,symbols,eligible)
        explanation['eligible']=eligible
        return weights,explanation
