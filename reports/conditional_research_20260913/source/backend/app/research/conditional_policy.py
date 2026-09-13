"""Paper-inspired conditional momentum pilot, not a reproduction of Gao et al.

The paper tests opening-to-closing half-hours in ETFs. This pilot instead asks
whether observed volume/volatility states help five-/thirty-minute stock returns.
All state variables use completed bars only; no final-day regime labels.
"""
import numpy as np
import pandas as pd
from .stock_policy import StockRuntime, StockCandidate, STOCKS
from .strategy_extensions import mature_fit, predict, ResearchSpec
from .liquid_policy import allocate
from ..quant_policy import normalize_bars, horizon_fraction

CONDITIONAL_CANDIDATES = (
    StockCandidate('conditional_equal', benchmark=True),
    StockCandidate('conditional_ridge_control', model='market_ridge'),
    StockCandidate('conditional_state_h1', model='state_ridge'),
    StockCandidate('conditional_state_h6', model='state_ridge', horizon=6),
)


def state_features(frames, market_features):
    output = {}
    for s in STOCKS:
        b = normalize_bars(frames[s]); f = market_features[s].copy()
        group = b.groupby(b.index.date)
        opening = group.open.transform('first')
        steps = group.close.diff().abs().fillna((b.close-b.open).abs())
        path = steps.groupby(steps.index.date).cumsum().replace(0, np.nan)
        f['observed_path_efficiency'] = (b.close-opening).abs()/path
        slots = b.index.strftime('%H:%M')
        volatility = f.realized_volatility_12
        prior = volatility.groupby(slots).transform(lambda x: x.expanding().mean().shift())
        f['volatility_state'] = np.log(volatility/prior.replace(0, np.nan))
        f['volume_state'] = np.log1p(f.seasonal_volume)
        # Centering/scaling and all coefficients are fitted on past data only.
        for signal in ('return_3', 'return_12', 'market_relative_session_return'):
            for state in ('observed_path_efficiency', 'volatility_state', 'volume_state'):
                f[f'{signal}_x_{state}'] = f[signal]*f[state]
        output[s] = f.replace([np.inf, -np.inf], np.nan)
    return output


class ConditionalRuntime(StockRuntime):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_x = state_features(self.frames, self.stock_x['market'])
        self.state_models = {}

    def context(self, c, day, index, model=None):
        if c.model != 'state_ridge':
            return super().context(c, day, index, model)
        key = (c.horizon, day, tuple(index))
        if key not in self.state_models:
            mu, training = {}, []
            for s in STOCKS:
                f = mature_fit(self.state_x[s], self.base.label(s, c.horizon), day, 'ridge')
                mu[s] = predict(f, self.state_x[s].reindex(index))
                training.append(dict(symbol=s, model=c.model, horizon=c.horizon, last_train=f['last_train'],
                                     rows=f['rows'], sessions=f['sessions'], names=list(f['names'])))
            self.state_models[key] = dict(predictions=mu, training=training,
                                         covariance=self.base.covariance(STOCKS, c.horizon, day))
        return self.state_models[key]

    def target(self, c, context, i, current, cost=5):
        stamp = context['index'][i]
        spec = ResearchSpec(c.name, horizon_bars=c.horizon, cost_bps=cost, symbol_limit=c.symbol_limit)
        fraction = horizon_fraction(stamp, spec)
        mu = {s: float(context['mu'][s][i])*fraction for s in STOCKS}
        eligible = {s: context['eligibility'][s]['eligible'] and self.normalized[s].loc[stamp, 'close'] >= self.rules.min_price for s in STOCKS}
        weights, detail = allocate(mu, context['covariance']*fraction, current, spec, STOCKS, eligible)
        return weights, dict(detail, stock_models={t['symbol']:t['model'] for t in context['training']}, horizon_bars=c.horizon)
