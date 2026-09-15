"""Prior-only calibration of noisy return curves before portfolio allocation."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from .holding_policy import HoldingModel,HoldingSpec,holding_features,executable_labels,curve_from_cumulative
from sklearn.covariance import LedoitWolf

VERSION='calibrated_direction_holding_v1'


class CalibratedHoldingModel(HoldingModel):
    @classmethod
    def fit(cls,frames,before,spec=HoldingSpec(name='calibrated_curve'),symbols=None,features=None,validation_sessions=5):
        from .holding_policy import DEFAULT_SYMBOLS
        symbols=tuple(symbols or DEFAULT_SYMBOLS);cutoff=pd.Timestamp(before)
        x=features or holding_features(frames,symbols,spec)
        days=sorted({d for d in x[symbols[0]].index.date if str(d)<str(cutoff.date())})
        if len(days)<=validation_sessions:raise ValueError('Prior training and calibration days required')
        validation_days=days[-validation_sessions:]
        validation_start=pd.Timestamp(validation_days[0],tz='America/New_York')
        earlier=HoldingModel.fit(frames,validation_start,spec,symbols,x)
        validation_features={s:f.loc[np.isin(f.index.date,validation_days)] for s,f in x.items()}
        predictions=earlier.predictions(validation_features)
        model=super().fit(frames,cutoff,spec,symbols,x)
        model.calibration={}
        for s in symbols:
            p=pd.DataFrame(predictions[s]);mean=p.mean().to_numpy();scale=p.std(ddof=0).to_numpy();scale[scale==0]=1
            z=(p.to_numpy()-mean)/scale
            state={}
            for h in spec.horizons:
                y,end=executable_labels(frames[s],h);y=y.reindex(p.index)
                valid=y.notna()&end.reindex(p.index).lt(cutoff)&np.isfinite(z).all(axis=1)
                if valid.sum()<2:raise ValueError('Insufficient mature prior calibration labels')
                fit=Ridge(alpha=spec.ridge_alpha,solver='svd').fit(z[valid],y[valid])
                state[str(h)]=dict(coef=fit.coef_.tolist(),intercept=float(fit.intercept_),rows=int(valid.sum()),
                    last_label_end=end.reindex(p.index)[valid].max().isoformat())
            model.calibration[s]=dict(mean=mean.tolist(),scale=scale.tolist(),state=state,
                validation_days=[str(d) for d in validation_days],base_trained_before=validation_start.isoformat())
        if spec.forecast_error_risk:
            # Forward-only second-stage evaluation: earlier base forecasts are
            # frozen; each calibrator learns exclusively from preceding days.
            k=max(spec.horizons);blocks=[];folds=[];last_ends=[]
            labels={s:{h:executable_labels(frames[s],h) for h in spec.horizons} for s in symbols}
            one={s:executable_labels(frames[s],1) for s in symbols}
            for day in validation_days[2:]:
                fold_cutoff=pd.Timestamp(day,tz='America/New_York')
                estimates={};truth={};ends={};training_ends=[]
                for s in symbols:
                    p=pd.DataFrame(predictions[s]);past=p.loc[p.index<fold_cutoff]
                    mu=past.mean();sd=past.std(ddof=0).replace(0,1)
                    z=(p-mu)/sd
                    test_index=p.index[p.index.date==day]
                    cumulative=[]
                    for h in spec.horizons:
                        y,end=labels[s][h];y=y.reindex(p.index);end=end.reindex(p.index)
                        valid=(p.index<fold_cutoff)&end.lt(fold_cutoff)&y.notna()&np.isfinite(z).all(axis=1)
                        if valid.sum()<2:raise ValueError('Insufficient forward error calibration labels')
                        fit=Ridge(alpha=spec.ridge_alpha,solver='svd').fit(z.loc[valid],y.loc[valid])
                        cumulative.append(fit.predict(z.loc[test_index]))
                        training_ends.append(end.loc[valid].max())
                    estimates[s]=pd.DataFrame(np.array(cumulative).T,index=test_index,columns=spec.horizons)
                    yy,ee=one[s]
                    yy=yy.loc[yy.index.date==day];ee=ee.reindex(yy.index)
                    truth[s]=pd.concat([yy.shift(-j) for j in range(k)],axis=1).reindex(test_index)
                    ends[s]=ee.shift(-(k-1)).reindex(test_index)
                count=0
                for stamp in test_index:
                    actual=np.column_stack([truth[s].loc[stamp].to_numpy() for s in symbols])
                    if not np.isfinite(actual).all() or any(pd.isna(ends[s].loc[stamp]) or ends[s].loc[stamp]>=cutoff for s in symbols):continue
                    if any(ends[s].loc[stamp]-stamp!=pd.Timedelta(minutes=5*(k+1)) for s in symbols):continue
                    cumulative=np.column_stack([estimates[s].loc[stamp].to_numpy() for s in symbols])
                    blocks.append((actual-curve_from_cumulative(cumulative,spec.horizons,k)).ravel())
                    last_ends.extend(ends[s].loc[stamp] for s in symbols);count+=1
                folds.append(dict(day=str(day),rows=count,calibrator_last_label_end=max(training_ends).isoformat()))
            if len(blocks)<2:raise ValueError('Insufficient prior forward prediction errors')
            errors=np.array(blocks);fit=LedoitWolf().fit(errors);bias=errors.mean(axis=0)
            model.forecast_error_covariance=fit.covariance_+np.outer(bias,bias)
            model.error_training=dict(method='prior_forward_calibrator_path_error_second_moment',
                rows=len(blocks),folds=folds,last_label_end=max(last_ends).isoformat(),
                base_trained_before=validation_start.isoformat(),overlapping_windows=True)
        return model

    def allocation(self,forecasts,current,stamp,allowed=None,shortable=None,l1_adjustment=None,liquidation_at=None):
        values={}
        for s in self.symbols:
            a=self.calibration[s];raw=np.array([forecasts[s][h] for h in self.spec.horizons])
            z=(raw-a['mean'])/a['scale']
            values[s]={h:float(z@a['state'][str(h)]['coef']+a['state'][str(h)]['intercept']) for h in self.spec.horizons}
        weights,info=super().allocation(values,current,stamp,allowed,shortable,l1_adjustment,liquidation_at)
        info.update(calibration='prior_five_session_oos_return_curve_ridge',
            calibration_days=self.calibration[self.symbols[0]]['validation_days'],
            raw_cumulative_forecast_bps={s:{str(h*5):forecasts[s][h]*10000 for h in self.spec.horizons} for s in self.symbols})
        return weights,info

    def save(self,path):
        super().save(path);a=json.loads(Path(path).read_text());a.update(kind=VERSION,calibration=self.calibration)
        Path(path).write_text(json.dumps(a,allow_nan=False)+'\n')

    @classmethod
    def load(cls,path):
        a=json.loads(Path(path).read_text())
        if a.get('kind')!=VERSION:raise ValueError('Unsupported calibrated model')
        obj=HoldingModel.load(path);obj.__class__=cls;obj.calibration=a['calibration']
        cutoff=pd.Timestamp(obj.trained_before,tz='America/New_York')
        for cal in obj.calibration.values():
            if max(cal['validation_days'])>=obj.trained_before:raise ValueError('Future calibration day')
            if any(pd.Timestamp(v['last_label_end'])>=cutoff for v in cal['state'].values()):raise ValueError('Immature calibration target')
        return obj
