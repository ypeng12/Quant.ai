"""Non-crypto research: individual past-only model selection, one portfolio.

The declared panel is a research scope, not a historical universe claim. Model
selection minimizes equally weighted daily prediction error, not hindsight PnL.
This module is inert and contains no broker or application-startup imports.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .liquid_policy import LiquidCandidate, LiquidRuntime, LiquidityRules
from .strategy_extensions import feature_panel, mature_fit, predict

STOCKS = ('SNDK', 'TSLA', 'NVDA')
REFERENCES = ('SPY', 'QQQ', 'SOXX')
REFERENCE_MAP = {'SNDK': 'SOXX', 'TSLA': 'QQQ', 'NVDA': 'SOXX'}
MODEL_MENU = {'context_tree': ('context', 'tree'),
              'market_tree': ('market', 'tree'),
              'market_ridge': ('market', 'ridge')}


@dataclass(frozen=True)
class StockCandidate(LiquidCandidate):
    universe: str = 'noncrypto'
    model: str = 'context_tree'
    horizon: int = 1


STOCK_CANDIDATES = (
    StockCandidate('noncrypto_context_tree'),
    StockCandidate('noncrypto_market_tree', model='market_tree'),
    StockCandidate('noncrypto_market_ridge', model='market_ridge'),
    StockCandidate('noncrypto_stock_selector', model='past_selector'),
)


def stock_features(frames):
    if set(frames) != set((*STOCKS, *REFERENCES)):
        raise ValueError('Exactly the declared non-crypto stock and reference inputs required')
    own = feature_panel({s: frames[s] for s in STOCKS}, 'context')
    market = {s: f.copy() for s, f in own.items()}
    refs = feature_panel({s: frames[s] for s in REFERENCES}, 'context')
    for s, f in market.items():
        for role, ref in [('market', 'SPY'), ('reference', REFERENCE_MAP[s])]:
            other = refs[ref].reindex(f.index)
            for col in ('return_1', 'return_3', 'return_12', 'session_return', 'vwap_distance', 'seasonal_volume'):
                f[f'{role}_{col}'] = other[col]
            f[f'{role}_relative_session_return'] = f.session_return - other.session_return
            beta = f.return_1.expanding(min_periods=2).cov(other.return_1).shift() / other.return_1.expanding(min_periods=2).var().shift().replace(0, np.nan)
            f[f'{role}_residual_return_1'] = f.return_1 - beta * other.return_1
        market[s] = f.replace([np.inf, -np.inf], np.nan)
    return {'context': own, 'market': market}


def choose_models(folds, before, validation_sessions=5):
    """Auditable per-stock selection; a current/future fold is an error."""
    dates = sorted({r['validation_day'] for r in folds})
    if len(dates) != validation_sessions or any(d >= before for d in dates):
        raise ValueError('Selection requires exactly the declared prior validation sessions')
    result = {}
    for s in STOCKS:
        scores = {}
        for model in MODEL_MENU:
            rows = [r for r in folds if r['symbol'] == s and r['model'] == model]
            if len(rows) != validation_sessions or sorted(r['validation_day'] for r in rows) != dates:
                raise ValueError('Missing or duplicate per-stock validation folds')
            if any(r['last_train'] >= r['validation_day'] or r['rows'] <= 0 for r in rows):
                raise ValueError('Validation training must precede the scored session')
            error = float(np.mean([r['mse_bps2'] for r in rows]))
            if not np.isfinite(error) or error < 0:
                raise ValueError('Finite nonnegative validation error required')
            scores[model] = error
        # Stable declared menu order resolves ties; no ticker-specific override.
        selected = min(scores, key=scores.get)
        result[s] = dict(model=selected, scores_mse_bps2=scores)
    return dict(method='lowest_mean_daily_out_of_sample_squared_error',
                validation_dates=dates, selections=result, folds=folds)


class StockRuntime(LiquidRuntime):
    def __init__(self, frames, rules=LiquidityRules(min_market_cap=0), instruments=None,
                 *, research_membership=False, validation_sessions=5):
        if not isinstance(validation_sessions, int) or validation_sessions < 2:
            raise ValueError('At least two declared validation sessions required')
        self.stock_x = stock_features(frames)
        super().__init__(frames, rules, instruments, research_membership=research_membership)
        self.validation_sessions = validation_sessions
        self.stock_forecasts = {}
        self.selections = {}

    def symbols(self, c):
        return STOCKS

    def forecast(self, model, day, index):
        key = (model, day, tuple(index))
        if key not in self.stock_forecasts:
            family, estimator = MODEL_MENU[model]
            predictions, training = {}, []
            for s in STOCKS:
                x = self.stock_x[family][s]
                fit = mature_fit(x, self.base.label(s, 1), day, estimator)
                predictions[s] = predict(fit, x.reindex(index))
                training.append(dict(symbol=s, model=model, horizon=1, last_train=fit['last_train'],
                                     rows=fit['rows'], sessions=fit['sessions'], names=list(fit['names'])))
            self.stock_forecasts[key] = dict(predictions=predictions, training=training)
        return self.stock_forecasts[key]

    def select(self, day):
        if day not in self.selections:
            dates = sorted({str(d) for d in self.frames[STOCKS[0]].index.date if str(d) < day})[-self.validation_sessions:]
            folds = []
            for d in dates:
                index = self.frames[STOCKS[0]].loc[self.frames[STOCKS[0]].index.strftime('%Y-%m-%d') == d].index
                if len(index) != 78 or any(not index.equals(f.loc[f.index.strftime('%Y-%m-%d') == d].index) for f in self.frames.values()):
                    raise ValueError('Full synchronized validation sessions required')
                for model in MODEL_MENU:
                    forecast = self.forecast(model, d, index)
                    for meta in forecast['training']:
                        s = meta['symbol']; y = self.base.label(s, 1).reindex(index).to_numpy()
                        p = forecast['predictions'][s]; valid = np.isfinite(y) & np.isfinite(p)
                        if not valid.any():
                            raise ValueError('No mature validation labels')
                        folds.append(dict(symbol=s, model=model, validation_day=d, last_train=meta['last_train'],
                                          rows=int(valid.sum()), training_rows=meta['rows'],
                                          mse_bps2=float(np.mean(((y[valid]-p[valid])*10000)**2)),
                                          zero_forecast_mse_bps2=float(np.mean((y[valid]*10000)**2))))
            self.selections[day] = choose_models(folds, day, self.validation_sessions)
        return self.selections[day]

    def context(self, c, day, index, model=None):
        if c.horizon != 1:
            raise ValueError('This experiment compares only common five-minute forecast horizons')
        if c.model == 'past_selector':
            choices = self.select(day)['selections']; predictions, training = {}, []
            for s in STOCKS:
                f = self.forecast(choices[s]['model'], day, index)
                predictions[s] = f['predictions'][s]
                training.extend(t for t in f['training'] if t['symbol'] == s)
            result = dict(predictions=predictions, training=training)
        else:
            result = self.forecast(c.model, day, index)
        return dict(result, covariance=self.base.covariance(STOCKS, 1, day))

    def prepare(self, c, day, index):
        result = super().prepare(c, day, index)
        result['selection'] = self.select(day) if c.model == 'past_selector' else None
        return result

    def target(self, c, context, i, current, cost=5):
        weights, explanation = super().target(c, context, i, current, cost)
        explanation['stock_models'] = {t['symbol']: t['model'] for t in context['training']}
        return weights, explanation
