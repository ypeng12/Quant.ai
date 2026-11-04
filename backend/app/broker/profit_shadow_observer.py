"""Bounded, asynchronous target comparisons; never submits or changes an order.

The active policy's observed inventory is the common starting point. This is
not an independently financed shadow portfolio and cannot produce candidate PnL.
No broker, network, training, or active-policy mutation is performed here.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from numbers import Integral, Real
import os
from pathlib import Path
import re
import threading
import time
from zoneinfo import ZoneInfo


COMPARISON_KIND = "targets_from_same_observed_holdings_not_independent_pnl"
SYMBOLS = ("NVDA", "SNDK", "TSLA")
INPUTS = (*SYMBOLS, "MSTR")
NY = ZoneInfo("America/New_York")


def _stamp(value):
    value = value.isoformat() if hasattr(value, "isoformat") else str(value)
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Aware observation clock required")
    return result.astimezone(NY)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Finite real scalar required")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Finite real scalar required")
    return result


def _json_default(value):
    # Numerical model diagnostics may contain NumPy scalar values.
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return _number(value)
    raise TypeError("Unsupported diagnostic value")


def _shares(value):
    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    value = _number(value)
    if not value.is_integer():
        raise _Unavailable("baseline_share_quantities_invalid")
    return int(value)


class _Unavailable(Exception):
    def __init__(self, code):
        self.code = code


class ProfitShadowObserver:
    """One daemon worker and at most one pending, independently copied snapshot.

    Construction/status never start a worker or load a model. ``observe`` only
    captures an input; it does not wait for calculation, model I/O or journaling.
    A busy worker keeps the latest pending observation and reports skipped ones.
    """

    def __init__(self, path, journal_directory=None):
        self.path = Path(path) if path else None
        self.journal_directory = Path(journal_directory) if journal_directory else None
        self._condition = threading.Condition(threading.Lock())
        self._worker = None
        self._pending = None
        self._closed = False
        self._model = None
        self._identity = None
        self._model_hash = None
        self._seen = {}
        self._public = {
            "configured": self.path is not None,
            "state": "waiting_for_decision" if self.path else "not_configured",
            "reason_code": None,
            "error_type": None,
            "execution_enabled": False,
            "comparison_kind": COMPARISON_KIND,
            "candidate": None,
            "model_sha256": None,
            "model_trained_before": None,
            "observed_at": None,
            "recorded_at": None,
            "bar_time": None,
            "comparison_count": 0,
            "skipped_count": 0,
            "duplicate_count": 0,
            "shared_symbols": [],
            "baseline_only_symbols": [],
            "max_abs_weight_delta": None,
            "differing_target_count": None,
            "elapsed_ms": None,
            "journal_state": "not_written" if journal_directory else "not_configured",
        }

    def status(self):
        with self._condition:
            result = dict(self._public)
            result["shared_symbols"] = list(result["shared_symbols"])
            result["baseline_only_symbols"] = list(result["baseline_only_symbols"])
        observed = result["observed_at"]
        age = ((datetime.now(timezone.utc) - _stamp(observed)).total_seconds()
               if observed else None)
        result["age_seconds"] = round(age, 3) if age is not None and age >= 0 else None
        return result

    def observe(self, frames, current, equity, allowed, shortable, now, liquidation_at, baseline):
        """Enqueue without waiting; all input containers are copied before use."""
        if self.path is None:
            return False
        try:
            observed = _stamp(now)
            snapshot = dict(
                frames={s: f.copy(deep=True) for s, f in frames.items()},
                current=deepcopy(current), equity=equity,
                allowed=deepcopy(allowed), shortable=deepcopy(shortable),
                now=observed, liquidation_at=_stamp(liquidation_at),
                baseline=deepcopy(baseline),
            )
            with self._condition:
                if self._closed:
                    return False
                if self._pending is not None:
                    self._public["skipped_count"] += 1
                self._pending = snapshot
                if self._worker is None:
                    self._worker = threading.Thread(target=self._run, daemon=True,
                                                    name="quant-profit-shadow")
                    try:
                        self._worker.start()
                    except Exception:
                        self._worker = None
                        self._pending = None
                        raise
                if self._public["state"] != "computing":
                    self._public.update(state="queued", reason_code=None, error_type=None)
                self._condition.notify()
            return True
        except Exception as exc:
            self._unavailable("snapshot_unavailable", exc)
            return False

    def close(self):
        """Release this diagnostic worker without joining or touching execution."""
        with self._condition:
            self._closed = True
            self._pending = None
            self._condition.notify()

    def _unavailable(self, code, exc=None, snapshot=None):
        with self._condition:
            self._public.update(
                state="unavailable", reason_code=code,
                error_type=type(exc).__name__ if exc else None,
                max_abs_weight_delta=None, differing_target_count=None,
                elapsed_ms=None,
            )
            if snapshot:
                baseline = snapshot.get("baseline")
                bar_time = baseline.get("bar_time") if isinstance(baseline, Mapping) else None
                try:
                    bar_time = _stamp(bar_time).isoformat() if bar_time is not None else None
                except (ValueError, TypeError):
                    bar_time = None
                self._public.update(observed_at=snapshot["now"].isoformat(),
                                    bar_time=bar_time)

    def _run(self):
        while True:
            with self._condition:
                while self._pending is None and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                snapshot, self._pending = self._pending, None
                self._public.update(state="computing", reason_code=None, error_type=None)
            started = time.monotonic()
            try:
                self._process(snapshot, started)
            except _Unavailable as exc:
                self._unavailable(exc.code, snapshot=snapshot)
            except Exception as exc:
                self._unavailable("comparison_unavailable", exc, snapshot)

    def _load_model(self):
        from app.research.profit_signal_shadow import ProfitSignalShadowModel
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            raise _Unavailable("model_missing") from None
        identity = (stat.st_mtime_ns, stat.st_size)
        if identity == self._identity and self._model is not None:
            return self._model
        if stat.st_size > 2 * 1024 * 1024:
            raise _Unavailable("model_invalid")
        content = self.path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != self._model_hash or self._model is None:
            try:
                model = ProfitSignalShadowModel.load(self.path)
            except (ValueError, KeyError, TypeError):
                raise _Unavailable("model_invalid") from None
        else:
            model = self._model
        after = self.path.stat()
        if (after.st_mtime_ns, after.st_size) != identity or self.path.read_bytes() != content:
            raise _Unavailable("model_changed_during_read")
        self._model, self._model_hash, self._identity = model, digest, identity
        return model

    def _process(self, snapshot, started):
        now, baseline = snapshot["now"], snapshot["baseline"]
        if not isinstance(baseline, Mapping):
            raise _Unavailable("baseline_unavailable")
        bar = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0) - timedelta(minutes=5)
        if _stamp(baseline["bar_time"]) != bar:
            raise _Unavailable("baseline_clock_mismatch")
        model = self._load_model()
        with self._condition:
            self._public.update(candidate=model.spec.name, model_sha256=self._model_hash,
                                model_trained_before=model.trained_before)
        if model.trained_before != now.date().isoformat():
            raise _Unavailable("model_session_mismatch")
        key = (self._model_hash, bar.isoformat())
        if key in self._seen:
            with self._condition:
                self._public["duplicate_count"] += 1
                self._public.update(self._seen[key])
                self._public.update(state="observed", reason_code="same_bar_already_observed")
            return
        frames = snapshot["frames"]
        if not set(INPUTS) <= set(frames):
            raise _Unavailable("input_symbols_missing")
        current = snapshot["current"]
        weights, shares = baseline.get("target_weights"), baseline.get("target_shares")
        if (not isinstance(current, Mapping) or not set(SYMBOLS) <= set(current)
                or not isinstance(weights, Mapping) or not isinstance(shares, Mapping)
                or not set(SYMBOLS) <= set(weights) or not set(SYMBOLS) <= set(shares)):
            raise _Unavailable("comparison_universe_mismatch")
        if any(not isinstance(s, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", s)
               for s in {*current, *weights, *shares}):
            raise _Unavailable("comparison_universe_mismatch")
        current = {s: _number(current[s]) for s in SYMBOLS}
        base_weights = {s: _number(weights[s]) for s in SYMBOLS}
        base_shares = {s: _shares(shares[s]) for s in SYMBOLS}
        allowed, shortable = snapshot["allowed"], snapshot["shortable"]
        if (not isinstance(allowed, Collection) or isinstance(allowed, (str, bytes, Mapping))
                or not isinstance(shortable, Mapping)):
            raise _Unavailable("permissions_unavailable")
        if model.state.last_stamp is None and any(abs(v) > 1e-12 for v in current.values()):
            raise _Unavailable("holding_start_unknown")
        if (model.last_decision is not None and bar - _stamp(model.last_decision) > timedelta(minutes=5)
                and any(abs(v) > 1e-12 for v in current.values())):
            raise _Unavailable("holding_observation_gap")
        result = model.shadow_targets(
            {s: frames[s] for s in INPUTS}, current, snapshot["equity"],
            allowed=set(allowed).intersection(SYMBOLS),
            shortable={s: shortable.get(s, False) for s in SYMBOLS},
            as_of=now, liquidation_at=snapshot["liquidation_at"],
        )
        delta_weights = {s: float(result["target_weights"][s]) - base_weights[s] for s in SYMBOLS}
        delta_shares = {s: int(result["target_shares"][s]) - int(base_shares[s]) for s in SYMBOLS}
        recorded = datetime.now(timezone.utc).isoformat()
        receipt = {
            "kind": "profit_shadow_comparison_v1", "comparison_kind": COMPARISON_KIND,
            "execution_enabled": False, "candidate_pnl": None,
            "observed_at": now.isoformat(), "recorded_at": recorded,
            "bar_time": bar.isoformat(), "model_sha256": self._model_hash,
            "baseline": {k: baseline[k] for k in ("target_weights", "target_shares", "model",
                         "model_sha256", "decision_id", "bar_time") if k in baseline}, "shadow": result,
            "delta_weights": delta_weights, "delta_shares": delta_shares,
            "shared_symbols": list(SYMBOLS),
            "baseline_only_symbols": sorted(set(weights).difference(SYMBOLS)),
        }
        journal = self._write_journal(receipt, now.date().isoformat())
        with self._condition:
            self._public.update(
                state="observed", reason_code=None, error_type=None,
                observed_at=now.isoformat(), recorded_at=recorded, bar_time=bar.isoformat(),
                comparison_count=self._public["comparison_count"] + 1,
                shared_symbols=list(SYMBOLS), baseline_only_symbols=receipt["baseline_only_symbols"],
                max_abs_weight_delta=max(abs(v) for v in delta_weights.values()),
                differing_target_count=sum(v != 0 for v in delta_shares.values()),
                elapsed_ms=round((time.monotonic() - started) * 1000, 3), journal_state=journal,
            )
            self._seen[key] = {k: deepcopy(v) for k, v in self._public.items()
                               if k not in {"comparison_count", "skipped_count", "duplicate_count"}}
            if len(self._seen) > 256:
                del self._seen[next(iter(self._seen))]

    def _write_journal(self, receipt, day):
        if self.journal_directory is None:
            return "not_configured"
        try:
            content = json.dumps(receipt, default=_json_default, allow_nan=False, sort_keys=True) + "\n"
            self.journal_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = self.journal_directory / f"{day}.jsonl"
            if path.is_symlink():
                raise ValueError("A journal must be a regular private file")
            descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
            return "written"
        except Exception:
            return "unavailable"
