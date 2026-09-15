"""Learn a one-interval L1 residual on prior out-of-sample bar forecasts.

No fixed OFI score or institution-identity inference. Missing or incompatible
L1 leaves the bar forecast unchanged, with an explicit diagnostic.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from ..alpha.paper_l1_alpha import PAPER_L1_FEATURES, VERSION
from .paper_models import PaperForecast

CONTRACT=('symbol','feed','source','clock','quote_size_unit','feature_version')


def l1_features_for_residual(book):
    missing=[k for k in CONTRACT if k not in book.attrs]
    if missing: raise ValueError(f'L1 contract missing: {missing}')
    if book.attrs['feature_version']!=VERSION: raise ValueError('L1 feature version mismatch')
    f=book.loc[:,list(PAPER_L1_FEATURES)].copy()
    f.attrs.update({k:book.attrs[k] for k in CONTRACT},required_features=list(PAPER_L1_FEATURES),
                   timestamp_convention='bar_open_available_at_end')
    return f


class HoldingL1Residual:
    def fit(self,book,base_oos,targets,label_end,*,before,base_trained_before):
        f=l1_features_for_residual(book)
        if not all(f.index.equals(x.index) for x in [base_oos,targets,label_end,base_trained_before]):
            raise ValueError('Aligned base predictions and maturity evidence required')
        trained=pd.to_datetime(base_trained_before,utc=True)
        if trained.isna().any() or not (trained<=f.index).all():
            raise ValueError('Base forecasts must be prior-trained out-of-sample predictions')
        if not np.isfinite(base_oos.dropna()).all():raise ValueError('Invalid base forecast')
        self.model=PaperForecast().fit(f,targets-base_oos,label_end=label_end,before=before)
        self.model.artifact.update(kind='holding_l1_residual',horizon_seconds=300,
            target='next_open_to_next_interval_open_residual',l1_contract={k:book.attrs[k] for k in CONTRACT},
            base_training_provenance='per-row prior training timestamps supplied and checked')
        return self

    def adjustment(self,book,as_of):
        now=pd.Timestamp(as_of);stamp=now.floor('5min')-pd.Timedelta(minutes=5)
        if now.tzinfo is None:raise ValueError('Aware decision time required')
        if any(book.attrs.get(k)!=v for k,v in self.model.artifact['l1_contract'].items()):
            raise ValueError('L1 source, clock or units changed')
        if stamp not in book.index:raise ValueError('Completed L1 bucket unavailable')
        f=l1_features_for_residual(book.loc[[stamp]])
        value=float(self.model.predict(f).iloc[-1])
        if not np.isfinite(value):raise ValueError('Incomplete or immature real L1 features')
        return value

    def save(self,path):Path(path).write_text(json.dumps(self.model.artifact,allow_nan=False)+'\n')

    @classmethod
    def load(cls,path):
        a=json.loads(Path(path).read_text())
        if a.get('kind')!='holding_l1_residual' or a.get('horizon_seconds')!=300:
            raise ValueError('Unsupported residual model')
        obj=cls();obj.model=PaperForecast();obj.model.artifact=a
        return obj


def packet_books(packet,as_of):
    """Transport contract for a separately collected, atomic real-L1 snapshot."""
    now=pd.Timestamp(as_of);available=pd.Timestamp(packet['available_at']);stamp=pd.Timestamp(packet['bar_time'])
    if any(t.tzinfo is None for t in [now,available,stamp]):raise ValueError('Aware packet timestamps required')
    if available>now or stamp+pd.Timedelta(minutes=5)>available or stamp!=now.floor('5min')-pd.Timedelta(minutes=5):
        raise ValueError('Future, incomplete or stale L1 packet')
    result={}
    for s,row in packet['symbols'].items():
        if row['contract'].get('symbol')!=s:raise ValueError('L1 packet symbol mismatch')
        f=pd.DataFrame([row['features']],index=pd.DatetimeIndex([stamp]));f.attrs.update(row['contract'])
        result[s]=f
    return result


def apply_residuals(models,books,as_of,symbols):
    adjustment=dict.fromkeys(symbols,0.);status={}
    for s in symbols:
        try:
            adjustment[s]=models[s].adjustment(books[s],as_of)
            status[s]=dict(state='applied',residual_bps=adjustment[s]*10000,performance_verified=False)
        except (KeyError,ValueError,TypeError) as exc:
            status[s]=dict(state='base_only',reason=type(exc).__name__)
    return adjustment,status
