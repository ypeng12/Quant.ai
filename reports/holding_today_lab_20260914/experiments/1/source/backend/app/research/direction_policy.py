"""Market/industry direction forecasts and receding-horizon portfolio research.

Only four stocks trade. Reference assets provide observed features. No date or
ticker-specific direction overrides, trade lockouts, or broker imports.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import minimize,Bounds,LinearConstraint
from sklearn.covariance import LedoitWolf
import osqp
from .liquid_policy import LiquidCandidate,LiquidRuntime,allocate
from .strategy_extensions import FOUR,ResearchSpec,feature_panel,mature_fit,predict
from ..quant_policy import normalize_bars,horizon_fraction,_validated_covariance

REFERENCES=('SPY','QQQ','SOXX','IBIT')
REFERENCE_MAP={'SNDK':'SOXX','NVDA':'SOXX','TSLA':'QQQ','MSTR':'IBIT'}

@dataclass(frozen=True)
class DirectionCandidate(LiquidCandidate):
    universe: str='four'
    model: str='tree'
    horizon: int=1
    planning: bool=False

DIRECTION_CANDIDATES=(
    DirectionCandidate('four_tree_control',control=True),
    DirectionCandidate('market_tree_h1'),
    DirectionCandidate('market_tree_h6',horizon=6),
    DirectionCandidate('market_ridge_h6',model='ridge',horizon=6),
    DirectionCandidate('market_tree_h12',horizon=12),
    DirectionCandidate('market_curve_ridge',model='ridge',horizon=6,planning=True),
)

def direction_features(frames):
    """Keep the original four-stock peer features; append explicit references."""
    missing=set((*FOUR,*REFERENCES))-set(frames)
    if missing:raise ValueError(f'Missing direction inputs: {sorted(missing)}')
    own=feature_panel({s:frames[s] for s in FOUR},'context')
    refs=feature_panel({s:frames[s] for s in REFERENCES},'context')
    for s,f in own.items():
        for role,ref in [('market','SPY'),('reference',REFERENCE_MAP[s])]:
            other=refs[ref].reindex(f.index)
            for col in ('return_1','return_3','return_12','session_return','vwap_distance','seasonal_volume'):
                f[f'{role}_{col}']=other[col]
            f[f'{role}_relative_session_return']=f.session_return-other.session_return
            pair=pd.concat([f.return_1,other.return_1],axis=1)
            beta=pair.iloc[:,0].expanding(min_periods=2).cov(pair.iloc[:,1]).shift()/pair.iloc[:,1].expanding(min_periods=2).var().shift().replace(0,np.nan)
            f[f'{role}_residual_return_1']=f.return_1-beta*other.return_1
        b=normalize_bars(frames[s]);group=b.groupby(b.index.date)
        # Observed running extrema, not the session's future high/low.
        f['drawdown_from_running_high']=b.close/group.high.cummax()-1
        f['rebound_from_running_low']=b.close/group.low.cummin()-1
        own[s]=f.replace([np.inf,-np.inf],np.nan)
    return own

def planned_target(forecasts,covariance,current,symbols,eligible,spec,*,shortable=None):
    """Trade only the first step of a fully costed hypothetical holding plan.

    Risk uses a covariance matrix of sequential, cross-stock returns estimated
    before the decision date. Intermediate turnover and terminal liquidation
    both cost money. Future weights are plans, never claimed future fills.
    """
    symbols=tuple(symbols);n=len(symbols);mu=np.asarray(forecasts,dtype=float)
    if mu.ndim!=2 or mu.shape[1]!=n or not np.isfinite(mu).all():raise ValueError('Finite horizon-by-symbol forecasts required')
    k=len(mu);m=k*n
    if k<1 or any(v!=0 for s,v in current.items() if s not in symbols):raise ValueError('All current exposure must be budgeted')
    old=np.array([current.get(s,0.) for s in symbols]);cov=_validated_covariance(covariance,m)
    if not np.isfinite(old).all():raise ValueError('Nonfinite holdings')
    limits=np.tile([spec.symbol_limit if eligible.get(s,False) else 0 for s in symbols],k)
    d=np.eye(m)
    for step in range(1,k):d[step*n:(step+1)*n,(step-1)*n:step*n]=-np.eye(n)
    eye=np.eye(m);zero=np.zeros((m,m));b=np.r_[old,np.zeros(m-n)]
    gross=np.kron(np.eye(k),np.ones((1,n)))
    a=np.vstack([np.hstack([-d,eye,zero]),np.hstack([d,eye,zero]),np.hstack([-eye,zero,eye]),
        np.hstack([eye,zero,eye]),np.hstack([np.zeros((k,2*m)),-gross])])
    lower=np.r_[-b,b,np.zeros(2*m),np.full(k,-spec.gross_limit)]
    lower_weights = -limits
    if shortable is not None:
        lower_weights = np.tile([-spec.symbol_limit if eligible.get(s,False) and shortable.get(s,False) else 0 for s in symbols],k)
    bounds=Bounds(np.r_[lower_weights,np.zeros(2*m)],np.r_[limits,np.full(2*m,np.inf)])
    cost=spec.cost_bps/10000
    terminal=np.r_[np.zeros(m-n),np.full(n,cost)]
    scale=max(abs(mu).max(),spec.risk_aversion*abs(cov).max(),cost,np.finfo(float).eps)
    p=sparse.block_diag([spec.risk_aversion*cov/scale,sparse.csc_matrix((2*m,2*m))],format='csc')
    q=np.r_[-mu.ravel(),np.full(m,cost),terminal]/scale
    matrix=sparse.vstack([sparse.csc_matrix(a),sparse.eye(3*m)],format='csc')
    lo=np.r_[lower,bounds.lb];hi=np.r_[np.full(len(lower),np.inf),bounds.ub]
    initial=np.clip(old,lower_weights[:n],limits[:n])
    if abs(initial).sum()>spec.gross_limit:initial*=spec.gross_limit/abs(initial).sum()
    w0=np.tile(initial,k);x0=np.r_[w0,abs(d@w0-b),abs(w0)]
    qp=osqp.OSQP();qp.setup(P=sparse.triu(p,format='csc'),q=q,A=matrix,l=lo,u=hi,verbose=False,
        eps_abs=1e-8,eps_rel=1e-8,max_iter=100000,polishing=True)
    qp.warm_start(x=x0);result=qp.solve(raise_error=False);solver='osqp_multiperiod'
    if result.info.status=='solved':x=result.x
    else:
        solver='slsqp_multiperiod_same_objective'
        retry=minimize(lambda x:float(.5*x@p@x+q@x),x0,jac=lambda x:p@x+q,method='SLSQP',bounds=bounds,
            constraints=[LinearConstraint(a,lower,np.full(len(lower),np.inf))],options=dict(ftol=1e-11,maxiter=1000))
        if not retry.success:raise RuntimeError(f'Multiperiod optimization failed: {retry.message}')
        x=retry.x
    if not np.isfinite(x).all() or max(np.max(lo-matrix@x),np.max(matrix@x-hi))>1e-6:raise ValueError('Infeasible holding plan')
    planned=np.clip(x[:m],lower_weights,limits).reshape(k,n);planned[abs(planned)<1e-10]=0
    for w in planned:
        if abs(w).sum()>spec.gross_limit:w*=spec.gross_limit/abs(w).sum()
    changes=np.diff(np.vstack([old,planned]),axis=0)
    return dict(zip(symbols,map(float,planned[0]))),dict(solver=solver,planned_steps=k,
        planned_weights=planned.tolist(),forecast_curve_bps=(mu*10000).tolist(),
        estimated_plan_turnover_cost=float(cost*abs(changes).sum()),estimated_terminal_cost=float(cost*abs(planned[-1]).sum()),
        forecast_portfolio_return=float((mu*planned).sum()),forecast_variance=float(planned.ravel()@cov@planned.ravel()))

class DirectionRuntime(LiquidRuntime):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.direction_x=direction_features(self.frames)
        self.direction_models={};self.block_covariances={}

    def forecast_context(self,c,day,index,horizon):
        key=(c.model,horizon,day,tuple(index))
        if key not in self.direction_models:
            mu={};training=[]
            for s in FOUR:
                f=mature_fit(self.direction_x[s],self.base.label(s,horizon),day,c.model)
                mu[s]=predict(f,self.direction_x[s].reindex(index))
                training.append(dict(symbol=s,horizon=horizon,model=c.model,last_train=f['last_train'],rows=f['rows'],sessions=f['sessions'],names=list(f['names'])))
            self.direction_models[key]=dict(mu=mu,training=training,covariance=self.base.covariance(FOUR,horizon,day))
        return self.direction_models[key]

    def block_covariance(self,day,k):
        key=(day,k)
        if key not in self.block_covariances:
            labels=pd.DataFrame({s:self.base.label(s,1) for s in FOUR})
            labels=labels.loc[labels.index.strftime('%Y-%m-%d')<day]
            blocks=[]
            for _,group in labels.groupby(labels.index.date):
                matrix=pd.concat([group.shift(-j) for j in range(k)],axis=1).dropna()
                # Label construction validates adjacent bars; retain only a
                # complete consecutive sequence across the full planning span.
                valid=group.index.to_series().shift(-(k-1))-group.index.to_series()==pd.Timedelta(minutes=5*(k-1))
                blocks.append(matrix.loc[matrix.index.intersection(valid[valid].index)].to_numpy())
            values=np.concatenate(blocks)
            if len(values)<2:raise ValueError('Insufficient mature holding-path observations')
            self.block_covariances[key]=LedoitWolf().fit(values).covariance_
        return self.block_covariances[key]

    def prepare(self,c,day,index):
        # Reuse only the audited admission/control path; changed models have
        # their own explicit forecast labels and reference inputs.
        base=super().prepare(c,day,index)
        if c.control:return base
        context=self.forecast_context(c,day,index,c.horizon)
        base.update(context)
        if c.planning:
            base['short']=self.forecast_context(c,day,index,1)
            base['training']=[*context['training'],*base['short']['training']]
        return base

    def target(self,c,context,i,current,cost=5):
        if c.control:return super().target(c,context,i,current,cost)
        symbols=FOUR;stamp=context['index'][i];day=str(stamp.date())
        spec=ResearchSpec(c.name,horizon_bars=c.horizon,cost_bps=cost,symbol_limit=c.symbol_limit)
        eligible={s:context['eligibility'][s]['eligible'] and float(self.normalized[s].loc[stamp,'close'])>=self.rules.min_price for s in symbols}
        if c.planning:
            entry=stamp+pd.Timedelta(minutes=5);end=pd.Timestamp(f'{day} 15:55',tz='America/New_York')
            k=min(c.horizon,int((end-entry)/pd.Timedelta(minutes=5)))
            if k<1:raise ValueError('No executable interval remains')
            short=np.array([context['short']['mu'][s][i] for s in symbols]);long=np.array([context['mu'][s][i] for s in symbols])
            curve=np.vstack([short,np.tile((long-short)/(c.horizon-1),(c.horizon-1,1))])[:k]
            weights,explanation=planned_target(curve,self.block_covariance(day,k),current,symbols,eligible,spec)
            explanation['forecast']={s:float(context['mu'][s][i]) for s in symbols}
        else:
            fraction=horizon_fraction(stamp,spec)
            mu={s:float(context['mu'][s][i])*fraction for s in symbols}
            weights,explanation=allocate(mu,context['covariance']*fraction,current,spec,symbols,eligible)
        explanation['eligible']=eligible
        return weights,explanation
