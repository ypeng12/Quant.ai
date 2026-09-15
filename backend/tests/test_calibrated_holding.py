import json
import numpy as np
import pandas as pd
import pytest
from test_holding_policy import frames
from app.research.holding_policy import HoldingSpec, DEFAULT_SYMBOLS
from app.research.calibrated_holding import CalibratedHoldingModel


def test_prior_calibration_roundtrip_and_future_independence(frames, tmp_path):
    before = pd.Timestamp('2026-08-10', tz='America/New_York')
    spec = HoldingSpec(family='legacy', horizons=(1, 3), seasonal_sessions=2)
    model = CalibratedHoldingModel.fit(frames, before, spec, validation_sessions=2)
    changed = {s: f.copy() for s, f in frames.items()}
    for f in changed.values():
        f.loc[f.index >= before, ['open', 'high', 'low', 'close']] *= 2
    other = CalibratedHoldingModel.fit(changed, before, spec, validation_sessions=2)
    assert model.calibration == other.calibration
    path = tmp_path / 'candidate.json'
    model.save(path)
    restored = CalibratedHoldingModel.load(path)
    now = before + pd.Timedelta(hours=10, minutes=35)
    kwargs = dict(allowed=DEFAULT_SYMBOLS, shortable=dict.fromkeys(DEFAULT_SYMBOLS, True), as_of=now)
    a, info = model.live_target(frames, dict.fromkeys(DEFAULT_SYMBOLS, 0.), **kwargs)
    b, _ = restored.live_target(frames, dict.fromkeys(DEFAULT_SYMBOLS, 0.), **kwargs)
    assert a == pytest.approx(b)
    assert max(info['calibration_days']) < str(before.date())
    assert all(np.isfinite(list(a.values())))
    artifact = json.loads(path.read_text())
    artifact['calibration']['SNDK']['state']['1']['last_label_end'] = now.isoformat()
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError, match='Immature calibration'):
        CalibratedHoldingModel.load(path)
