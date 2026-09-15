"""Inspectable Ridge/tree/LightGBM artifacts using the paper feature contract."""
from __future__ import annotations
from dataclasses import asdict
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.tree import DecisionTreeRegressor
from ..alpha.paper_bar_alpha import BarAlphaSpec, bar_alpha_panel, VERSION
from ..quant_policy import PolicySpec, labeled_frame


def feature_contract(features):
    keys=("feature_version","spec","panel_symbols","rank_symbols","peer_groups","timestamp_convention",
          "window_unit","symbol","feed","clock","max_gap","source","market_depth","required_features")
    return json.loads(json.dumps({k:v for k,v in features.attrs.items() if k in keys}))


def combine_bar_l1(features,events,*,as_of=None):
    from ..alpha.paper_l1_alpha import enhanced_l1_features,PAPER_L1_FEATURES
    book=enhanced_l1_features(events,as_of=as_of)
    combined=features.join(book)
    combined.attrs.update(features.attrs)
    combined.attrs.update({k:book.attrs[k] for k in ('symbol','feed','clock','max_gap','source','market_depth') if k in book.attrs})
    combined.attrs.update(required_features=list(PAPER_L1_FEATURES))
    return combined


class PaperForecast:
    def fit(self,features,targets,*,label_end,before,estimator="ridge",parameters=None):
        cutoff=pd.Timestamp(before)
        if cutoff.tzinfo is None: raise ValueError("Timezone-aware training cutoff required")
        if not features.index.equals(targets.index) or not features.index.equals(label_end.index):
            raise ValueError("Targets and maturity timestamps must align exactly")
        params=parameters or {}
        valid=(features.index<cutoff)&label_end.lt(cutoff)&targets.notna()&features.notna().any(axis=1)
        required=features.attrs.get('required_features',[])
        if required: valid &= features[required].notna().all(axis=1)
        x=features.loc[valid].replace([np.inf,-np.inf],np.nan);y=targets.loc[valid]
        names=list(x.columns[x.notna().any()])
        if len(x)<2 or not names: raise ValueError("No mature, observed training samples")
        means=x[names].mean().to_numpy();v=x[names].fillna(dict(zip(names,means))).to_numpy()
        scales=v.std(axis=0);scales[scales==0]=1;z=(v-means)/scales
        if estimator=="ridge":
            model=Ridge(**({"alpha":10.,"solver":"svd"}|params)).fit(z,y)
            state=dict(coefficient=model.coef_.tolist(),intercept=float(model.intercept_))
        elif estimator=="tree":
            model=DecisionTreeRegressor(**({"max_depth":3,"min_samples_leaf":40,"random_state":42}|params)).fit(z,y)
            t=model.tree_
            state=dict(left=t.children_left.tolist(),right=t.children_right.tolist(),feature=t.feature.tolist(),
                       threshold=t.threshold.tolist(),value=t.value[:,0,0].tolist())
        elif estimator=="lightgbm":
            from lightgbm import LGBMRegressor
            model=LGBMRegressor(**({"n_estimators":60,"max_depth":3,"num_leaves":7,"min_child_samples":40,
                                   "learning_rate":.03,"n_jobs":1,"verbosity":-1,"random_state":42}|params)).fit(z,y)
            state=dict(model_string=model.booster_.model_to_string())
        else: raise ValueError("Unknown estimator")
        self.artifact=dict(schema_version=1,kind="paper_forecast",feature_version=VERSION,estimator=estimator,
                           input_features=list(features.columns),features=names,unused_features=[n for n in features if n not in names],
                           mean=means.tolist(),scale=scales.tolist(),state=state,parameters=model.get_params(),
                           trained_before=cutoff.isoformat(),last_label_end=label_end[valid].max().isoformat(),
                           rows=len(x),sessions=len(set(x.index.date)),feature_contract=feature_contract(features),
                           deployment="research_only",performance_verified=False)
        return self

    def predict(self,features):
        a=self.artifact
        if list(features.columns)!=a["input_features"]: raise ValueError("Feature schema changed")
        if feature_contract(features)!=a["feature_contract"]: raise ValueError("Feature source or panel contract changed")
        v=features[a["features"]].to_numpy(dtype=float);valid=np.isfinite(v).any(axis=1)
        required=a['feature_contract'].get('required_features',[])
        if required: valid &= features[required].notna().all(axis=1).to_numpy()
        z=(np.where(np.isfinite(v),v,a["mean"])-a["mean"])/a["scale"]
        state=a["state"]
        if a["estimator"]=="ridge": prediction=z@np.asarray(state["coefficient"])+state["intercept"]
        elif a["estimator"]=="tree":
            prediction=np.empty(len(z))
            for row,values in enumerate(z):
                node=0
                while state["left"][node]!=-1:
                    node=state["left"][node] if values[state["feature"][node]]<=state["threshold"][node] else state["right"][node]
                prediction[row]=state["value"][node]
        else:
            from lightgbm import Booster
            prediction=Booster(model_str=state["model_string"]).predict(z)
        prediction[~valid]=np.nan
        # Training rows are not presented as future predictions.
        prediction[features.index<pd.Timestamp(a["trained_before"])]=np.nan
        return pd.Series(prediction,index=features.index,name="expected_return")

    def forecast(self,frames,*,as_of,events=None):
        """Same builder used by fit_bar_model, suitable for a future live adapter."""
        a=self.artifact;contract=a["feature_contract"]
        if sorted(frames)!=contract["panel_symbols"]: raise ValueError("Model requires its complete declared panel")
        spec=dict(contract["spec"]);spec["windows"]=tuple(spec["windows"])
        panel=bar_alpha_panel(frames,BarAlphaSpec(**spec),as_of=as_of,
                              peers=contract["peer_groups"],rank_symbols=contract["rank_symbols"])
        features=panel[a["symbol"]]
        if a.get('input_kind')=='bar_plus_real_l1':
            if events is None: raise ValueError('Real L1 required by this model')
            features=combine_bar_l1(features,events,as_of=as_of)
        return self.predict(features)

    def save(self,path):
        Path(path).write_text(json.dumps(self.artifact,indent=2,allow_nan=False)+"\n")

    @classmethod
    def load(cls,path):
        obj=cls();obj.artifact=json.loads(Path(path).read_text())
        if obj.artifact.get("kind")!="paper_forecast" or obj.artifact.get("feature_version")!=VERSION:
            raise ValueError("Unsupported paper forecast artifact")
        # Canonical JSON representation makes tuples/lists consistent after loading.
        return obj


def fit_bar_model(frames,symbol,*,before,spec=BarAlphaSpec(),horizon_bars=1,estimator="ridge",parameters=None):
    cutoff=pd.Timestamp(before)
    if cutoff.tzinfo is None: raise ValueError("Timezone-aware cutoff required")
    features=bar_alpha_panel(frames,spec,as_of=cutoff)[symbol]
    policy=PolicySpec("paper_library_training",horizon_bars=horizon_bars)
    _,target=labeled_frame(frames[symbol],policy)
    target=target.reindex(features.index)
    end=pd.Series(features.index+pd.Timedelta(minutes=5*(horizon_bars+1)),index=features.index)
    fitted=PaperForecast().fit(features,target,label_end=end,before=cutoff,estimator=estimator,parameters=parameters)
    fitted.artifact.update(symbol=symbol,horizon_bars=horizon_bars,target="next_open_to_horizon_close_return")
    return fitted


def l1_event_features(q):
    from ..alpha.paper_l1_alpha import VERSION as L1_VERSION
    f=pd.DataFrame({"qi":q.qi,"ofi_depth":q.ofi/(q.depth/2),
                    "microprice_bps":(q.weighted_mid-q.mid)/q.mid*10000,
                    "spread_bps":q.spread/q.mid*10000},index=q.index)
    f["ofi_x_spread"]=f.ofi_depth*f.spread_bps
    f.attrs.update({k:v for k,v in q.attrs.items() if k!="late_events_excluded"},feature_version=L1_VERSION,
                   timestamp_convention="observed_quote_event")
    return f


def fit_l1_ridge(events,*,before,horizon="5s",tolerance="1s",parameters=None):
    from ..alpha.paper_l1_alpha import quote_states,forward_mid_labels
    q=quote_states(events,as_of=pd.Timestamp(before))
    target=forward_mid_labels(q,horizon,tolerance)
    model=PaperForecast().fit(l1_event_features(q),target.target,label_end=target.label_end,
                             before=before,parameters=parameters)
    model.artifact.update(horizon=horizon,target="future_mid_return_not_executable_pnl")
    return model
