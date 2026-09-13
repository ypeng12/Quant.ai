"""Liquid-stock research policy. Inert: no broker, network or config imports.

Membership is a declared contemporary research panel; only dated price/volume
eligibility and model inputs are point-in-time. Live admission additionally
requires timestamped instrument metadata. No ticker-specific profit exclusion.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.optimize import nnls, minimize, Bounds, LinearConstraint
from scipy import sparse
import osqp
from sklearn.covariance import LedoitWolf
from ..quant_policy import normalize_bars,_validated_covariance
from .strategy_extensions import FOUR,REFERENCES,SECTOR_REFERENCE,Extension,ResearchRuntime,ResearchSpec
from .policy_replay import ShareLedger

EXTRA_STOCKS=('JNJ','XOM','PG','COST','WMT','UNH','V','MA')
RISK_REFERENCES=(*REFERENCES,'XLV','XLP','XLE')
REFERENCE_MAP={**SECTOR_REFERENCE,**dict.fromkeys(('JNJ','UNH'),'XLV'),
    **dict.fromkeys(('PG','COST','WMT'),'XLP'),'XOM':'XLE',**dict.fromkeys(('V','MA'),'XLF')}

@dataclass(frozen=True)
class LiquidityRules:
    min_price: float=10.
    min_adv: float=50_000_000.
    min_market_cap: float=50_000_000_000.
    lookback_sessions: int=20

    def __post_init__(self):
        if not np.isfinite([self.min_price,self.min_adv,self.min_market_cap]).all() or min(self.min_price,self.min_adv)<=0 or self.min_market_cap<0:
            raise ValueError('Positive finite price and dollar-volume thresholds required')
        if not isinstance(self.lookback_sessions,int) or self.lookback_sessions<2:raise ValueError('At least two history sessions required')

@dataclass(frozen=True)
class LiquidCandidate:
    name: str
    universe: str='broad'
    calibration: bool=False
    integrated_risk: bool=False
    symbol_limit: float=.7
    benchmark: bool=False
    control: bool=False

LIQUID_CANDIDATES=(
    LiquidCandidate('four_tree_control',universe='four',control=True),
    LiquidCandidate('largecap_four_tree',universe='four'),
    LiquidCandidate('largecap_equal',benchmark=True),
    LiquidCandidate('largecap_tree'),
    LiquidCandidate('largecap_calibrated',calibration=True),
    LiquidCandidate('largecap_integrated',calibration=True,integrated_risk=True),
    LiquidCandidate('largecap_integrated_25pct',calibration=True,integrated_risk=True,symbol_limit=.25),
)

class LiquidLedger(ShareLedger):
    """Apply the user's price eligibility to additions at the modeled fill open.

    Existing position reductions/closures still use the ordinary cash ledger.
    This is a simulation check, not a promise about an actual market-order fill.
    """
    def __init__(self,symbols,config,rules):
        super().__init__(symbols,config);self.liquidity_rules=rules

    def _feasible_addition(self,symbol,delta,prices):
        return prices[symbol]>=self.liquidity_rules.min_price and super()._feasible_addition(symbol,delta,prices)

def instrument_admission(record,as_of):
    """Unknown/OTC/derivative products cannot silently become eligible stocks."""
    if not record:return False,'missing_instrument_metadata'
    try:known=pd.Timestamp(record.get('known_at'))
    except (TypeError,ValueError):return False,'invalid_metadata_timestamp'
    now=pd.Timestamp(as_of)
    if known.tzinfo is None or now.tzinfo is None or known>now:return False,'metadata_not_known_at_decision'
    if record.get('exchange') not in ('NMS','NGM','NCM','NYQ','NASDAQ','NYSE'):return False,'unsupported_or_otc_exchange'
    if record.get('quote_type')!='EQUITY' or record.get('instrument_type') not in ('common_stock','adr'):
        return False,'not_reviewed_common_stock_or_adr'
    if record.get('leveraged') is not False:return False,'leveraged_or_unverified_product'
    return True,'admitted'

def daily_eligibility(frames,symbols,day,rules):
    """Use the immediately preceding complete 20 sessions, never today's volume."""
    import exchange_calendars as xcals
    prior_end=(pd.Timestamp(day)-pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    begin=(pd.Timestamp(day)-pd.Timedelta(days=rules.lookback_sessions*3+20)).strftime('%Y-%m-%d')
    calendar=xcals.get_calendar('XNYS',start=begin,end=day)
    expected=[str(d.date()) for d in calendar.sessions if str(d.date())<=prior_end][-rules.lookback_sessions:]
    if len(expected)!=rules.lookback_sessions:raise ValueError('Insufficient calendar history for eligibility')
    result={}
    for s in symbols:
        f=normalize_bars(frames[s]);past=f.loc[f.index.strftime('%Y-%m-%d')<day]
        grouped=past.groupby(past.index.strftime('%Y-%m-%d'))
        available=set(grouped.groups);complete=all(d in available and len(grouped.get_group(d))==78 for d in expected)
        if not complete:
            result[s]=dict(eligible=False,reason='incomplete_prior_sessions',last_price=None,adv=None);continue
        selected=past.loc[past.index.strftime('%Y-%m-%d').isin(expected)]
        adv=float((selected.close*selected.volume).groupby(selected.index.date).sum().mean())
        price=float(selected.close.iloc[-1]);ok=price>=rules.min_price and adv>=rules.min_adv
        result[s]=dict(eligible=ok,reason='admitted' if ok else ('low_price' if price<rules.min_price else 'low_dollar_volume'),
            last_price=price,adv=adv,history_start=expected[0],history_end=expected[-1],sessions=len(expected),
            dollar_volume_method='sum_5min_close_times_volume_proxy')
    return result

def allocate(mu,covariance,current,spec,symbols,eligible):
    """All existing holdings remain in the budget, including newly ineligible ones."""
    symbols=tuple(symbols);n=len(symbols)
    if set(mu)!=set(symbols) or any(v!=0 for s,v in current.items() if s not in symbols):raise ValueError('All current exposure must be budgeted')
    cov=_validated_covariance(covariance,n);expected=np.array([mu[s] for s in symbols]);old=np.array([current.get(s,0.) for s in symbols])
    if not np.isfinite(expected).all() or not np.isfinite(old).all():raise ValueError('Nonfinite forecasts or holdings')
    limits=np.array([spec.symbol_limit if eligible.get(s,False) else 0. for s in symbols])
    eye=np.eye(n);zero=np.zeros((n,n));cost=np.full(n,spec.cost_bps/10000)
    a=np.vstack([np.hstack([-eye,eye,zero]),np.hstack([eye,eye,zero]),np.hstack([-eye,zero,eye]),np.hstack([eye,zero,eye]),np.r_[np.zeros(2*n),-np.ones(n)][None,:]])
    lower=np.r_[-old,old,np.zeros(2*n),-spec.gross_limit]
    bounds=Bounds(np.r_[-limits,np.zeros(2*n)],np.r_[limits,np.full(2*n,np.inf)])
    scale=max(abs(expected).max(),spec.risk_aversion*abs(cov).max(),cost.max(),np.finfo(float).eps)
    p=sparse.block_diag([spec.risk_aversion*cov/scale,sparse.csc_matrix((2*n,2*n))],format='csc')
    q=np.r_[-expected,cost,np.zeros(n)]/scale
    matrix=sparse.vstack([sparse.csc_matrix(a),sparse.eye(3*n)],format='csc')
    lo=np.r_[lower,bounds.lb];hi=np.r_[np.full(len(lower),np.inf),bounds.ub]
    initial=np.clip(old,-limits,limits)
    if abs(initial).sum()>spec.gross_limit:initial*=spec.gross_limit/abs(initial).sum()
    x0=np.r_[initial,abs(initial-old),abs(initial)]
    qp=osqp.OSQP();qp.setup(P=sparse.triu(p,format='csc'),q=q,A=matrix,l=lo,u=hi,verbose=False,eps_abs=1e-8,eps_rel=1e-8,max_iter=100000,polishing=True)
    qp.warm_start(x=x0);solution=qp.solve(raise_error=False);solver='osqp'
    if solution.info.status=='solved':x=solution.x
    else:
        solver='slsqp_retry_same_objective'
        result=minimize(lambda v:float(.5*v@p@v+q@v),x0,jac=lambda v:p@v+q,method='SLSQP',bounds=bounds,
            constraints=[LinearConstraint(a,lower,np.full(len(lower),np.inf))],options=dict(maxiter=1000,ftol=1e-11))
        if not result.success:raise RuntimeError(f'Liquid portfolio solver failed: {result.message}')
        x=result.x
    if not np.isfinite(x).all() or max(np.max(lo-matrix@x),np.max(matrix@x-hi))>1e-6:raise ValueError('Infeasible portfolio solution')
    w=np.clip(x[:n],-limits,limits);w[abs(w)<1e-10]=0
    if abs(w).sum()>spec.gross_limit:w*=spec.gross_limit/abs(w).sum()
    gradient=spec.risk_aversion*cov@w
    return dict(zip(symbols,map(float,w))),dict(solver=solver,forecast=mu,
        marginal_risk=dict(zip(symbols,map(float,gradient))),estimated_turnover_cost=float(cost@abs(w-old)),
        forecast_portfolio_return=float(expected@w),forecast_variance=float(w@cov@w))

class CommonStockRuntime(ResearchRuntime):
    def symbols(self,c):
        return FOUR if c.universe=='four' else tuple(sorted(set(self.frames)-set(RISK_REFERENCES)))


class LiquidRuntime:
    """Same engine for research replay and future paper decisions."""
    def __init__(self,frames,rules=LiquidityRules(),instruments=None,*,research_membership=False):
        self.frames=frames;self.rules=rules;self.base=CommonStockRuntime(frames)
        self.instruments=instruments or {};self.research_membership=research_membership
        self.normalized={s:normalize_bars(f) for s,f in frames.items()}
        self.daily={};self.contexts={};self.calibrations={};self.reference_risks={}
        self.broad=tuple(sorted(set(frames)-set(RISK_REFERENCES)))
        self.returns=pd.DataFrame({s:f.close.groupby(f.index.date).pct_change(fill_method=None) for s,f in self.normalized.items()})
        self.returns=self.returns.where(self.returns.index.to_series().diff().eq(pd.Timedelta(minutes=5)),axis=0)

    def symbols(self,c):return FOUR if c.universe=='four' else self.broad

    def context(self,c,day,index,model='tree'):
        symbols=self.symbols(c);key=(symbols,day,tuple(index),model)
        if key not in self.contexts:
            # Reference ETFs provide inputs, never enter the common-stock trading universe.
            ext=Extension('liquid_base',universe=c.universe,model=model)
            self.contexts[key]=self.base.prepare(ext,day,index)
        return self.contexts[key]

    def calibrate(self,c,day):
        symbols=self.symbols(c);key=(symbols,day)
        if key in self.calibrations:return self.calibrations[key]
        dates=sorted({str(d) for d in self.frames[symbols[0]].index.date if str(d)<day})[-5:]
        if len(dates)<5:raise ValueError('Five prior validation sessions required')
        xs=[];ys=[];errors=[];training=[]
        for d in dates:
            index=self.frames[symbols[0]].loc[self.frames[symbols[0]].index.strftime('%Y-%m-%d')==d].index
            tree=self.context(c,d,index);ridge=self.context(c,d,index,'ridge')
            x=np.stack([np.array([tree['predictions'][s] for s in symbols]).T,np.array([ridge['predictions'][s] for s in symbols]).T],axis=-1)
            y=np.column_stack([self.base.label(s,1).reindex(index).to_numpy() for s in symbols])
            valid=np.isfinite(y)&np.isfinite(x).all(axis=-1)
            xs.append(x[valid]);ys.append(y[valid]);errors.append((x,y,valid))
            training.append(dict(validation_day=d,training_last_session=max(t['last_train'] for t in tree['training'])))
        coef=nnls(np.concatenate(xs),np.concatenate(ys))[0]
        if coef.sum()>1:coef/=coef.sum() # convex blend plus zero-return prior; cannot amplify gross forecasts
        residual=[]
        for x,y,valid in errors:
            e=y-x@coef;e[~valid]=np.nan;residual.append(e)
        e=np.concatenate(residual);e=e[np.isfinite(e).all(axis=1)]
        # Session count acknowledges dependence within bars; approximate error risk, not a win probability.
        risk=LedoitWolf().fit(e).covariance_/len(dates)
        result=dict(coef=coef,error_risk=risk,validation_dates=dates,folds=training,calibration_rows=len(np.concatenate(ys)))
        self.calibrations[key]=result;return result

    def prepare(self,c,day,index):
        symbols=self.symbols(c);key=(symbols,day)
        if key not in self.daily:
            self.daily[key]=daily_eligibility(self.frames,symbols,day,self.rules)
            for s,row in self.daily[key].items():
                record=self.instruments.get(s,{})
                asof=record.get('known_at') if self.research_membership and record else pd.Timestamp(f'{day} 09:25',tz='America/New_York')
                admitted,reason=instrument_admission(record,asof)
                cap=record.get('market_cap');size_ok=isinstance(cap,(int,float)) and np.isfinite(cap) and cap>0 and cap>=self.rules.min_market_cap
                row.update(instrument_admitted=admitted,market_cap=cap,metadata_known_at=record.get('known_at'),
                    membership_basis='contemporary_selected_panel_not_historical_proof' if self.research_membership else 'known_at_decision')
                if not admitted:row.update(eligible=False,reason=reason)
                elif not size_ok:row.update(eligible=False,reason='small_or_unknown_market_cap')
        if c.benchmark:return dict(symbols=symbols,eligibility=self.daily[key],index=index)
        context=self.context(c,day,index);mu=context['predictions'];calibration=None
        if c.calibration:
            calibration=self.calibrate(c,day);ridge=self.context(c,day,index,'ridge')
            mu={s:calibration['coef'][0]*mu[s]+calibration['coef'][1]*ridge['predictions'][s] for s in symbols}
        return dict(symbols=symbols,eligibility=self.daily[key],index=index,mu=mu,covariance=context['covariance'],training=context['training'],calibration=calibration)

    def target(self,c,context,i,current,cost=5):
        symbols=context['symbols'];stamp=context['index'][i]
        spec=ResearchSpec(c.name,cost_bps=cost,symbol_limit=c.symbol_limit)
        if c.control:
            return self.base.target(dict(symbols=symbols,selected=symbols,index=context['index'],covariance=context['covariance'],predictions=context['mu'],beta=None),i,current,spec),dict(control=True)
        eligible={s:context['eligibility'][s]['eligible'] and float(self.normalized[s].loc[stamp,'close'])>=self.rules.min_price for s in symbols}
        mu={s:float(context['mu'][s][i]) for s in symbols};cov=context['covariance'].copy()
        if c.integrated_risk:
            today=self.returns.loc[(self.returns.index.date==stamp.date())&(self.returns.index<=stamp),list(symbols)].dropna()
            if len(today)>=2:
                fraction=len(today)/(5*77+len(today));cov=(1-fraction)*cov+fraction*LedoitWolf().fit(today).covariance_
            key=(symbols,str(stamp.date()))
            if key not in self.reference_risks:
                refs=tuple(sorted({REFERENCE_MAP.get(s,'SPY') for s in symbols}))
                prior=self.returns.loc[self.returns.index.date<stamp.date(),list(dict.fromkeys((*symbols,*refs)))].dropna()
                b=np.zeros((len(symbols),len(refs)))
                for j,s in enumerate(symbols):
                    ref=REFERENCE_MAP.get(s,'SPY');variance=prior[ref].var();b[j,refs.index(ref)]=prior[s].cov(prior[ref])/variance if variance>0 else 0
                self.reference_risks[key]=b@prior[list(refs)].cov().to_numpy()@b.T
            cov+=self.reference_risks[key]+context['calibration']['error_risk']
        weights,explanation=allocate(mu,cov,current,spec,symbols,eligible)
        explanation['eligible']=eligible
        return weights,explanation
