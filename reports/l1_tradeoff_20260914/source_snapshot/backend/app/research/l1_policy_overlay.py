"""Research adapter joining a bar forecast and observed L1 diagnostics.

No orders are emitted and no L1 number is added to expected bar returns by
default. Missing, stale or incompatible L1 leaves ``base_mu`` and covariance
unchanged. ``candidate_mu`` is a separate research output, never a replacement
for ``base_mu``. The caller supplies freshness and source expectations.

A future fusion model must expose ``artifact`` and::

    predict(*, base_mu, features, decision_time, horizon_seconds) -> Mapping

``features`` has one row per symbol and the exact PAPER_L1_FEATURES columns.
The artifact contract is validated by ``_fusion_candidate`` below. Metadata
checks establish compatibility, not profitability or successful calibration.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from ..alpha.paper_l1_alpha import (
    PAPER_L1_FEATURES, VERSION, enhanced_l1_features, observed_events, quote_states,
)


_CONTRACT_KEYS = ("symbol", "feed", "source", "clock", "max_gap", "quote_size_unit")
_EXPECTED_KEYS = ("feed", "source", "clock")


def _timestamp(value, name):
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return timestamp


def _json_value(value):
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json_value(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


@dataclass(frozen=True)
class L1PolicyRecord:
    """Base forecast references remain untouched; ``to_dict`` is JSON-safe."""

    base_mu: Mapping[str, float]
    covariance: Any
    symbols: tuple[str, ...]
    decision_time: pd.Timestamp
    horizon_seconds: float
    base_target: str
    l1: dict
    candidate_mu: dict[str, float] | None
    fusion: dict

    def to_dict(self):
        return _json_value(dict(
            schema_version=1, deployment="research_only", base_mu=self.base_mu,
            covariance=self.covariance, symbols=self.symbols,
            decision_time=self.decision_time, horizon_seconds=self.horizon_seconds,
            base_target=self.base_target, feature_version=VERSION, l1=self.l1,
            candidate_mu=self.candidate_mu, fusion=self.fusion,
            active_forecast="base_mu",
        ))


def _observed_prefix(events, decision_time):
    """Remove events unavailable at the decision before validating features.

    In particular a WebSocket packet timestamped before t but received after t
    cannot change t's diagnostic record. Nothing is written to raw capture.
    """
    if not isinstance(events.index, pd.DatetimeIndex) or events.index.tz is None:
        raise ValueError("Timezone-aware event index required")
    if "source" not in events or events.source.isna().any():
        raise ValueError("Every event needs an explicit source")
    sources = events.source.unique()
    if len(sources) != 1:
        raise ValueError("One source per symbol input is required")
    if sources[0] == "alpaca_stock_websocket":
        if "received_at" not in events:
            raise ValueError("WebSocket events require received_at")
        clock = pd.DatetimeIndex(pd.to_datetime(
            events.received_at, utc=True, errors="coerce", format="mixed"))
        if clock.hasnans:
            raise ValueError("Invalid received_at")
    else:
        clock = events.index
    return events.loc[clock < decision_time].copy()


def _artifact_maturity(artifact, decision_time):
    trained_before = _timestamp(artifact["trained_before"], "trained_before")
    last_label_end = _timestamp(artifact["last_label_end"], "last_label_end")
    if trained_before > decision_time:
        raise ValueError("Model training cutoff is later than decision_time")
    if last_label_end >= trained_before or last_label_end >= decision_time:
        raise ValueError("Model labels were not mature before training and decision")


def _model_diagnostic(model, events, quotes, decision_time):
    """Run an existing L1 model with its own explicitly labelled target."""
    artifact = model.artifact
    output = dict(status="unavailable", model=artifact.get("model"),
                  target=artifact.get("target"), target_feed=artifact.get("target_feed"),
                  performance_verified=artifact.get("performance_verified", False),
                  deployment=artifact.get("deployment"),
                  contributes_to_base_mu=False)
    try:
        if artifact.get("schema_version") != 1 or artifact.get("feature_version") != VERSION:
            raise ValueError("L1 model feature schema/version mismatch")
        contract = {key: quotes.attrs[key] for key in _CONTRACT_KEYS}
        if artifact.get("contract") != contract:
            raise ValueError("L1 model source/clock/symbol/units contract mismatch")
        _artifact_maturity(artifact, decision_time)
        kind, feed = artifact["model"], contract["feed"]
        targets = dict(
            qi_logistic=f"next_{feed}_mid_move_up",
            transition_microprice=f"future_{feed}_mid_after_finite_price_changes",
            ofi_ridge=f"future_{feed}_mid_return_not_executable_pnl",
        )
        if kind not in targets or artifact.get("target") != targets[kind] or artifact.get("target_feed") != feed:
            raise ValueError("L1 model target/feed mismatch or unsupported model")
        output["horizon_seconds"] = None
        if kind == "ofi_ridge":
            horizon = pd.Timedelta(artifact["horizon"]).total_seconds()
            if horizon <= 0 or not np.isfinite(horizon):
                raise ValueError("Invalid L1 Ridge horizon")
            output["horizon_seconds"] = horizon
        predicted = model.predict(events, as_of=decision_time)
        if predicted.empty or not isinstance(predicted.index, pd.DatetimeIndex) or predicted.index.tz is None:
            raise ValueError("Model returned no timestamped prediction")
        # Do not backfill an unsupported latest state with an older prediction.
        timestamp, value = predicted.index[-1], predicted.iloc[-1]
        if timestamp != quotes.index[-1] or timestamp >= decision_time:
            raise ValueError("Model prediction is not at the latest observed quote")
        if timestamp < _timestamp(artifact["trained_before"], "trained_before"):
            raise ValueError("No post-training L1 observation at this decision")
        if isinstance(value, pd.Series):
            if not np.isfinite(value.to_numpy(dtype=float)).all():
                raise ValueError("Latest quote state has no finite model prediction")
            value = value.to_dict()
        else:
            value = float(value)
            if not np.isfinite(value):
                raise ValueError("Latest quote state has no finite model prediction")
        if kind == "qi_logistic" and not 0 <= value <= 1:
            raise ValueError("QI prediction must be a probability")
        output.update(status="available", observation_time=timestamp.isoformat(), value=value,
                      interpretation=artifact.get("interpretation"))
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        output["reason"] = str(error)
    return output


def _symbol_diagnostic(symbol, events, *, decision_time, expected_contract,
                       max_quote_age, frequency, max_gap, models):
    result = dict(status="unavailable", reason=None, features={}, models={},
                  feature_version=VERSION, contributes_to_base_mu=False)
    if events is None or events.empty:
        result["reason"] = "No retained real L1 events for this symbol"
        return result
    try:
        if not isinstance(expected_contract, Mapping) or not all(key in expected_contract for key in _EXPECTED_KEYS):
            raise ValueError("Explicit expected feed/source/clock contract is required")
        prefix = _observed_prefix(events, decision_time)
        observed = observed_events(prefix, as_of=decision_time)
        quotes = quote_states(prefix, as_of=decision_time, max_gap=max_gap)
        contract = {key: quotes.attrs[key] for key in _CONTRACT_KEYS}
        result["contract"] = contract
        if contract["symbol"] != symbol:
            raise ValueError("Observed L1 symbol differs from base forecast symbol")
        if any(contract.get(key) != value for key, value in expected_contract.items()):
            raise ValueError("Observed feed/source/clock/units contract differs from expectation")
        current_quote = observed.loc[observed.event_type.eq("quote")].iloc[-1]
        result["latest_observed_quote_time"] = current_quote.name.isoformat()
        # quote_states deliberately removes locked/empty book states for model
        # fitting. A later invalid quote must not revive an older valid book.
        if (float(current_quote.ask_price) <= float(current_quote.bid_price)
                or float(current_quote.bid_size) + float(current_quote.ask_size) <= 0):
            raise ValueError("Latest observed quote is locked or has zero depth; older quotes are not current")
        latest = quotes.index[-1]
        quote_age = (decision_time - latest).total_seconds()
        # Arrival freshness alone must not make an old exchange quote current.
        exchange_time = quotes.exchange_timestamp.iloc[-1] if "exchange_timestamp" in quotes else latest
        exchange_age = (decision_time - exchange_time).total_seconds()
        result.update(
            latest_quote_time=latest.isoformat(), quote_age_seconds=quote_age,
            latest_exchange_time=exchange_time.isoformat(), exchange_quote_age_seconds=exchange_age,
            max_quote_age_seconds=max_quote_age.total_seconds(),
            late_events_excluded=int(observed.attrs.get("late_events_excluded", 0)),
            events_observed=len(observed), quotes_observed=len(quotes),
            current_mid=float(quotes.mid.iloc[-1]), current_spread=float(quotes.spread.iloc[-1]),
            price_scope="single_venue_iex_not_nbbo" if contract["feed"] == "iex" else "consolidated_sip",
        )
        features = enhanced_l1_features(prefix, frequency, as_of=decision_time, max_gap=max_gap)
        complete = features.loc[(features.index + pd.Timedelta(frequency) <= decision_time)
                                & features.l1_quote_updates.gt(0)]
        if not complete.empty:
            row = complete.iloc[-1]
            opened = complete.index[-1]
            expected_end = decision_time.floor(frequency)
            result.update(
                bucket_open=opened.isoformat(),
                bucket_end=(opened + pd.Timedelta(frequency)).isoformat(),
                bucket_is_latest_complete=bool(opened + pd.Timedelta(frequency) == expected_end),
                features=_json_value(row.loc[list(PAPER_L1_FEATURES)].to_dict()),
                missing_features=[key for key in PAPER_L1_FEATURES if pd.isna(row[key])],
            )
        else:
            result.update(bucket_is_latest_complete=False, missing_features=list(PAPER_L1_FEATURES))
        if quote_age > max_quote_age.total_seconds() or exchange_age > max_quote_age.total_seconds():
            raise ValueError("Latest real quote is stale for the requested freshness assumption")
        if exchange_age < 0:
            raise ValueError("Latest exchange timestamp is later than decision_time")
        result["status"] = "available"
        # A fresh event model can exist before the first completed bar bucket.
        result["models"] = {
            name: _model_diagnostic(model, prefix, quotes, decision_time)
            for name, model in (models or {}).items()
        }
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        result["reason"] = str(error)
    return result


def _fusion_candidate(model, *, base_mu, symbols, l1, decision_time,
                      horizon_seconds, base_target, frequency):
    report = dict(status="unavailable", reason="No calibrated fusion model supplied",
                  affects_base_mu=False)
    if model is None:
        return None, report
    try:
        artifact = model.artifact
        report.update(model=artifact.get("model"), deployment=artifact.get("deployment"),
                      performance_verified=artifact.get("performance_verified"))
        if artifact.get("schema_version") != 1 or artifact.get("feature_version") != VERSION:
            raise ValueError("Fusion feature schema/version mismatch")
        if artifact.get("model") != "calibrated_l1_fusion" or artifact.get("calibration_status") != "fitted":
            raise ValueError("Fusion requires a fitted calibration artifact")
        if not artifact.get("calibration_method"):
            raise ValueError("Fusion must identify its fitted calibration method")
        if artifact.get("deployment") not in ("research_only", "shadow") or not isinstance(artifact.get("performance_verified"), bool):
            raise ValueError("Fusion must declare research/shadow deployment and verification status")
        if artifact.get("target") != base_target or artifact.get("forecast_horizon_seconds") != horizon_seconds:
            raise ValueError("Fusion target/horizon differs from base forecast; future feed mid is not executable return")
        if artifact.get("frequency") != frequency or artifact.get("features") != list(PAPER_L1_FEATURES):
            raise ValueError("Fusion bucket frequency or feature order mismatch")
        if artifact.get("symbols") != list(symbols):
            raise ValueError("Fusion symbol order differs from base covariance order")
        _artifact_maturity(artifact, decision_time)
        for symbol in symbols:
            diagnostic = l1[symbol]
            if diagnostic["status"] != "available" or not diagnostic.get("bucket_is_latest_complete") or diagnostic.get("missing_features"):
                raise ValueError(f"Fusion requires complete current observed L1 features for {symbol}")
            if artifact.get("contracts", {}).get(symbol) != diagnostic["contract"]:
                raise ValueError(f"Fusion source/clock/symbol/units contract mismatch for {symbol}")
        features = pd.DataFrame.from_dict({symbol: l1[symbol]["features"] for symbol in symbols}, orient="index")
        features = features.loc[list(symbols), list(PAPER_L1_FEATURES)]
        candidate = model.predict(base_mu=dict(base_mu), features=features,
                                  decision_time=decision_time, horizon_seconds=horizon_seconds)
        if not isinstance(candidate, Mapping) or set(candidate) != set(symbols):
            raise ValueError("Fusion prediction must contain exactly the base forecast symbols")
        candidate = {symbol: float(candidate[symbol]) for symbol in symbols}
        if not np.isfinite(list(candidate.values())).all():
            raise ValueError("Fusion prediction must contain finite returns")
        report.update(status="available", reason=None, target=base_target,
                      forecast_horizon_seconds=horizon_seconds)
        return candidate, report
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        report["reason"] = str(error)
        return None, report


def build_l1_policy_record(base_forecast, events_by_symbol, *, decision_time,
                           horizon_seconds, base_target, expected_contracts,
                           max_quote_age, frequency="5min", max_gap="30s",
                           l1_models=None, fusion_model=None):
    """Attach causal L1 diagnostics while preserving the original forecast.

    ``base_forecast`` is duck typed: ``mu`` is a symbol->gross-return mapping,
    ``covariance`` is its matrix and optional ``symbols`` gives matrix order.
    ``base_target`` must explicitly describe that return, e.g.
    ``next_open_to_horizon_close_gross_return``. Never describe an IEX mid mark
    as an executable return. ``expected_contracts`` maps symbols to at least
    feed/source/clock. ``l1_models`` maps symbols to {name: fitted model}.

    Data issues affect only L1 availability, not the base strategy. Invalid
    *base* forecasts or call parameters raise rather than inventing a forecast.
    """
    decision_time = _timestamp(decision_time, "decision_time")
    if not isinstance(base_target, str) or not base_target.strip():
        raise ValueError("An explicit base_target is required")
    horizon_seconds = float(horizon_seconds)
    if not np.isfinite(horizon_seconds) or horizon_seconds <= 0:
        raise ValueError("Positive finite forecast horizon_seconds required")
    max_quote_age = pd.Timedelta(max_quote_age)
    if pd.isna(max_quote_age) or max_quote_age <= pd.Timedelta(0):
        raise ValueError("Positive explicit max_quote_age required")
    if pd.Timedelta(frequency) <= pd.Timedelta(0) or pd.Timedelta(max_gap) <= pd.Timedelta(0):
        raise ValueError("Positive fixed bucket frequency and max_gap required")
    # Validate fixed-length frequency before deriving completed bucket bounds.
    decision_time.floor(frequency)
    mu, covariance = base_forecast.mu, base_forecast.covariance
    if not isinstance(mu, Mapping) or not mu or not np.isfinite(list(mu.values())).all():
        raise ValueError("Base mu must be a nonempty finite symbol-return mapping")
    symbols = tuple(getattr(base_forecast, "symbols", tuple(mu)))
    if len(set(symbols)) != len(symbols) or set(symbols) != set(mu):
        raise ValueError("Base symbol order must match mu exactly")
    matrix = np.asarray(covariance, dtype=float)
    if matrix.shape != (len(symbols), len(symbols)) or not np.isfinite(matrix).all():
        raise ValueError("Base covariance shape/values do not match symbols")
    l1 = {
        symbol: _symbol_diagnostic(
            symbol, events_by_symbol.get(symbol), decision_time=decision_time,
            expected_contract=expected_contracts.get(symbol), max_quote_age=max_quote_age,
            frequency=frequency, max_gap=max_gap, models=(l1_models or {}).get(symbol),
        ) for symbol in symbols
    }
    candidate, fusion = _fusion_candidate(
        fusion_model, base_mu=mu, symbols=symbols, l1=l1,
        decision_time=decision_time, horizon_seconds=horizon_seconds,
        base_target=base_target, frequency=frequency,
    )
    return L1PolicyRecord(mu, covariance, symbols, decision_time, horizon_seconds,
                          base_target, l1, candidate, fusion)
