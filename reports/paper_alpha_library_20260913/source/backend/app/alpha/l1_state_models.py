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
    if cutoff.tzinfo is None: raise ValueError("Training cutoff must be timezone-aware")
    return cutoff


def _contract(q):
    return {k:q.attrs[k] for k in ("symbol","feed","clock","max_gap")}


class QueueImbalanceModel:
    def fit(self,events,*,before,C=1.0,max_gap="30s"):
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
                           interpretation="probability_next_mid_move_up_not_trade_win_rate")
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
    def fit(self,events,*,before,tick_size=.01,imbalance_bins=5,spread_ticks=(1,2,3,4,5),
            price_changes=6,symmetrize=True,max_gap="30s"):
        if not np.isfinite(tick_size) or tick_size<=0 or type(imbalance_bins) is not int or imbalance_bins<2:
            raise ValueError("Positive tick size and integer imbalance_bins >= 2 required")
        if type(price_changes) is not int or price_changes<1 or not spread_ticks or any(type(s) is not int or s<1 for s in spread_ticks):
            raise ValueError("Explicit spread states and expansion count required")
        self.artifact=dict(schema_version=1,model="transition_microprice",feature_version=VERSION,
                           tick_size=tick_size,imbalance_bins=imbalance_bins,spread_ticks=list(spread_ticks),
                           price_changes=price_changes,symmetrize=symmetrize,trained_before=_cutoff(before).isoformat())
        q=quote_states(events,as_of=_cutoff(before),max_gap=max_gap)
        self.artifact["contract"]=_contract(q)
        states=self._states(q);records=[]
        for i in range(len(q)-1):
            a,b=states[i],states[i+1]
            if a is None or b is None or q.segment.iloc[i]!=q.segment.iloc[i+1]: continue
            delta=float(q.mid.iloc[i+1]-q.mid.iloc[i])
            records.append((a,b,delta))
            if symmetrize:
                records.append(((a[0],imbalance_bins-1-a[1]),(b[0],imbalance_bins-1-b[1]),-delta))
        if not records: raise ValueError("No observed microprice state transitions")
        active=sorted({x for a,b,_ in records for x in (a,b)});lookup={s:i for i,s in enumerate(active)}
        n=len(active);Q=np.zeros((n,n));R=np.zeros((n,n));g=np.zeros(n);count=np.zeros(n)
        for a,b,delta in records:
            i,j=lookup[a],lookup[b];count[i]+=1
            if abs(delta)<1e-10: Q[i,j]+=1
            else: R[i,j]+=1;g[i]+=delta
        if (count==0).any(): raise ValueError("State has no observed outgoing transitions; collect more quotes")
        Q/=count[:,None];R/=count[:,None];g/=count
        spectral_radius=float(np.max(np.abs(np.linalg.eigvals(Q))))
        if spectral_radius>=1-1e-10: raise ValueError("Non-absorbing no-move states; microprice is not identified")
        A=np.eye(n)-Q
        first=np.linalg.solve(A,g);B=np.linalg.solve(A,R)
        correction=first.copy();increment=first.copy()
        for _ in range(1,price_changes): increment=B@increment;correction+=increment
        if not np.isfinite(correction).all(): raise ValueError("Nonfinite transition correction")
        self.artifact.update(states=[list(s) for s in active],state_counts=count.tolist(),Q=Q.tolist(),R=R.tolist(),
                             immediate_reward=g.tolist(),first_move_correction=first.tolist(),B=B.tolist(),
                             correction=correction.tolist(),last_increment=increment.tolist(),
                             no_move_spectral_radius=spectral_radius,rows=len(q),transitions=len(records),
                             supported_quotes=sum(s is not None for s in states),
                             finite_expansion=True,interpretation="estimated_mid_after_finite_price_changes_not_fair_value_or_profit")
        return self

    def _states(self,q):
        a=self.artifact;n=a["imbalance_bins"];tick=a["tick_size"]
        ticks=q.spread.to_numpy()/tick;bucket=np.minimum(n-1,np.floor((q.qi.to_numpy()+1)*.5*n).astype(int))
        return [(int(round(s)),int(b)) if np.isclose(s,round(s),atol=1e-6,rtol=0) and int(round(s)) in a["spread_ticks"] else None for s,b in zip(ticks,bucket)]

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
