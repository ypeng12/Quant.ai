"""Train-only QI logistic and empirical Stoikov state-transition microprice.

Independent implementation of Q/R/g transition equations (author reference:
https://github.com/sstoikov/microprice). The finite price-change expansion is
explicit; it is not an assertion that an infinite series converges.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from .paper_l1_alpha import quote_states, next_move_labels, VERSION


def _cutoff(before):
    cutoff=pd.Timestamp(before)
    if pd.isna(cutoff) or cutoff.tzinfo is None: raise ValueError("Training cutoff must be timezone-aware")
    return cutoff


def _contract(q):
    return {k:q.attrs[k] for k in ("symbol","feed","source","clock","max_gap","quote_size_unit")}


class QueueImbalanceModel:
    def fit(self,events,*,before,C=1.0,max_gap="30s"):
        if not np.isfinite(C) or C <= 0:
            raise ValueError("Positive logistic regularization C required")
        q=quote_states(events,as_of=_cutoff(before),max_gap=max_gap)
        labels=next_move_labels(q);mask=labels.target.notna()
        if labels.target[mask].nunique()!=2: raise ValueError("QI needs both observed next-move directions")
        # Equal weight per next-price-change event reduces quote-burst dominance.
        counts=labels.loc[mask].groupby("label_end").target.transform("size")
        weights=1/counts.to_numpy();weights*=len(weights)/weights.sum()
        model=LogisticRegression(C=C,solver="lbfgs").fit(q.loc[mask,["qi"]],labels.target[mask],sample_weight=weights)
        self.artifact=dict(schema_version=1,model="qi_logistic",feature_version=VERSION,contract=_contract(q),
                           trained_before=_cutoff(before).isoformat(),rows=int(mask.sum()),
                           next_move_events=int(labels.label_end[mask].nunique()),regularization_C=C,
                           coefficient=float(model.coef_[0,0]),intercept=float(model.intercept_[0]),
                           last_label_end=labels.label_end[mask].max().isoformat(),
                           deployment="research_only", performance_verified=False,
                           target_feed=q.attrs["feed"],target=f"next_{q.attrs['feed']}_mid_move_up",
                           interpretation="probability_next_feed_mid_move_up_not_trade_win_rate")
        return self

    def predict(self,events,*,as_of=None):
        q=quote_states(events,as_of=as_of,max_gap=self.artifact["contract"]["max_gap"])
        if _contract(q)!=self.artifact["contract"]: raise ValueError("QI source/clock/symbol contract changed")
        z=q.qi*self.artifact["coefficient"]+self.artifact["intercept"]
        p=1/(1+np.exp(-np.clip(z,-700,700)))
        return p.where(q.index>=pd.Timestamp(self.artifact["trained_before"])).rename("qi_next_move_up_probability")

    def save(self,path): Path(path).write_text(json.dumps(self.artifact,indent=2,allow_nan=False)+"\n")

    @classmethod
    def load(cls,path):
        obj=cls();obj.artifact=json.loads(Path(path).read_text())
        if obj.artifact.get("model")!="qi_logistic" or obj.artifact.get("feature_version")!=VERSION:
            raise ValueError("Invalid QI artifact")
        return obj


class TransitionMicroprice:
    def fit(self,events,*,before,tick_size=.01,imbalance_bins=5,spread_ticks=None,
            spread_bins=5,price_changes=6,symmetrize=True,max_gap="30s"):
        if not np.isfinite(tick_size) or tick_size<=0 or type(imbalance_bins) is not int or imbalance_bins<2:
            raise ValueError("Positive tick size and integer imbalance_bins >= 2 required")
        if (type(price_changes) is not int or price_changes<1 or type(spread_bins) is not int or spread_bins<1
                or (spread_ticks is not None and (not spread_ticks or any(type(s) is not int or s<1 for s in spread_ticks)))):
            raise ValueError("Explicit spread states and expansion count required")
        self.artifact=dict(schema_version=1,model="transition_microprice",feature_version=VERSION,
                           tick_size=tick_size,imbalance_bins=imbalance_bins,
                           spread_ticks=None if spread_ticks is None else list(spread_ticks), spread_bins=spread_bins,
                           price_changes=price_changes,symmetrize=symmetrize,trained_before=_cutoff(before).isoformat())
        q=quote_states(events,as_of=_cutoff(before),max_gap=max_gap)
        self.artifact["contract"]=_contract(q)
        if spread_ticks is None:
            # IEX venue spreads need not be 1--5 cents. Quantile boundaries are
            # learned only from this training prefix and remain frozen later.
            ticks=np.round(q.spread.to_numpy()/tick_size,8)
            cuts=np.unique(np.quantile(ticks,np.arange(1,spread_bins)/spread_bins))
            cuts=cuts[(cuts>ticks.min())&(cuts<ticks.max())]
            self.artifact.update(spread_state_kind="training_quantile_bins",
                                 spread_quantile_cuts=cuts.tolist(),
                                 spread_training_range_ticks=[float(ticks.min()),float(ticks.max())])
        else:
            self.artifact["spread_state_kind"]="explicit_exact_ticks"
        # Count adjacent transitions with bounded state matrices; do not create
        # a Python record or perform pandas indexing for every quote pair.
        states=self._state_ids(q)
        pairs=(states[:-1]>=0)&(states[1:]>=0)&(np.diff(q.segment.to_numpy())==0)&(np.diff(q.index.asi8)>0)
        a,b=states[:-1][pairs],states[1:][pairs]
        delta=np.diff(q.mid.to_numpy())[pairs]
        if not len(a): raise ValueError("No observed microprice state transitions")
        if symmetrize:
            mirror_a=a//imbalance_bins*imbalance_bins+imbalance_bins-1-a%imbalance_bins
            mirror_b=b//imbalance_bins*imbalance_bins+imbalance_bins-1-b%imbalance_bins
            a=np.r_[a,mirror_a];b=np.r_[b,mirror_b];delta=np.r_[delta,-delta]
        active=np.union1d(a,b);n=len(active)
        i,j=np.searchsorted(active,a),np.searchsorted(active,b)
        count=np.bincount(i,minlength=n).astype(float)
        no_move=np.abs(delta)<1e-10
        Q=np.bincount((i*n+j)[no_move],minlength=n*n).reshape(n,n).astype(float)
        R=np.bincount((i*n+j)[~no_move],minlength=n*n).reshape(n,n).astype(float)
        g=np.bincount(i[~no_move],weights=delta[~no_move],minlength=n).astype(float)
        if (count==0).any(): raise ValueError("State has no observed outgoing transitions; collect more quotes")
        Q/=count[:,None];R/=count[:,None];g/=count
        spectral_radius=float(np.max(np.abs(np.linalg.eigvals(Q))))
        if spectral_radius>=1-1e-10: raise ValueError("Non-absorbing no-move states; microprice is not identified")
        A=np.eye(n)-Q
        first=np.linalg.solve(A,g);B=np.linalg.solve(A,R)
        correction=first.copy();increment=first.copy()
        for _ in range(1,price_changes): increment=B@increment;correction+=increment
        if not np.isfinite(correction).all(): raise ValueError("Nonfinite transition correction")
        self.artifact.update(states=[[int(s//imbalance_bins),int(s%imbalance_bins)] for s in active],state_counts=count.tolist(),Q=Q.tolist(),R=R.tolist(),
                             immediate_reward=g.tolist(),first_move_correction=first.tolist(),B=B.tolist(),
                             correction=correction.tolist(),last_increment=increment.tolist(),
                             no_move_spectral_radius=spectral_radius,rows=len(q),transitions=len(a),
                             supported_quotes=int((states>=0).sum()),
                             finite_expansion=True,deployment="research_only",performance_verified=False,
                             last_label_end=q.index[-1].isoformat(),
                             target_feed=q.attrs["feed"],target=f"future_{q.attrs['feed']}_mid_after_finite_price_changes",
                             interpretation="estimated_venue_mid_after_finite_price_changes_not_nbbo_fair_value_or_executable_profit")
        return self

    def _state_ids(self,q):
        a=self.artifact;n=a["imbalance_bins"];tick=a["tick_size"]
        ticks=q.spread.to_numpy()/tick;bucket=np.minimum(n-1,np.floor((q.qi.to_numpy()+1)*.5*n).astype(int))
        if a["spread_state_kind"]=="training_quantile_bins":
            ticks=np.round(ticks,8)
            lower,upper=a["spread_training_range_ticks"]
            spread_state=np.searchsorted(a["spread_quantile_cuts"],ticks,side="right")
            return np.where((ticks>=lower)&(ticks<=upper),spread_state*n+bucket,-1)
        rounded=np.rint(ticks)
        supported=np.isclose(ticks,rounded,atol=1e-6,rtol=0)&np.isin(rounded,a["spread_ticks"])
        return np.where(supported,rounded.astype(np.int64)*n+bucket,-1)

    def _states(self,q):
        n=self.artifact["imbalance_bins"]
        return [(int(s//n),int(s%n)) if s>=0 else None for s in self._state_ids(q)]

    def predict(self,events,*,as_of=None):
        q=quote_states(events,as_of=as_of,max_gap=self.artifact["contract"]["max_gap"])
        if _contract(q)!=self.artifact["contract"]: raise ValueError("Microprice source/clock/symbol contract changed")
        correction=dict(zip(map(tuple,self.artifact["states"]),self.artifact["correction"]))
        values=np.array([correction.get(s,np.nan) for s in self._states(q)])
        out=pd.DataFrame({"mid":q.mid,"weighted_mid":q.weighted_mid,"transition_microprice":q.mid+values,
                          "transition_correction_bps":values/q.mid*10000},index=q.index)
        out.loc[out.index<pd.Timestamp(self.artifact["trained_before"]),["transition_microprice","transition_correction_bps"]]=np.nan
        return out

    def save(self,path): Path(path).write_text(json.dumps(self.artifact,indent=2,allow_nan=False)+"\n")

    @classmethod
    def load(cls,path):
        obj=cls();obj.artifact=json.loads(Path(path).read_text())
        if obj.artifact.get("model")!="transition_microprice" or obj.artifact.get("feature_version")!=VERSION:
            raise ValueError("Invalid microprice artifact")
        return obj
