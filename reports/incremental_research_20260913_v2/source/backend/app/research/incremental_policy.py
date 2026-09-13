"""Predeclared feature additions to the frozen conditional Ridge baseline.

Daily slot recurrence adapts a literature hypothesis; gap and range interactions
are project hypotheses. No date/ticker profit overrides or trade vetoes.
"""
import numpy as np
import pandas as pd
from .conditional_policy import ConditionalRuntime
from .stock_policy import StockCandidate, STOCKS
from .strategy_extensions import mature_fit, predict, ResearchSpec
from ..quant_policy import normalize_bars, labeled_frame

INCREMENTAL_CANDIDATES = (
    StockCandidate('incremental_equal', benchmark=True),
    StockCandidate('incremental_control', model='state_ridge'),
    StockCandidate('incremental_slot', model='slot'),
    StockCandidate('incremental_gap', model='gap'),
    StockCandidate('incremental_range', model='range'),
    StockCandidate('incremental_all', model='all'),
)


def incremental_features(frames, baseline):
    output = {family:{} for family in ('slot','gap','range','all')}
    for s in STOCKS:
        b=normalize_bars(frames[s]); base=baseline[s]; g=b.groupby(b.index.date)
        opening=g.open.transform('first'); day=pd.Series(b.index.date,index=b.index)
        # A historical target is known before the next session's same slot.
        # shift(1) is within each wall-clock slot, thus never uses today's target.
        labels=labeled_frame(b,ResearchSpec('slot'))[1]
        slots=b.index.strftime('%H:%M')
        slot=pd.DataFrame(index=b.index)
        for n in (5,20):
            slot[f'prior_{n}_same_slot_mean']=labels.groupby(slots).transform(lambda x:x.shift().rolling(n,min_periods=2).mean())
        slot['prior_20_same_slot_std']=labels.groupby(slots).transform(lambda x:x.shift().rolling(20,min_periods=2).std())
        daily_return=g.close.last()/g.open.first()-1
        prior_day=day.map(daily_return.shift())
        gap=pd.DataFrame(dict(prior_day_return=prior_day,
            gap_x_prior_day=base.overnight_gap*prior_day,
            gap_x_session_return=base.overnight_gap*base.session_return,
            gap_x_elapsed=base.overnight_gap*base.time_fraction),index=b.index)
        high=g.high.transform(lambda x:x.shift().rolling(12,min_periods=1).max())
        low=g.low.transform(lambda x:x.shift().rolling(12,min_periods=1).min())
        returns=base.return_1
        up=returns.clip(lower=0).pow(2).groupby(day).transform(lambda x:x.rolling(12,min_periods=2).mean())
        down=returns.clip(upper=0).pow(2).groupby(day).transform(lambda x:x.rolling(12,min_periods=2).mean())
        ranges=pd.DataFrame(dict(distance_prior_high=(b.close-high)/opening,
            distance_prior_low=(b.close-low)/opening,
            directional_variance=(up-down)/(up+down).replace(0,np.nan)),index=b.index)
        ranges['high_distance_x_volume']=ranges.distance_prior_high*base.volume_state
        ranges['low_distance_x_volume']=ranges.distance_prior_low*base.volume_state
        additions=dict(slot=slot,gap=gap,range=ranges,all=pd.concat([slot,gap,ranges],axis=1))
        for family,extra in additions.items():output[family][s]=base.join(extra).replace([np.inf,-np.inf],np.nan)
    return output


class IncrementalRuntime(ConditionalRuntime):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.extra_x=incremental_features(self.frames,self.state_x);self.extra_models={}

    def context(self,c,day,index,model=None):
        if c.model not in self.extra_x:return super().context(c,day,index,model)
        if c.horizon!=1:raise ValueError('Incremental experiment fixes the five-minute target')
        key=(c.model,day,tuple(index))
        if key not in self.extra_models:
            mu={};training=[]
            for s in STOCKS:
                x=self.extra_x[c.model][s];f=mature_fit(x,self.base.label(s,1),day,'ridge')
                mu[s]=predict(f,x.reindex(index))
                training.append(dict(symbol=s,model=c.model,horizon=1,last_train=f['last_train'],rows=f['rows'],sessions=f['sessions'],names=list(f['names'])))
            self.extra_models[key]=dict(predictions=mu,training=training,covariance=self.base.covariance(STOCKS,1,day))
        return self.extra_models[key]
