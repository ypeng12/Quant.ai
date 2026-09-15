"""Forecast uncertainty changes sizing without hard direction or time rules."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.quant_policy import PolicySpec, target_weights
from app.research.direction_policy import planned_target


def plan(mu, covariance, current=0., **kwargs):
    return planned_target(np.asarray(mu, dtype=float).reshape(-1, 1), covariance,
                          {'stock': current}, ('stock',), {'stock': True},
                          PolicySpec('uncertainty_test', risk_aversion=50., cost_bps=2.), **kwargs)


def test_none_matches_one_step_objective_including_terminal_cost():
    mu = .0015
    covariance = np.array([[.00008]])
    weights, info = plan([mu], covariance, current=.2)
    explicit_none, _ = plan([mu], covariance, current=.2, forecast_error_covariance=None)
    # The existing one-period solver can express terminal liquidation cost as
    # its absolute-position penalty, independently reproducing the old planner.
    reference = target_weights({'stock': mu}, covariance, {'stock': .2},
                               PolicySpec('reference', risk_aversion=50., cost_bps=2.),
                               symbols=('stock',), uncertainty=[.0002],
                               uncertainty_aversion=1., solver='osqp')
    assert weights == pytest.approx(reference, abs=1e-7)
    assert explicit_none == pytest.approx(weights, abs=1e-9)
    assert info['forecast_error_risk_enabled'] is False
    assert info['forecast_error_variance'] == 0
    assert info['total_risk_variance'] == pytest.approx(info['forecast_variance'])


def test_forecast_uncertainty_reduces_extreme_exposure_and_accounts_for_risk():
    covariance = np.array([[.000001]])
    without, _ = plan([.0015], covariance)
    weights, info = plan([.0015], covariance, forecast_error_covariance=np.array([[.0001]]))
    assert without['stock'] == pytest.approx(.7, abs=1e-7)
    assert 0 < weights['stock'] < without['stock']
    assert info['forecast_error_risk_enabled'] is True
    assert info['forecast_error_variance'] > 0
    assert info['total_risk_variance'] == pytest.approx(
        info['forecast_variance'] + info['forecast_error_variance'])


def test_strong_negative_forecast_still_reverses_a_long_position():
    weights, info = plan([-.01], np.array([[.000001]]), current=.5,
                         forecast_error_covariance=np.array([[.0001]]))
    assert weights['stock'] < 0
    assert info['estimated_plan_turnover_cost'] > .5 * .0002


@pytest.mark.parametrize('invalid', [
    np.zeros((1, 1)),  # The plan below has two intervals.
    np.array([[1., np.nan], [np.nan, 1.]]),
    np.array([[1., 1.], [0., 1.]]),
    np.array([[1., 2.], [2., 1.]]),
])
def test_invalid_forecast_error_covariance_is_rejected(invalid):
    with pytest.raises(ValueError, match='Covariance'):
        plan([.001, .002], np.eye(2) * .00001, forecast_error_covariance=invalid)
