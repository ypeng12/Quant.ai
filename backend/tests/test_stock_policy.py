import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import pytest
from app.research.stock_policy import StockRuntime, StockCandidate, STOCKS, REFERENCES, MODEL_MENU, stock_features, choose_models
from app.research.liquid_policy import LiquidityRules
from test_liquid_policy import histories, metadata


def panel():
    original = histories()
    return {s: original.get(s, original['SPY']).copy() for s in (*STOCKS, *REFERENCES)}


def test_only_declared_noncrypto_inputs_and_causal_features():
    f = panel(); cut = pd.Timestamp('2026-08-31 10:00', tz='America/New_York')
    full = stock_features(f); prefix = stock_features({s: x.loc[:cut] for s, x in f.items()})
    for family in full:
        for s in STOCKS:
            pd.testing.assert_frame_equal(full[family][s].loc[:cut], prefix[family][s])
    with pytest.raises(ValueError, match='Exactly'):
        stock_features(dict(f, MSTR=f['SPY']))


def test_selector_really_selects_independently_and_rejects_leakage():
    days = ['2026-08-27', '2026-08-28']; folds = []
    for i, s in enumerate(STOCKS):
        for j, model in enumerate(MODEL_MENU):
            for day in days:
                folds.append(dict(symbol=s, model=model, validation_day=day, last_train='2026-08-26', rows=76, mse_bps2=abs(i-j)))
    selected = choose_models(folds, '2026-08-31', 2)['selections']
    expected = [list(MODEL_MENU)[min(i, len(MODEL_MENU) - 1)] for i in range(len(STOCKS))]
    assert [selected[s]['model'] for s in STOCKS] == expected
    with pytest.raises(ValueError, match='prior validation'):
        choose_models(folds, '2026-08-28', 2)
    bad = [dict(r) for r in folds]; bad[0]['last_train'] = bad[0]['validation_day']
    with pytest.raises(ValueError, match='precede'):
        choose_models(bad, '2026-08-31', 2)


def test_future_prices_cannot_change_selected_models_forecasts_or_portfolio():
    f = panel(); cut = pd.Timestamp('2026-08-31 10:00', tz='America/New_York'); idx = pd.DatetimeIndex([cut])
    rules = LiquidityRules(min_adv=1, min_market_cap=0)
    a = StockRuntime(f, rules, metadata(f))
    b = StockRuntime({s: x.loc[:cut] for s, x in f.items()}, rules, metadata(f))
    c = StockCandidate('test', model='past_selector')
    x = a.prepare(c, '2026-08-31', idx); y = b.prepare(c, '2026-08-31', idx)
    assert x['selection'] == y['selection']
    assert all(t['last_train'] < '2026-08-31' for t in x['training'])
    assert all(t['last_train'] < t['validation_day'] < '2026-08-31' for t in x['selection']['folds'])
    for s in STOCKS:
        np.testing.assert_allclose(x['mu'][s], y['mu'][s])
    wa, _ = a.target(c, x, 0, {}); wb, _ = b.target(c, y, 0, {})
    np.testing.assert_allclose(list(wa.values()), list(wb.values()), atol=1e-8)
    assert sum(abs(v) for v in wa.values()) <= .95 + 1e-8
    with pytest.raises(ValueError, match='All current exposure'):
        a.target(c, x, 0, {'MSTR': .1})
