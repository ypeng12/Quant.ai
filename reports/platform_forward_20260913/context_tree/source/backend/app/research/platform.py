"""Offline feature/model/portfolio experiments. No broker, network or config imports.

Research estimates are conditional on retained data and an explicit execution
model. Clustered Ridge uncertainty is approximate, not a win probability.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.tree import DecisionTreeRegressor
from sklearn.covariance import LedoitWolf
from ..quant_policy import PolicySpec, normalize_bars, panel_feature_frames, labeled_frame, target_weights
from ..alpha.real_l1_alpha import REAL_L1_FEATURES, build_real_l1_features

@dataclass(frozen=True)
class Candidate:
    name: str
    features: str = 'price_volume'
    model: str = 'ridge'
    portfolio: str = 'joint'

CANDIDATES = (
    Candidate('cash',portfolio='cash'), Candidate('equal_weight',portfolio='equal'),
    Candidate('price_ridge'), Candidate('peer_ridge','price_volume_peer'),
    Candidate('context_ridge','context'), Candidate('context_tree','context','tree'),
    Candidate('context_lightgbm','context','lightgbm'),
    Candidate('context_uncertainty','context','ridge','uncertainty'),
    Candidate('context_common_risk','context','ridge','common'),
    Candidate('context_robust','context','ridge','robust'),
    Candidate('l1_ridge','l1'), Candidate('combined_robust','combined','ridge','robust'),
)


def features_for_panel(frames, family, events=None):
    bars = {s:normalize_bars(f) for s,f in frames.items()}
    if family in ('price_volume','price_volume_peer'):
        return panel_feature_frames(bars, family)
    base = panel_feature_frames(bars,'price_volume_peer')
    for symbol, frame in bars.items():
        result=base[symbol]
        result['time_fraction'] = (frame.index.hour*60+frame.index.minute-570)/390
        prior_close=frame.close.groupby(frame.index.date).last().shift()
        prior_map=pd.Series(frame.index.date,index=frame.index).map(prior_close)
        session_open=frame.open.groupby(frame.index.date).transform('first')
        result['overnight_gap']=session_open/prior_map-1
        # Same wall-clock bucket, earlier sessions only. Not within-day RVOL.
        slots=frame.index.strftime('%H:%M')
        seasonal=frame.volume.groupby(slots).transform(lambda x:x.expanding().mean().shift())
        result['seasonal_volume']=frame.volume/seasonal.replace(0,np.nan)-1
        # Market reference is explicit if present; never relabel peer basket as SPY.
        if 'SPY' in bars and symbol!='SPY':
            market=base['SPY'].return_1.reindex(frame.index)
            own=result.return_1
            pair=pd.concat([own,market],axis=1).dropna()
            # A past-only expanding beta; all observations precede this bar.
            beta=pair.iloc[:,0].expanding(min_periods=2).cov(pair.iloc[:,1]).shift()/pair.iloc[:,1].expanding(min_periods=2).var().shift()
            result['market_residual_1']=own-beta.reindex(frame.index)*market
        if family in ('l1','combined'):
            if not events or symbol not in events or events[symbol].empty:
                raise ValueError(f'Real L1 unavailable for {symbol}')
            book=build_real_l1_features(events[symbol])
            book=book.reindex(frame.index)
            result=book if family=='l1' else result.join(book)
        base[symbol]=result.replace([np.inf,-np.inf],np.nan)
    return base


class FittedForecast:
    def __init__(self, family, estimator, ridge_alpha=10):
        self.family,self.estimator,self.alpha=family,estimator,ridge_alpha

    def fit(self, features, labels, before):
        # Session cutoff purges all intraday labels on/after test day.
        mask=(features.index.strftime('%Y-%m-%d')<before) & labels.notna()
        if self.family in ('l1','combined'):
            mask &= features[list(REAL_L1_FEATURES)].notna().all(axis=1)
        x=features.loc[mask];y=labels.loc[mask]
        if len(x)<2:raise ValueError('Insufficient mature training labels')
        self.names=tuple(x.columns)
        self.mean=x.mean().fillna(0).to_numpy();v=x.to_numpy(dtype=float)
        v=np.where(np.isfinite(v),v,self.mean)
        self.scale=v.std(axis=0);self.scale[self.scale==0]=1
        z=(v-self.mean)/self.scale
        if self.estimator=='ridge':self.model=Ridge(alpha=self.alpha,solver='svd')
        elif self.estimator=='tree':self.model=DecisionTreeRegressor(max_depth=3,min_samples_leaf=40,random_state=42)
        elif self.estimator=='lightgbm':
            from lightgbm import LGBMRegressor
            self.model=LGBMRegressor(n_estimators=60,max_depth=3,num_leaves=7,min_child_samples=40,learning_rate=.03,n_jobs=1,verbosity=-1,random_state=42)
        else:raise ValueError('Unknown model')
        self.model.fit(z,y.to_numpy())
        residual=y.to_numpy()-self.model.predict(z)
        design=np.column_stack([np.ones(len(z)),z]);penalty=np.eye(design.shape[1])*self.alpha;penalty[0,0]=0
        inverse=np.linalg.pinv(design.T@design+penalty)
        # Cluster scores by session to avoid treating all bars as independent.
        scores=pd.DataFrame(design*residual[:,None],index=x.index).groupby(x.index.date).sum().to_numpy()
        self.parameter_cov=inverse@scores.T@scores@inverse
        self.last_train=str(x.index[-1].date()); self.rows=len(x);self.sessions=len(scores)
        return self

    def predict(self, features):
        if tuple(features.columns)!=self.names:raise ValueError('Feature schema changed')
        v=features.to_numpy(dtype=float);z=(np.where(np.isfinite(v),v,self.mean)-self.mean)/self.scale
        pred=self.model.predict(z)
        design=np.column_stack([np.ones(len(z)),z])
        error=np.sqrt(np.maximum(0,np.einsum('ij,jk,ik->i',design,self.parameter_cov,design)))
        if self.family in ('l1','combined'):
            missing=features[list(REAL_L1_FEATURES)].isna().any(axis=1).to_numpy()
            pred[missing]=np.nan;error[missing]=np.nan
        return pred,error


def joint_risk(frames, before, symbols):
    returns={}
    for s in symbols:
        b=normalize_bars(frames[s]);b=b.loc[b.index.strftime('%Y-%m-%d')<before]
        r=b.close.groupby(b.index.date).pct_change(fill_method=None)
        r=r.where(b.index.to_series().diff().eq(pd.Timedelta(minutes=5)))
        returns[s]=r
    aligned=pd.DataFrame(returns).dropna()
    if len(aligned)<2:raise ValueError('Insufficient aligned prior returns')
    covariance=LedoitWolf().fit(aligned.to_numpy()).covariance_
    values,vectors=np.linalg.eigh(covariance)
    # First principal component is a statistical shared factor, not a sector label.
    common=values[-1]*np.outer(vectors[:,-1],vectors[:,-1])
    return covariance,common,vectors[:,-1]


def portfolio_target(mu,errors,current,covariance,common,spec,*,robust=False,uncertainty_aversion=1.,common_risk_aversion=1.):
    symbols=tuple(mu)
    effective=covariance+(common_risk_aversion*common if robust else 0)
    return target_weights(mu,effective,current,spec,symbols=symbols,
                          uncertainty=[errors[s] for s in symbols] if robust else None,
                          uncertainty_aversion=uncertainty_aversion if robust else 0)


def risk_diagnostics(weights,covariance,common,loading):
    w=np.asarray(weights);variance=float(w@covariance@w)
    contribution=w*(covariance@w)
    return dict(variance=variance,common_variance=float(w@common@w),common_exposure=float(w@loading),
                variance_contributions=contribution.tolist(),gross=float(abs(w).sum()),net=float(w.sum()))
