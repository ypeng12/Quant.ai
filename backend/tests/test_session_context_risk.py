"""Opening observations and prediction-error evidence are causal model inputs."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research.calibrated_holding import CalibratedHoldingModel
from app.research.holding_policy import DEFAULT_SYMBOLS, REFERENCES, HoldingSpec, holding_features
from test_holding_policy import frames


def test_opening_context_is_observed_without_fabricating_long_lookbacks(frames):
    features = holding_features(frames, spec=HoldingSpec(family='session_context'))
    opening = pd.Timestamp('2026-08-10 09:30', tz='America/New_York')
    for symbol in DEFAULT_SYMBOLS:
        row = features[symbol].loc[opening]
        expected = frames[symbol].loc[opening, 'close'] / frames[symbol].loc[opening, 'open'] - 1
        assert row.state_open_return == pytest.approx(expected)
        assert np.isnan(row.momentum_12)
        assert row.state_momentum_12_available == 0
        assert row.state_beta_available == 0
        for ref in REFERENCES:
            ref_expected = frames[ref].loc[opening, 'close'] / frames[ref].loc[opening, 'open'] - 1
            assert row[f'state_{ref}_open_return'] == pytest.approx(ref_expected)
            assert row[f'state_{ref}_open_residual'] == pytest.approx(expected - ref_expected)
            assert np.isnan(row[f'{ref}_return_12'])


def test_session_context_matches_prefix_and_ignores_future_extrema(frames):
    spec = HoldingSpec(family='session_context')
    last_closed = pd.Timestamp('2026-08-10 10:05', tz='America/New_York')
    original = holding_features(frames, spec=spec)
    prefix = holding_features({s: b.loc[:last_closed] for s, b in frames.items()}, spec=spec)
    changed = {s: b.copy() for s, b in frames.items()}
    for bars in changed.values():
        bars.loc[bars.index > last_closed, ['open', 'high', 'low', 'close', 'volume']] *= 3
    mutated = holding_features(changed, spec=spec)
    for symbol in DEFAULT_SYMBOLS:
        pd.testing.assert_frame_equal(original[symbol].loc[:last_closed], prefix[symbol])
        pd.testing.assert_frame_equal(original[symbol].loc[:last_closed], mutated[symbol].loc[:last_closed])


def test_error_covariance_uses_prior_forward_folds_and_survives_roundtrip(frames, tmp_path):
    cutoff = pd.Timestamp('2026-08-10', tz='America/New_York')
    spec = HoldingSpec(family='session_context', horizons=(1, 3), seasonal_sessions=2,
                       forecast_error_risk=True)
    model = CalibratedHoldingModel.fit(frames, cutoff, spec, validation_sessions=3)
    changed = {s: b.copy() for s, b in frames.items()}
    for bars in changed.values():
        # Mutate all not-yet-observed prices and volume while preserving OHLC.
        bars.loc[bars.index >= cutoff, ['open', 'high', 'low', 'close', 'volume']] *= 2
    other = CalibratedHoldingModel.fit(changed, cutoff, spec, validation_sessions=3)
    np.testing.assert_allclose(model.forecast_error_covariance, other.forecast_error_covariance,
                               rtol=0, atol=1e-14)
    assert model.error_training == other.error_training
    assert len(model.error_training['folds']) == 1
    for fold in model.error_training['folds']:
        assert pd.Timestamp(fold['calibrator_last_label_end']) < pd.Timestamp(fold['day'], tz='America/New_York')
        assert pd.Timestamp(fold['day'], tz='America/New_York') < cutoff
    assert pd.Timestamp(model.error_training['last_label_end']) < cutoff
    assert np.linalg.eigvalsh(model.forecast_error_covariance).min() >= -1e-14
    assert model.forecast_error_covariance.shape == (12, 12)

    path = tmp_path / 'candidate.json'
    model.save(path)
    restored = CalibratedHoldingModel.load(path)
    np.testing.assert_allclose(restored.forecast_error_covariance, model.forecast_error_covariance)
    kwargs = dict(allowed=DEFAULT_SYMBOLS, shortable=dict.fromkeys(DEFAULT_SYMBOLS, True),
                  as_of=cutoff + pd.Timedelta(hours=10, minutes=35))
    before, info = model.live_target(frames, dict.fromkeys(DEFAULT_SYMBOLS, 0.), **kwargs)
    after, _ = restored.live_target(frames, dict.fromkeys(DEFAULT_SYMBOLS, 0.), **kwargs)
    assert after == pytest.approx(before, abs=1e-7)
    assert info['forecast_error_risk_enabled'] is True

    artifact = json.loads(path.read_text())
    artifact['error_training']['last_label_end'] = cutoff.isoformat()
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError, match='Immature forecast error'):
        CalibratedHoldingModel.load(path)
