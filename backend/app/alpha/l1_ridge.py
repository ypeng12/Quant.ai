"""Inspectable, train-only OFI Ridge models without any bar-library dependency."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from .l1_state_models import _contract, _cutoff
from .paper_l1_alpha import VERSION, forward_mid_labels, quote_states


def l1_event_features(quotes):
    """Every feature is available at the observed quote, with no forward fill."""
    frame = pd.DataFrame({
        "qi": quotes.qi, "ofi_raw": quotes.ofi, "ofi_depth": quotes.ofi / (quotes.depth/2),
        "microprice_bps": (quotes.weighted_mid-quotes.mid)/quotes.mid*10000,
        "spread_bps": quotes.spread/quotes.mid*10000,
    }, index=quotes.index)
    minutes = quotes.index.hour*60 + quotes.index.minute - 570
    frame["ofi_x_spread"] = frame.ofi_depth*frame.spread_bps
    frame["ofi_x_session_sin"] = frame.ofi_depth*np.sin(2*np.pi*minutes/390)
    frame["ofi_x_session_cos"] = frame.ofi_depth*np.cos(2*np.pi*minutes/390)
    frame.attrs.update(quotes.attrs)
    return frame.replace([np.inf, -np.inf], np.nan)


class L1Ridge:
    def fit(self, events, *, before, horizon="5s", tolerance="1s", alpha=10., max_gap="30s"):
        cutoff = _cutoff(before)
        if not np.isfinite(alpha) or alpha <= 0:
            raise ValueError("Positive Ridge regularization alpha required")
        quotes = quote_states(events, as_of=cutoff, max_gap=max_gap)
        labels = forward_mid_labels(quotes, horizon, tolerance)
        features = l1_event_features(quotes)
        valid = features.notna().all(axis=1) & labels.target.notna() & labels.label_end.lt(cutoff)
        if int(valid.sum()) < 2:
            raise ValueError("Insufficient observed quotes with mature future-mid labels")
        values = features.loc[valid].to_numpy()
        means, scales = values.mean(axis=0), values.std(axis=0)
        scales[scales == 0] = 1
        model = Ridge(alpha=alpha, solver="svd").fit((values-means)/scales, labels.target[valid])
        self.artifact = dict(
            schema_version=1, model="ofi_ridge", feature_version=VERSION,
            features=list(features.columns), contract=_contract(quotes), mean=means.tolist(),
            scale=scales.tolist(), coefficient=model.coef_.tolist(), intercept=float(model.intercept_),
            regularization_alpha=alpha, horizon=str(horizon), tolerance=str(tolerance),
            trained_before=cutoff.isoformat(), last_label_end=labels.label_end[valid].max().isoformat(),
            rows=int(valid.sum()), sessions=int(features.index[valid].normalize().nunique()),
            deployment="research_only", performance_verified=False, target_feed=quotes.attrs["feed"],
            target=f"future_{quotes.attrs['feed']}_mid_return_not_executable_pnl",
            interpretation="Observed OFI predicts a future feed-specific mid mark; costs and execution are not evaluated",
        )
        return self

    def predict(self, events, *, as_of=None):
        quotes = quote_states(events, as_of=as_of, max_gap=self.artifact["contract"]["max_gap"])
        if _contract(quotes) != self.artifact["contract"]:
            raise ValueError("L1 Ridge source/clock/symbol contract changed")
        features = l1_event_features(quotes)
        if list(features.columns) != self.artifact["features"]:
            raise ValueError("L1 Ridge feature schema changed")
        values = (features.to_numpy()-self.artifact["mean"])/self.artifact["scale"]
        predicted = values @ np.asarray(self.artifact["coefficient"]) + self.artifact["intercept"]
        result = pd.Series(predicted, index=features.index, name="future_mid_return")
        return result.where(features.index >= pd.Timestamp(self.artifact["trained_before"]))

    def save(self, path):
        Path(path).write_text(json.dumps(self.artifact, indent=2, allow_nan=False) + "\n")

    @classmethod
    def load(cls, path):
        model = cls()
        model.artifact = json.loads(Path(path).read_text())
        if model.artifact.get("model") != "ofi_ridge" or model.artifact.get("feature_version") != VERSION:
            raise ValueError("Invalid L1 Ridge artifact")
        return model
