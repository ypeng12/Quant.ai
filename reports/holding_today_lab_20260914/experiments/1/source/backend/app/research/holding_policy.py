"""Versioned paper candidate: shared factors, return curve and holding plans.

No broker calls, probability claims, minimum holding timer or direction overrides.
Only the first step of a costed plan is actionable. Later steps are predictions.
"""
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf
from ..alpha.paper_bar_alpha import bar_alpha_panel, BarAlphaSpec, PEERS
from ..quant_policy import normalize_bars, feature_frame, PolicySpec, target_weights
from .paper_models import PaperForecast
from .direction_policy import planned_target

VERSION = 'direction_holding_v1'
DEFAULT_SYMBOLS = ('SNDK', 'TSLA', 'PLTR', 'NVDA')
REFERENCES = ('SPY', 'QQQ', 'SOXX')


@dataclass(frozen=True)
class HoldingSpec:
    name: str = 'context_curve'
    family: str = 'context'
    horizons: tuple = (1, 3, 6, 12)
    planning: bool = True
    ridge_alpha: float = 10.
    risk_aversion: float = 50.
    cost_bps: float = 2.
    gross_limit: float = .95
    symbol_limit: float = .70
    seasonal_sessions: int = 20
    min_price: float = 10.
    min_adv: float = 50_000_000.

    def __post_init__(self):
        if self.family not in {'legacy', 'paper', 'context'}:
            raise ValueError('Unknown feature family')
        if not self.horizons or tuple(sorted(set(self.horizons))) != tuple(self.horizons):
            raise ValueError('Sorted unique horizons required')
        if any(type(h) is not int or h < 1 or h > 12 for h in self.horizons):
            raise ValueError('Horizon must be 1 to 12 five-minute intervals')
        if self.horizons[0] != 1 or self.seasonal_sessions < 2:
            raise ValueError('One-bar entry forecast and prior seasonal sessions required')
        values = [self.ridge_alpha, self.risk_aversion, self.cost_bps, self.min_price, self.min_adv]
        if not np.isfinite(values).all() or min(values) < 0 or self.ridge_alpha == 0:
            raise ValueError('Finite nonnegative model settings required')
        if not 0 < self.symbol_limit <= self.gross_limit <= 1:
            raise ValueError('Invalid portfolio bounds')


def holding_features(frames, symbols=DEFAULT_SYMBOLS, spec=HoldingSpec()):
    bars = {s: normalize_bars(f) for s, f in sorted(frames.items())}
    if not set((*symbols, *REFERENCES)).issubset(bars):
        raise ValueError('Complete stock and market-reference inputs required')
    index = next(iter(bars.values())).index
    if any(not b.index.equals(index) for b in bars.values()):
        raise ValueError('Synchronized input panel required')
    if spec.family == 'legacy':
        result = {s: feature_frame(bars[s]) for s in symbols}
    else:
        panel = bar_alpha_panel(bars, BarAlphaSpec(), rank_symbols=symbols)
        result = {s: panel[s] for s in symbols}
    if spec.family == 'context':
        for s, f in result.items():
            b = bars[s]
            # Every denominator uses only earlier sessions at the SAME time slot.
            seasonal = b.volume.groupby(b.index.strftime('%H:%M')).transform(
                lambda v: v.shift().rolling(spec.seasonal_sessions, min_periods=2).mean())
            f['seasonal_rvol'] = b.volume / seasonal.replace(0, np.nan) - 1
            for h in (1, 3, 12):
                own = b.close.groupby(b.index.date).pct_change(h, fill_method=None)
                f[f'momentum_{h}'] = own
                for ref in REFERENCES:
                    ret = bars[ref].close.groupby(index.date).pct_change(h, fill_method=None)
                    f[f'{ref}_return_{h}'] = ret
                    f[f'{ref}_relative_{h}'] = own - ret
            delta = b.close.groupby(index.date).diff()
            distance = delta.abs().groupby(index.date).transform(lambda v: v.rolling(12).sum())
            trend = b.close.groupby(index.date).diff(12)
            f['trend_efficiency_12'] = trend / distance.replace(0, np.nan)
            f['volume_x_return'] = f.seasonal_rvol * f.momentum_1
            f['volume_x_efficiency'] = f.seasonal_rvol * f.trend_efficiency_12
            prior_close = b.close.groupby(index.date).last().shift()
            previous = pd.Series(index.date, index=index).map(prior_close)
            f['overnight_gap'] = b.open.groupby(index.date).transform('first') / previous - 1
            f['session_fraction'] = (index.hour * 60 + index.minute - 570) / 390
    for f in result.values():
        f.replace([np.inf, -np.inf], np.nan, inplace=True)
        f.attrs.update(feature_version=VERSION, spec=asdict(spec), panel_symbols=list(bars),
                       rank_symbols=list(symbols), timestamp_convention='bar_open_available_at_end',
                       window_unit='5min', peer_groups=PEERS)
    return result


def executable_labels(frame, horizon):
    """Decision after row t; enter t+1 open, exit t+h+1 open before 15:55.

    Using next opens makes adjoining curve segments add consistently (up to
    simple-return compounding). No label crosses the session or uses later days.
    """
    b = normalize_bars(frame)
    y = pd.Series(np.nan, index=b.index)
    ends = pd.Series(pd.NaT, index=b.index, dtype=b.index.dtype)
    for _, g in b.groupby(b.index.date):
        entry, exit_price = g.open.shift(-1), g.open.shift(-(horizon + 1))
        end = pd.Series(g.index, index=g.index).shift(-(horizon + 1))
        valid = end - pd.Series(g.index, index=g.index) == pd.Timedelta(minutes=5 * (horizon + 1))
        y.loc[g.index] = (exit_price / entry - 1).where(valid)
        ends.loc[g.index] = end.where(valid)
    return y, ends


def curve_from_cumulative(cumulative, horizons, steps):
    """Interpolate cumulative gross returns, then convert to interval returns."""
    cumulative = np.asarray(cumulative, dtype=float)
    if cumulative.shape[0] != len(horizons) or not np.isfinite(cumulative).all():
        raise ValueError('Finite horizon-by-symbol forecasts required')
    if (cumulative <= -1).any():
        raise ValueError('Impossible cumulative gross-return forecast')
    grid = np.r_[0, horizons]
    levels = np.vstack([np.zeros(cumulative.shape[1]), np.log1p(cumulative)])
    interpolated = np.array([np.interp(np.arange(steps + 1), grid, levels[:, j])
                             for j in range(cumulative.shape[1])]).T
    return np.expm1(np.diff(interpolated, axis=0))


class HoldingModel:
    @classmethod
    def fit(cls, frames, before, spec=HoldingSpec(), symbols=DEFAULT_SYMBOLS, features=None):
        model = cls(); model.spec = spec; model.symbols = tuple(symbols)
        model.input_symbols = tuple(sorted(frames))
        cutoff = pd.Timestamp(before)
        if cutoff.tzinfo is None or cutoff != cutoff.normalize():
            raise ValueError('Timezone-aware start-of-day training cutoff required')
        model.trained_before = str(cutoff.date())
        bars = {s: normalize_bars(f) for s, f in frames.items()}
        x = features or holding_features(bars, symbols, spec)
        model.models = {}
        for s in symbols:
            model.models[s] = {}
            for h in spec.horizons:
                y, end = executable_labels(bars[s], h)
                fit = PaperForecast().fit(x[s], y, label_end=end, before=cutoff,
                    parameters={'alpha': spec.ridge_alpha})
                model.models[s][h] = fit
        # Joint covariance of future sequential returns, fit on prior days only.
        k = max(spec.horizons)
        returns = pd.DataFrame({s: executable_labels(bars[s], 1)[0] for s in symbols})
        blocks = []
        for day, g in returns.groupby(returns.index.date):
            if str(day) >= model.trained_before: continue
            block = pd.concat([g.shift(-j) for j in range(k)], axis=1).dropna()
            blocks.append(block.to_numpy())
        values = np.concatenate(blocks)
        if len(values) < 2: raise ValueError('Insufficient mature return blocks')
        model.covariance = LedoitWolf().fit(values).covariance_
        model.history = {}
        model.eligibility = {}
        for s, b in bars.items():
            prior = b.loc[b.index < cutoff]
            days = sorted(set(prior.index.date))[-spec.seasonal_sessions:]
            model.history[s] = prior.loc[np.isin(prior.index.date, days)]
            if s in symbols:
                amount = (prior.close * prior.volume).groupby(prior.index.date).sum().tail(spec.seasonal_sessions)
                adv = float(amount.mean()) if len(amount) else 0.
                price = float(prior.close.iloc[-1])
                model.eligibility[s] = dict(eligible=len(amount) >= spec.seasonal_sessions and
                    adv >= spec.min_adv and price >= spec.min_price, prior_adv=adv, prior_price=price,
                    sessions=len(amount), scope='contemporary listed-stock research pool; not historical membership')
        model.last_diagnostics = {}
        return model

    def predictions(self, features):
        return {s: {h: m.predict(features[s]) for h, m in hs.items()} for s, hs in self.models.items()}

    def allocation(self, forecasts, current, stamp, allowed=None, shortable=None, l1_adjustment=None, liquidation_at=None):
        symbols = self.symbols; allowed = set(symbols if allowed is None else allowed)
        stamp = pd.Timestamp(stamp)
        liquidation_at = stamp.normalize() + pd.Timedelta(hours=15, minutes=55) if liquidation_at is None else pd.Timestamp(liquidation_at)
        if liquidation_at.tzinfo is None:raise ValueError('Aware exchange liquidation time required')
        remaining = int((liquidation_at -
                         stamp - pd.Timedelta(minutes=5)) / pd.Timedelta(minutes=5))
        if remaining <= 0: return dict.fromkeys(symbols, 0.), {'reason': 'scheduled_session_close'}
        cumulative = np.array([[forecasts[s][h] for s in symbols] for h in self.spec.horizons])
        if l1_adjustment is not None:
            # An externally calibrated one-interval residual can adjust only h=1.
            cumulative[0] += np.array([l1_adjustment[s] for s in symbols])
        k = min(max(self.spec.horizons), remaining) if self.spec.planning else 1
        curve = curve_from_cumulative(cumulative, self.spec.horizons, k)
        eligible = {s: s in allowed and self.eligibility[s]['eligible'] for s in symbols}
        cov = self.covariance[:k*len(symbols), :k*len(symbols)]
        if self.spec.planning:
            weights, explanation = planned_target(curve, cov, current, symbols, eligible, self.spec,shortable=shortable)
        else:
            selected=tuple(s for s in symbols if eligible[s]);indices=[symbols.index(s) for s in selected]
            weights=dict.fromkeys(symbols,0.)
            weights.update(target_weights({s:curve[0,symbols.index(s)] for s in selected},
                cov.take(indices,axis=0).take(indices,axis=1),{s:current.get(s,0.) for s in selected},
                PolicySpec(self.spec.name, horizon_bars=1, cost_bps=self.spec.cost_bps,
                    risk_aversion=self.spec.risk_aversion, symbol_limit=self.spec.symbol_limit,
                    gross_limit=self.spec.gross_limit), symbols=selected,
                    shortable=shortable, solver='osqp'))
            explanation = dict(planned_steps=1, forecast_curve_bps=(curve*10000).tolist())
        explanation.update(model=self.spec.name, feature_family=self.spec.family,
            horizons_minutes=[5*h for h in self.spec.horizons],
            cumulative_forecast_bps={s:{str(h*5):float(cumulative[i,j])*10000 for i,h in enumerate(self.spec.horizons)} for j,s in enumerate(symbols)},
            cost_assumption_bps=self.spec.cost_bps, cost_verified=False,
            active_features=len(next(iter(self.models.values()))[1].artifact['features']),
            eligibility=self.eligibility, l1_contributes=l1_adjustment is not None,
            actions={s:'hold' if abs(weights[s]-current.get(s,0))<1e-8 else
                     'reverse' if weights[s]*current.get(s,0)<0 else
                     'reduce' if abs(weights[s])<abs(current.get(s,0)) else 'increase' for s in symbols})
        return weights, explanation

    def live_target(self, frames, current, *, allowed, shortable, as_of, liquidation_at=None):
        now = pd.Timestamp(as_of)
        combined = {}
        for s in self.input_symbols:
            fresh = normalize_bars(frames[s]); fresh = fresh.loc[fresh.index+pd.Timedelta(minutes=5)<=now]
            all_bars = pd.concat([self.history[s], fresh])
            combined[s] = all_bars.loc[~all_bars.index.duplicated(keep='last')].sort_index()
        x = holding_features(combined, self.symbols, self.spec)
        predictions = self.predictions(x)
        stamps = {f.index[-1] for f in x.values()}
        if len(stamps)!=1: raise ValueError('Latest panel timestamps differ')
        stamp = stamps.pop()
        if stamp != now.floor('5min')-pd.Timedelta(minutes=5): raise ValueError('Stale holding-policy input')
        values={s:{h:float(p.loc[stamp]) for h,p in hs.items()} for s,hs in predictions.items()}
        return self.allocation(values,current,stamp,allowed,shortable,liquidation_at=liquidation_at)

    def save(self, path):
        payload=dict(kind=VERSION,spec=asdict(self.spec),symbols=self.symbols,input_symbols=self.input_symbols,
            trained_before=self.trained_before,models={s:{str(h):m.artifact for h,m in hs.items()} for s,hs in self.models.items()},
            covariance=self.covariance.tolist(),eligibility=self.eligibility,
            history={s:dict(index=[t.isoformat() for t in b.index],values=b.to_numpy().tolist()) for s,b in self.history.items()},
            performance_verified=False,deployment='paper_candidate_pending_review')
        Path(path).write_text(json.dumps(payload,allow_nan=False)+'\n')

    @classmethod
    def load(cls,path):
        a=json.loads(Path(path).read_text())
        if a.get('kind') not in {VERSION,'calibrated_direction_holding_v1'}: raise ValueError('Unsupported holding model')
        obj=cls(); spec=a['spec'];spec['horizons']=tuple(spec['horizons']);obj.spec=HoldingSpec(**spec)
        obj.symbols=tuple(a['symbols']);obj.input_symbols=tuple(a['input_symbols'])
        obj.trained_before=a['trained_before'];obj.eligibility=a['eligibility'];obj.covariance=np.array(a['covariance'])
        obj.models={}
        for s,hs in a['models'].items():
            obj.models[s]={}
            for h,artifact in hs.items():
                m=PaperForecast();m.artifact=artifact;obj.models[s][int(h)]=m
                if pd.Timestamp(artifact['last_label_end'])>=pd.Timestamp(artifact['trained_before']):
                    raise ValueError('Immature training label')
        obj.history={s:pd.DataFrame(v['values'],index=pd.to_datetime(v['index'],utc=True).tz_convert('America/New_York'),
            columns=['open','high','low','close','volume']) for s,v in a['history'].items()}
        obj.last_diagnostics={}
        return obj
