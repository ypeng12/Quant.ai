"""Predeclared research candidates, shared by replay and future paper decisions.

No broker imports or orders. Hyperparameters are explicit experiment choices,
not claims of institutional optimality. Predictions are gross signed returns.
"""
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.tree import DecisionTreeRegressor
from .platform import features_for_panel
from ..quant_policy import normalize_bars, labeled_frame, target_weights, horizon_fraction

FOUR = ('SNDK', 'TSLA', 'MSTR', 'NVDA')
REFERENCES = ('SPY', 'QQQ', 'IWM', 'XLK', 'SOXX', 'XLF', 'IBIT')
SECTOR_REFERENCE = {
    **dict.fromkeys(('NVDA','AMD','AVGO','MU','SNDK','SMCI','INTC','TSM'), 'SOXX'),
    **dict.fromkeys(('AAPL','MSFT','ORCL','PLTR','CRM'), 'XLK'),
    **dict.fromkeys(('JPM','HOOD'), 'XLF'),
    **dict.fromkeys(('COIN','MSTR','MARA'), 'IBIT'),
}

@dataclass(frozen=True)
class ResearchSpec:
    name: str
    horizon_bars: int = 1
    cost_bps: float = 5.
    risk_aversion: float = 50.
    gross_limit: float = .95
    symbol_limit: float = .7
    feature_set: str = 'price_volume'
    ridge_alpha: float = 10.

    def __post_init__(self):
        if self.horizon_bars not in (1,3,6,12): raise ValueError('Research horizons: 1/3/6/12 five-minute bars')
        if not all(np.isfinite(x) for x in (self.cost_bps,self.risk_aversion,self.gross_limit,self.symbol_limit)):
            raise ValueError('Nonfinite research setting')
        if self.cost_bps < 0 or self.risk_aversion <= 0 or not 0 < self.symbol_limit <= self.gross_limit <= 1:
            raise ValueError('Invalid research setting')

@dataclass(frozen=True)
class Extension:
    name: str
    universe: str = 'four'
    model: str = 'tree'
    horizon: int = 1
    pooled: bool = False
    family: str = 'context'
    selector: str = 'all'
    omit: str = ''
    pair: tuple = ()
    reference_risk: bool = False
    volatility_scaled: bool = False

# Registered before replay, not extended in response to evaluation profits.
EXTENSIONS = (
    Extension('four_tree_h1'),
    Extension('four_price_ridge_h1',model='ridge',family='price_volume'),
    Extension('four_equal',model='equal'),
    *(Extension(f'four_tree_h{h}',horizon=h) for h in (3,6,12)),
    Extension('four_tree_no_wicks_h3',horizon=3,family='no_wicks'),
    *(Extension(f'four_pooled_{m}_h3',model=m,horizon=3,pooled=True) for m in ('ridge','tree','lightgbm')),
    *(Extension(f'four_tree_without_{s}',omit=s) for s in FOUR),
    Extension('broad_equal',universe='broad',model='equal'),
    Extension('broad_tree_h3',universe='broad',horizon=3),
    Extension('broad_pooled_tree_h3',universe='broad',horizon=3,pooled=True),
    Extension('broad_pooled_ridge_h3',universe='broad',model='ridge',horizon=3,pooled=True),
    Extension('broad_pooled_tree_scaled_h3',universe='broad',horizon=3,pooled=True,volatility_scaled=True),
    Extension('active8_tree_h3',universe='broad',horizon=3,selector='opening_activity'),
    Extension('active8_pooled_tree_h3',universe='broad',horizon=3,pooled=True,selector='opening_activity'),
    Extension('active8_pooled_ridge_h3',universe='broad',model='ridge',horizon=3,pooled=True,selector='opening_activity'),
    Extension('sector_pooled_ridge_h3',universe='broad',model='ridge',horizon=3,pooled=True,family='sector'),
    Extension('sector_risk_pooled_ridge_h3',universe='broad',model='ridge',horizon=3,pooled=True,family='sector',reference_risk=True),
    *(Extension(f'pair_{a}_{b}_h3',universe='pair',model='pair',horizon=3,pair=(a,b)) for a,b in [('NVDA','AMD'),('NVDA','TSM'),('MSTR','IBIT')]),
)


def feature_panel(frames, family):
    if family == 'price_volume': return features_for_panel(frames, family)
    base = features_for_panel(frames, 'context')
    if family == 'no_wicks':
        return {s:f.drop(columns=['body_fraction','upper_wick_fraction','lower_wick_fraction','close_location']) for s,f in base.items()}
    if family == 'sector':
        for s,f in base.items():
            reference = SECTOR_REFERENCE.get(s,'SPY')
            if reference not in base: raise ValueError(f'Missing reference {reference}')
            other = base[reference].return_1.reindex(f.index)
            own = f.return_1
            beta = own.expanding(min_periods=2).cov(other).shift() / other.expanding(min_periods=2).var().shift().replace(0,np.nan)
            f['reference_return_1'] = other
            f['reference_residual_1'] = own - beta * other
    return base


def mature_fit(features, labels, before, estimator='tree'):
    """Same preprocessing as the original control, with no invented uncertainty."""
    if not features.index.equals(labels.index): raise ValueError('Training labels misaligned')
    mask = (features.index.strftime('%Y-%m-%d') < before) & labels.notna().to_numpy()
    x = features.iloc[np.flatnonzero(mask)]
    y = labels.iloc[np.flatnonzero(mask)].to_numpy()
    if len(x)<2: raise ValueError('Insufficient mature prior-session labels')
    mean = x.mean().fillna(0).to_numpy()
    values = np.where(np.isfinite(x.to_numpy()), x.to_numpy(), mean)
    scale = values.std(axis=0);scale[scale==0]=1
    z = (values-mean)/scale
    if estimator=='tree': model=DecisionTreeRegressor(max_depth=3,min_samples_leaf=40,random_state=42)
    elif estimator=='ridge': model=Ridge(alpha=10,solver='svd')
    elif estimator=='lightgbm':
        from lightgbm import LGBMRegressor
        model=LGBMRegressor(n_estimators=60,max_depth=3,num_leaves=7,min_child_samples=40,learning_rate=.03,n_jobs=1,verbosity=-1,random_state=42)
    else: raise ValueError('Unknown estimator')
    model.fit(z,y)
    return dict(model=model,mean=mean,scale=scale,names=tuple(x.columns),rows=len(x),last_train=str(x.index.max().date()),
                sessions=len(set(x.index.date)))


def predict(fitted, features):
    if tuple(features.columns)!=fitted['names']: raise ValueError('Prediction feature schema differs from training')
    values=features.to_numpy();values=np.where(np.isfinite(values),values,fitted['mean'])
    return fitted['model'].predict((values-fitted['mean'])/fitted['scale'])


def opening_activity(features, symbols, day, count=8):
    """Choose once at 09:35 using only the first completed RTH bar.

    Equal ranks of absolute opening gap and opening volume relative to earlier
    sessions; count is an explicit research capacity, not an entry-score veto.
    """
    stamp=pd.Timestamp(f'{day} 09:30',tz='America/New_York')
    rows={s:{'gap':abs(float(features[s].loc[stamp,'overnight_gap'])),
             'relative_volume':float(features[s].loc[stamp,'seasonal_volume'])} for s in symbols}
    table=pd.DataFrame.from_dict(rows,orient='index')
    if not np.isfinite(table.to_numpy()).all():raise ValueError('Opening selection needs actual first bar and prior opening-volume history')
    table['score']=table.rank(pct=True).mean(axis=1)
    ranked=table.sort_index().sort_values('score',ascending=False,kind='stable')
    return tuple(ranked.index[:count]), dict(available_at=(stamp+pd.Timedelta(minutes=5)).isoformat(),
        method='equal_percentile_ranks_absolute_gap_and_opening_volume',capacity=count,scores=ranked.to_dict(orient='index'))


def horizon_covariance(frames,before,symbols,horizon):
    from sklearn.covariance import LedoitWolf
    if horizon==1:
        from .platform import joint_risk
        return joint_risk(frames,before,symbols)[0]
    labels={s:labeled_frame(frames[s],ResearchSpec('risk',horizon_bars=horizon))[1] for s in symbols}
    aligned=pd.DataFrame(labels)
    aligned=aligned.loc[aligned.index.strftime('%Y-%m-%d')<before].dropna()
    if len(aligned)<2:raise ValueError('Insufficient prior horizon returns')
    return LedoitWolf().fit(aligned.to_numpy()).covariance_


def reference_covariance(frames,before,symbols,horizon):
    """Estimated shared-reference exposure penalty; classifications are declared."""
    refs=tuple(sorted({SECTOR_REFERENCE.get(s,'SPY') for s in symbols}))
    returns={s:labeled_frame(frames[s],ResearchSpec('ref',horizon_bars=horizon))[1] for s in (*symbols,*refs)}
    table=pd.DataFrame(returns);table=table.loc[table.index.strftime('%Y-%m-%d')<before].dropna()
    b=np.zeros((len(symbols),len(refs)))
    for i,s in enumerate(symbols):
        reference=SECTOR_REFERENCE.get(s,'SPY');variance=table[reference].var()
        b[i,refs.index(reference)]=table[s].cov(table[reference])/variance if variance>0 else 0
    c=table[list(refs)].cov().to_numpy()
    return b@c@b.T


class PairForecast:
    """Past-fitted log-price hedge plus learned forward spread return.

    A relative-value hypothesis, not NAV arbitrage or a promise of reversion.
    """
    def fit(self, frames, symbols, before, horizon):
        self.symbols=tuple(symbols)
        a,b=(normalize_bars(frames[s]) for s in symbols)
        logs=pd.DataFrame({'a':np.log(a.close),'b':np.log(b.close)}).dropna()
        train=logs.loc[logs.index.strftime('%Y-%m-%d')<before]
        design=np.column_stack([np.ones(len(train)),train.b])
        self.intercept,self.beta=np.linalg.lstsq(design,train.a,rcond=None)[0]
        f=self.features(logs)
        spec=ResearchSpec('pair',horizon_bars=horizon)
        y=labeled_frame(a,spec)[1]-self.beta*labeled_frame(b,spec)[1]
        self.fitted=mature_fit(f,y.reindex(f.index),before,'ridge')
        self.all_features=f
        self.metadata=dict(beta=float(self.beta),intercept=float(self.intercept),last_train=self.fitted['last_train'],rows=self.fitted['rows'])
        return self

    def features(self, logs):
        spread=logs.a-self.intercept-self.beta*logs.b
        f=pd.DataFrame({'spread':spread})
        for h in (1,3):
            f[f'spread_change_{h}']=spread.groupby(spread.index.date).diff(h)
            continuous=spread.index.to_series().diff(h).eq(pd.Timedelta(minutes=5*h))
            f[f'spread_change_{h}']=f[f'spread_change_{h}'].where(continuous)
        return f

    def predict(self,index):return predict(self.fitted,self.all_features.reindex(index))


def pair_target(mu,beta,covariance,current,spec,symbols):
    """Exact scalar convex allocation w=(q,-beta*q), including both legs' costs."""
    direction=np.array([1.,-beta]);old=np.array([current.get(s,0.) for s in symbols])
    cap=min(spec.gross_limit/abs(direction).sum(),*(spec.symbol_limit/abs(v) for v in direction if abs(v)>0))
    curvature=spec.risk_aversion*float(direction@covariance@direction)
    if curvature<=0 or not np.isfinite(curvature):raise ValueError('Pair variance must be positive')
    breaks=sorted({-cap,cap,*[float(np.clip(old[i]/v,-cap,cap)) for i,v in enumerate(direction) if abs(v)>0]})
    choices=list(breaks)
    cost=spec.cost_bps/10000
    for low,high in zip(breaks[:-1],breaks[1:]):
        middle=(low+high)/2
        slope=cost*np.sum(direction*np.sign(direction*middle-old))
        choices.append(float(np.clip((mu-slope)/curvature,low,high)))
    def objective(q):return -mu*q+curvature*q*q/2+cost*np.abs(q*direction-old).sum()
    q=min(choices,key=objective)
    return dict(zip(symbols,q*direction))


class ResearchRuntime:
    """One decision implementation for historical replay and future paper use.

    Input bars must be completed before calling a future decision. Daily models
    only fit earlier sessions; the opening selector only sees the 09:30 bar.
    Caches are scoped to this immutable input snapshot, never to changing files.
    """
    def __init__(self, frames):
        self.frames=frames
        self.features={};self.labels={};self.forecasts={};self.risks={}

    def symbols(self,c):
        if c.universe=='pair':return tuple(c.pair)
        return tuple(s for s in (FOUR if c.universe=='four' else sorted(set(self.frames)-set(REFERENCES))) if s!=c.omit)

    def label(self,s,horizon):
        key=(s,horizon)
        if key not in self.labels:self.labels[key]=labeled_frame(self.frames[s],ResearchSpec('labels',horizon_bars=horizon))[1]
        return self.labels[key]

    def covariance(self,symbols,horizon,day,reference_risk=False):
        # Reuse identical full-panel labels; the dated mask is applied on every
        # fit. This avoids rebuilding 34 sessions of labels for each test day.
        if horizon==1:
            cov=horizon_covariance(self.frames,day,symbols,horizon)
            return cov+reference_covariance(self.frames,day,symbols,horizon) if reference_risk else cov
        from sklearn.covariance import LedoitWolf
        refs=tuple(sorted({SECTOR_REFERENCE.get(s,'SPY') for s in symbols})) if reference_risk else ()
        table=pd.DataFrame({s:self.label(s,horizon) for s in (*symbols,*refs)})
        table=table.loc[table.index.strftime('%Y-%m-%d')<day].dropna()
        cov=LedoitWolf().fit(table[list(symbols)].to_numpy()).covariance_
        if refs:
            b=np.zeros((len(symbols),len(refs)))
            for i,s in enumerate(symbols):
                ref=SECTOR_REFERENCE.get(s,'SPY');variance=table[ref].var()
                b[i,refs.index(ref)]=table[s].cov(table[ref])/variance if variance>0 else 0
            cov=cov+b@table[list(refs)].cov().to_numpy()@b.T
        return cov

    def prepare(self,c,day,index):
        symbols=self.symbols(c)
        scope=FOUR if c.universe=='four' else tuple(self.frames)
        panel={s:self.frames[s] for s in scope}
        key=(scope,c.family)
        if c.model!='pair' and key not in self.features:self.features[key]=feature_panel(panel,c.family)
        f=self.features.get(key)
        selected=symbols;selection=None
        if c.selector=='opening_activity':selected,selection=opening_activity(f,symbols,day)
        risk_key=(symbols,c.horizon,day,c.reference_risk)
        if risk_key not in self.risks:
            cov=self.covariance(symbols,c.horizon,day,c.reference_risk)
            self.risks[risk_key]=cov
        cov=self.risks[risk_key]
        model_key=(scope,symbols,c.model,c.family,c.horizon,c.pooled,c.volatility_scaled,day,tuple(index))
        if model_key not in self.forecasts:
            metadata=[]
            if c.model=='pair':
                model=PairForecast().fit(self.frames,symbols,day,c.horizon)
                predictions={'spread':model.predict(index)};metadata=[model.metadata]
                beta=float(model.beta)
            else:
                ys={};scales={}
                for s in symbols:
                    ys[s]=self.label(s,c.horizon)
                    if c.volatility_scaled:
                        scales[s]=f[s].return_1.expanding(min_periods=2).std().shift()*np.sqrt(c.horizon)
                        ys[s]=ys[s]/scales[s].replace(0,np.nan)
                predictions={};beta=None
                if c.pooled:
                    model=mature_fit(pd.concat([f[s] for s in symbols]),pd.concat([ys[s] for s in symbols]),day,c.model)
                    metadata=[{k:v for k,v in model.items() if k in ('rows','last_train','sessions','names')}]
                    for s in symbols:predictions[s]=predict(model,f[s].reindex(index))
                else:
                    for s in symbols:
                        model=mature_fit(f[s],ys[s],day,c.model)
                        metadata.append(dict(symbol=s,**{k:v for k,v in model.items() if k in ('rows','last_train','sessions','names')}))
                        predictions[s]=predict(model,f[s].reindex(index))
                if c.volatility_scaled:
                    for s in symbols:predictions[s]=predictions[s]*scales[s].reindex(index).to_numpy()
            if any(not np.isfinite(v[:76]).all() for v in predictions.values()):raise ValueError('Nonfinite executable predictions')
            self.forecasts[model_key]=(predictions,metadata,beta)
        predictions,metadata,beta=self.forecasts[model_key]
        return dict(symbols=symbols,selected=selected,selection=selection,covariance=cov,
                    predictions=predictions,training=metadata,beta=beta,index=index)

    @staticmethod
    def target(context,i,current,spec):
        symbols=context['symbols'];fraction=horizon_fraction(context['index'][i],spec)
        cov=context['covariance']*fraction
        if context['beta'] is not None:
            return pair_target(float(context['predictions']['spread'][i])*fraction,context['beta'],cov,current,spec,symbols)
        selected=context['selected'];positions=[symbols.index(s) for s in selected]
        mu={s:float(context['predictions'][s][i])*fraction for s in selected}
        weights=target_weights(mu,cov[np.ix_(positions,positions)],current,spec,symbols=selected,solver='osqp')
        return {s:weights.get(s,0.) for s in symbols}
