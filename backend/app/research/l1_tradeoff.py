"""Chronological, held-out horizon diagnostics for retained L1 quotes.

Targets are future feed-mid marks, never executable returns. Models are fitted
from their training prefix here; full-day train-only artifacts are not loaded.
"""
from __future__ import annotations

import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from ..alpha.paper_l1_alpha import VERSION, observed_events, quote_states
from ..market_data.alpaca_l1_capture import load_real_l1_events
from ..market_data.history import validate_symbol
from .real_l1_research import digest

HORIZONS = ("1s", "5s", "30s", "1min", "5min")
CANDIDATES = {
    "zero": (),
    "past_mid_ridge": ("past_mid_return",),
    "qi_ridge": ("qi",),
    "l1_ridge": ("qi", "ofi_depth", "microprice_bps", "spread_bps", "ofi_x_spread"),
    "past_mid_plus_l1_ridge": ("past_mid_return", "qi", "ofi_depth", "microprice_bps", "spread_bps", "ofi_x_spread"),
}


def _hash_frame(frame):
    h = hashlib.sha256()
    h.update(json.dumps(list(frame.columns)).encode())
    h.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
    return h.hexdigest()


def decision_dataset(q, *, horizons=HORIZONS, decision_interval="5s", max_quote_age="1s",
                     label_tolerance="1s", ofi_window="5s", invalid_times=None):
    """Sample an open-anchored observation-clock grid, without random sampling.

    Lookup the latest quote at/before decision t, then the first quote at/after
    t+h. Label tolerance measures delay beyond t+h, not beyond the source quote.
    Past-mid baselines and labels must remain in the same quote_states segment.
    OFI sums all observed updates in (t-window,t], within the current segment.
    """
    step, age, tol, window = map(pd.Timedelta, (decision_interval, max_quote_age, label_tolerance, ofi_window))
    if step <= pd.Timedelta(0) or age < pd.Timedelta(0) or tol < pd.Timedelta(0) or window <= pd.Timedelta(0):
        raise ValueError("Invalid sampling/quote-age/label-tolerance/OFI-window")
    if any(pd.Timedelta(h) <= pd.Timedelta(0) for h in horizons):
        raise ValueError("Positive horizons required")
    calendar = xcals.get_calendar("XNYS")
    grids = []
    for date in sorted(set(q.index.tz_convert("America/New_York").strftime("%Y-%m-%d"))):
        if calendar.is_session(date):
            grids.append(pd.date_range(calendar.session_open(date), calendar.session_close(date), freq=step, inclusive="left"))
    if not grids:
        raise ValueError("No regular-session observations")
    grid = grids[0].append(grids[1:]).tz_convert("America/New_York")
    times, decisions = q.index.asi8, grid.asi8
    previous = np.searchsorted(times, decisions, side="right") - 1
    safe = np.maximum(previous, 0)
    valid = (previous >= 0) & (decisions-times[safe] <= age.value)
    exchange_age = None
    if "exchange_timestamp" in q:
        exchange_times = pd.DatetimeIndex(q.exchange_timestamp).asi8
        exchange_age = (decisions-exchange_times[safe])/1e9
        # A newly arrived backlog is arrival-fresh but market-stale. Enforce
        # the same explicit freshness parameter on both clocks.
        valid &= (exchange_age >= 0) & (exchange_age <= age.total_seconds())
    if invalid_times is not None and len(invalid_times):
        invalid = np.sort(pd.DatetimeIndex(invalid_times).asi8)
        last_invalid = np.searchsorted(invalid, decisions, side="right") - 1
        valid &= (last_invalid < 0) | (times[safe] > invalid[np.maximum(last_invalid, 0)])
    segments, mids = q.segment.to_numpy(), q.mid.to_numpy()
    starts = np.r_[0, np.flatnonzero(np.diff(segments) != 0)+1]
    start_for_quote = starts[np.searchsorted(starts, np.arange(len(q)), side="right")-1]
    left = np.maximum(np.searchsorted(times, decisions-window.value, side="right"), start_for_quote[safe])
    right = safe+1
    count = right-left
    ofi_cumsum = np.r_[0., np.cumsum(q.ofi.to_numpy())]
    depth_cumsum = np.r_[0., np.cumsum(q.depth.to_numpy())]
    depth = np.divide(depth_cumsum[right]-depth_cumsum[left], 2*count,
                      out=np.full(len(grid), np.nan), where=count > 0)
    sampled = pd.DataFrame(index=grid)
    sampled["quote_time"] = q.index[safe]
    sampled["quote_age_seconds"] = (decisions-times[safe])/1e9
    if exchange_age is not None:
        sampled["quote_exchange_age_seconds"] = exchange_age
    sampled["segment"] = segments[safe]
    sampled["mid"] = mids[safe]
    sampled["qi"] = q.qi.to_numpy()[safe]
    sampled["ofi_depth"] = (ofi_cumsum[right]-ofi_cumsum[left])/depth
    sampled["microprice_bps"] = ((q.weighted_mid.to_numpy()[safe]-mids[safe])/mids[safe])*10000
    sampled["spread_bps"] = q.spread.to_numpy()[safe]/mids[safe]*10000
    sampled["ofi_x_spread"] = sampled.ofi_depth*sampled.spread_bps
    sampled["decision_valid"] = valid
    output = {}
    for horizon in horizons:
        h = pd.Timedelta(horizon).value
        future = np.searchsorted(times, decisions+h, side="left")
        f = np.minimum(future, len(q)-1)
        label_valid = valid & (future < len(q)) & (times[f] <= decisions+h+tol.value) & (segments[f] == segments[safe])
        past = np.searchsorted(times, decisions-h, side="right")-1
        p = np.maximum(past, 0)
        past_valid = valid & (past >= 0) & (decisions-h-times[p] <= age.value) & (segments[p] == segments[safe])
        frame = sampled.copy()
        frame["past_mid_return"] = np.where(past_valid, mids[safe]/mids[p]-1, np.nan)
        frame["target"] = np.where(label_valid, mids[f]/mids[safe]-1, np.nan)
        frame["label_end"] = pd.to_datetime(np.where(label_valid, times[f], pd.NaT.value), utc=True)
        frame["session"] = frame.index.strftime("%Y-%m-%d")
        frame["period"] = frame.index.floor("h").strftime("%H:%M")
        frame.attrs.update(q.attrs, horizon=horizon, grid_rows=len(grid), valid_decisions=int(valid.sum()))
        output[horizon] = frame.replace([np.inf, -np.inf], np.nan)
    return output


def chronological_splits(frame, intraday_cut="12:00"):
    """Prior complete dates only, or explicitly labelled one-day diagnostic."""
    dates = sorted(frame.session.unique())
    if len(dates) == 1:
        cutoff = pd.Timestamp(f"{dates[0]} {intraday_cut}", tz="America/New_York")
        if not frame.index.min() < cutoff < frame.index.max():
            raise ValueError("Intraday diagnostic cutoff must lie inside the decision session")
        return [dict(name=f"{dates[0]}_intraday", kind="intraday_diagnostic", cutoff=cutoff,
                     train=(frame.index < cutoff) & frame.label_end.lt(cutoff).to_numpy(),
                     test=frame.index >= cutoff)]
    splits = []
    for date in dates[1:]:
        cutoff = pd.Timestamp(date, tz="America/New_York")
        splits.append(dict(name=f"{date}_prior_dates", kind="walk_forward_sessions", cutoff=cutoff,
                           train=(frame.index < cutoff) & frame.label_end.lt(cutoff).to_numpy(),
                           test=frame.session.eq(date).to_numpy()))
    return splits


def prediction_metrics(target, prediction):
    """Explicit zeros: zero forecast is an abstention for direction accuracy."""
    y, p = np.asarray(target, dtype=float), np.asarray(prediction, dtype=float)
    if len(y) == 0 or not np.isfinite(y).all() or not np.isfinite(p).all():
        raise ValueError("Finite nonempty matched targets/predictions required")
    moving = y != 0
    directional = moving & (p != 0)
    def correlation(a, b):
        if len(a) < 2 or np.ptp(a) == 0 or np.ptp(b) == 0:
            return None
        return float(np.corrcoef(a, b)[0, 1])
    mse = float(np.mean((p-y)**2)*1e8)
    return dict(rows=len(y), mse_bps2=mse, rmse_bps=float(np.sqrt(mse)),
                mae_bps=float(np.mean(np.abs(p-y))*1e4), mean_error_bps=float(np.mean(p-y)*1e4),
                ic=correlation(p, y), rank_ic=correlation(pd.Series(p).rank().to_numpy(), pd.Series(y).rank().to_numpy()),
                target_zero_fraction=float((~moving).mean()), forecast_zero_fraction=float((p == 0).mean()),
                directional_rows=int(directional.sum()),
                direction_accuracy_nonzero=float((np.sign(p[directional]) == np.sign(y[directional])).mean()) if directional.any() else None,
                forecast_direction_coverage=float(directional.sum()/moving.sum()) if moving.any() else None,
                sign_match_including_zeros=float((np.sign(p) == np.sign(y)).mean()),
                predicted_abs_bps_p50=float(np.median(np.abs(p))*1e4),
                target_abs_bps_p50=float(np.median(np.abs(y))*1e4))


def _cost_diagnostics(frame, one_way_costs, decision_interval):
    rows = []
    for cost in one_way_costs:
        hurdle = 2*cost/10000
        signal = np.where(np.abs(frame.prediction) > hurdle, np.sign(frame.prediction), 0.)
        adjacent = (np.diff(frame.index.asi8) == pd.Timedelta(decision_interval).value)
        adjacent &= np.diff(frame.segment.to_numpy()) == 0
        changes = np.abs(np.diff(signal))[adjacent]
        rows.append(dict(one_way_cost_bps=cost, round_trip_hurdle_bps=2*cost,
                         prediction_exceeds_hurdle_fraction=float((signal != 0).mean()),
                         mean_abs_sign_change_adjacent=float(changes.mean()) if len(changes) else None,
                         adjacent_pairs=int(adjacent.sum()),
                         interpretation="forecast magnitude/sign diagnostic only; no portfolio, fills, executable PnL, or optimal-action claim"))
    return rows


def evaluate_dataset(frame, *, ridge_alpha=10., intraday_cut="12:00", costs=(2., 5.), decision_interval="5s"):
    """All candidates share identical train/test rows; training-only scaling."""
    if not np.isfinite(ridge_alpha) or ridge_alpha <= 0:
        raise ValueError("Positive Ridge alpha required")
    if any(not np.isfinite(c) or c < 0 for c in costs):
        raise ValueError("Nonnegative cost scenarios required")
    required = list(CANDIDATES["past_mid_plus_l1_ridge"])+["target"]
    eligible = frame.decision_valid & frame[required].notna().all(axis=1)
    reports, predictions, splits = [], [], []
    for split in chronological_splits(frame, intraday_cut):
        train = frame.loc[split["train"] & eligible]
        test = frame.loc[split["test"] & eligible]
        split_row = dict(name=split["name"], kind=split["kind"], trained_before=split["cutoff"].isoformat(),
                         train_rows=len(train), test_rows=len(test),
                         last_train_label_end=train.label_end.max().isoformat() if len(train) else None,
                         train_data_sha256=_hash_frame(train[required+["label_end"]]),
                         test_data_sha256=_hash_frame(test[required+["label_end"]]),
                         train_grid_rows=int(split["train"].sum()), test_grid_rows=int(split["test"].sum()))
        splits.append(split_row)
        for name, columns in CANDIDATES.items():
            row = dict(model=name, split=split["name"], evaluation_kind=split["kind"], features=list(columns),
                       train_rows=len(train), test_rows=len(test), trained_before=split["cutoff"].isoformat(),
                       status="unavailable", selected_for_live=None)
            if len(train) < 2 or len(test) < 2:
                row["reason"] = "Fewer than two matched training/test observations; no fitted diagnostic"
                reports.append(row)
                continue
            if name == "zero":
                forecast = np.zeros(len(test))
                artifact = dict(model="zero", mean=[], scale=[], coefficient=[], intercept=0.)
            else:
                x = train[list(columns)].to_numpy()
                mean, scale = x.mean(axis=0), x.std(axis=0)
                scale[scale == 0] = 1
                model = Ridge(alpha=ridge_alpha, solver="svd").fit((x-mean)/scale, train.target)
                forecast = model.predict((test[list(columns)].to_numpy()-mean)/scale)
                artifact = dict(model="ridge", regularization_alpha=ridge_alpha, mean=mean.tolist(), scale=scale.tolist(),
                                coefficient=model.coef_.tolist(), intercept=float(model.intercept_))
            prediction_columns = ["quote_time", "quote_age_seconds", "segment", "label_end", "session", "period", "target"]
            if "quote_exchange_age_seconds" in test:
                prediction_columns.append("quote_exchange_age_seconds")
            prediction = test[prediction_columns].copy()
            prediction["prediction"] = forecast
            prediction["model"] = name
            prediction["split"] = split["name"]
            prediction["model_trained_before"] = split["cutoff"].isoformat()
            predictions.append(prediction)
            row.update(status="evaluated_diagnostic", metrics=prediction_metrics(test.target, forecast), artifact=artifact,
                       by_period=[dict(period=period, **prediction_metrics(part.target, part.prediction)) for period, part in prediction.groupby("period")],
                       cost_scenarios=_cost_diagnostics(prediction, costs, decision_interval))
            reports.append(row)
    return reports, (pd.concat(predictions) if predictions else pd.DataFrame()), splits


def run_l1_tradeoff(inputs, symbols, output, *, session_dates=None, horizons=HORIZONS,
                    decision_interval="5s", max_quote_age="1s", label_tolerance="1s", ofi_window="5s",
                    max_gap="30s", ridge_alpha=10., intraday_cut="12:00", costs=(2., 5.), progress=None):
    """Load each symbol once, build quote_states once, share across all horizons."""
    roots = list(dict.fromkeys(Path(p).resolve() for p in inputs))
    symbols = list(dict.fromkeys(validate_symbol(s) for s in symbols))
    horizons = list(dict.fromkeys(horizons))
    if not roots or not symbols or not horizons:
        raise ValueError("Inputs, symbols and horizons are required")
    if session_dates is not None:
        session_dates = sorted(set(session_dates))
        if not session_dates or any(pd.Timestamp(date).strftime("%Y-%m-%d") != date for date in session_dates):
            raise ValueError("Session dates must be explicit YYYY-MM-DD dates")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    parameters = dict(horizons=horizons, decision_interval=decision_interval, max_quote_age=max_quote_age,
                      label_tolerance=label_tolerance, ofi_window=ofi_window, max_gap=max_gap,
                      ridge_alpha=ridge_alpha, intraday_cut=intraday_cut, cost_scenarios_one_way_bps=list(costs))
    app_root = Path(__file__).resolve().parents[1]
    dependency_files = ("alpha/paper_l1_alpha.py", "alpha/real_l1_alpha.py", "market_data/history.py",
                        "market_data/alpaca_l1_capture.py", "research/real_l1_research.py")
    registry = dict(schema_version=1, task="l1_held_out_horizon_diagnostic", feature_version=VERSION,
                    created_at=pd.Timestamp.now(tz="UTC").isoformat(), status="unavailable", parameters=parameters,
                    requested_symbols=symbols, requested_sessions=session_dates, models=[], datasets=[], source_files=[], errors=[],
                    missing_requested_sessions=[],
                    selected_for_live=None, performance_verified=False, deployment="research_only",
                    assumptions=["Future feed-mid marks are not executable returns or trading PnL.",
                                 "IEX is one venue; spreads and future-mid marks are not consolidated NBBO.",
                                 "Historical timestamps cannot verify arrival latency or attainable fills.",
                                 "One-day morning/afternoon splits are intraday diagnostics, not future-session validation.",
                                 "Long-horizon labels overlap on the decision grid; rows are serially dependent, not independent trials.",
                                 "Quote-only study: signed trades, state-transition microprice, bar-alpha fusion and execution are not tested here.",
                                 "2/5 bps are hypothetical one-way costs; sign-change statistics are not realized turnover or savings.",
                                 "No candidate or horizon is selected for live trading or optimized against test profit."],
                    code_sha256=digest(__file__), dependency_sha256={path: digest(app_root/path) for path in dependency_files},
                    software_versions={name: importlib.metadata.version(name) for name in ("numpy", "pandas", "scikit-learn", "exchange-calendars")})
    seen_paths, seen_hashes = set(), set()
    calendar = xcals.get_calendar("XNYS")
    for symbol in symbols:
        if progress:
            progress(f"{symbol}: loading retained events once")
        try:
            frames = []
            for root in roots:
                files = (sorted(root.glob(f"*/{symbol}.jsonl")) if session_dates is None else
                         [root/date/f"{symbol}.jsonl" for date in session_dates if (root/date/f"{symbol}.jsonl").is_file()])
                for path in files:
                    if path.resolve() in seen_paths:
                        raise ValueError("Overlapping input paths would double-count events")
                    seen_paths.add(path.resolve())
                stamps = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in files}
                if session_dates is None:
                    part = load_real_l1_events(root, symbol)
                    if not part.empty:
                        frames.append(part)
                else:
                    for date in session_dates:
                        part = load_real_l1_events(root, symbol, date)
                        if not part.empty:
                            frames.append(part)
                for path in files:
                    sha = digest(path)
                    if stamps[path] != (path.stat().st_size, path.stat().st_mtime_ns):
                        raise ValueError("Input changed during read; use a completed snapshot")
                    if path.stat().st_size and sha in seen_hashes:
                        raise ValueError("Duplicate input contents would double-count events")
                    seen_hashes.add(sha)
                    registry["source_files"].append(dict(path=str(path), bytes=path.stat().st_size, sha256=sha))
            if not frames:
                raise ValueError("No retained events; no synthetic L1 generated")
            raw = pd.concat(frames).sort_index(kind="stable")
            del frames, part
            if not {"source", "feed"}.issubset(raw) or raw[["source", "feed"]].isna().any().any():
                raise ValueError("Explicit source and feed required")
            for (source, feed), events in raw.groupby(["source", "feed"], sort=True):
                observed_clock = (pd.DatetimeIndex(pd.to_datetime(events.received_at, utc=True, format="mixed"))
                                  if source == "alpaca_stock_websocket" else events.index)
                if observed_clock.hasnans:
                    raise ValueError("Missing observation-clock timestamps")
                include = np.zeros(len(events), dtype=bool)
                for date in sorted(set(observed_clock.tz_convert("America/New_York").strftime("%Y-%m-%d"))):
                    if calendar.is_session(date):
                        include |= (observed_clock >= calendar.session_open(date)) & (observed_clock < calendar.session_close(date))
                events, observed_clock = events.iloc[np.flatnonzero(include)], observed_clock[include]
                # quote_states removes locked/zero-depth quotes after segmenting.
                # Retain their observation times so backward sampling never
                # resurrects the earlier valid book during an invalid interval.
                if source == "alpaca_stock_websocket":
                    # Match the same late-event exclusion as quote_states;
                    # stale locked quotes arriving out of order must not hide
                    # a newer valid book. Historical million-row inputs do
                    # not take this additional observation-clock pass.
                    invalid_source = observed_events(events)
                    invalid = invalid_source.event_type.eq("quote") & ((invalid_source.ask_price <= invalid_source.bid_price) | ((invalid_source.bid_size+invalid_source.ask_size) <= 0))
                    invalid_times = invalid_source.index[invalid]
                    del invalid_source
                else:
                    invalid = events.event_type.eq("quote") & ((events.ask_price <= events.bid_price) | ((events.bid_size+events.ask_size) <= 0))
                    invalid_times = observed_clock[invalid]
                if progress:
                    progress(f"{symbol}/{feed}: building quote states once from {len(events):,} events")
                q = quote_states(events, max_gap=max_gap)
                datasets = decision_dataset(q, horizons=horizons, decision_interval=decision_interval,
                                            max_quote_age=max_quote_age, label_tolerance=label_tolerance,
                                            ofi_window=ofi_window, invalid_times=invalid_times)
                info = {k: q.attrs[k] for k in ("clock", "source", "feed", "symbol", "quote_size_unit")}
                info.update(quotes=len(q), raw_session_events=len(events), segments=int(q.segment.nunique()),
                            sessions=sorted(set(q.index.strftime("%Y-%m-%d"))),
                            quote_spread_bps_p50=float((q.spread/q.mid*10000).median()),
                            quote_spread_bps_p95=float((q.spread/q.mid*10000).quantile(.95)))
                missing_sessions = sorted(set(session_dates or [])-set(info["sessions"]))
                if missing_sessions:
                    registry["missing_requested_sessions"].append(dict(symbol=symbol, source=source, feed=feed,
                                                                         sessions=missing_sessions))
                registry["datasets"].append(info)
                for horizon, dataset in datasets.items():
                    models, predictions, splits = evaluate_dataset(dataset, ridge_alpha=ridge_alpha,
                                                                   intraday_cut=intraday_cut, costs=costs, decision_interval=decision_interval)
                    path = output/f"predictions_{symbol}_{feed}_{source}_{horizon}.csv"
                    if not predictions.empty:
                        predictions["horizon"] = horizon
                        predictions["source"] = source
                        predictions["feed"] = feed
                        predictions["clock"] = q.attrs["clock"]
                        predictions["symbol"] = symbol
                        # Same-row price-only forecast is retained beside every
                        # candidate so L1 incremental errors can be rechecked.
                        baseline = predictions[predictions.model.eq("past_mid_ridge")].prediction
                        predictions["baseline_prediction"] = baseline.reindex(predictions.index).to_numpy()
                        predictions.to_csv(path, index_label="decision_time")
                    for model in models:
                        model.update(symbol=symbol, feed=feed, source=source, clock=q.attrs["clock"], horizon=horizon,
                                     grid_rows=dataset.attrs["grid_rows"], valid_decisions=dataset.attrs["valid_decisions"],
                                     split_contract=next(s for s in splits if s["name"] == model["split"]),
                                     predictions_file=path.name if not predictions.empty else None,
                                     predictions_sha256=digest(path) if not predictions.empty else None)
                        registry["models"].append(model)
                    if progress:
                        progress(f"{symbol}/{feed}/{horizon}: {sum(m['status'] == 'evaluated_diagnostic' for m in models)} candidates evaluated")
                del q, datasets, events
            del raw
            gc.collect()
        except (ValueError, OSError, KeyError, AttributeError, np.linalg.LinAlgError) as error:
            registry["errors"].append(dict(symbol=symbol, reason=str(error)))
            if progress:
                progress(f"{symbol}: unavailable ({error})")
    evaluated = [m for m in registry["models"] if m["status"] == "evaluated_diagnostic"]
    registry["evaluation_kinds"] = sorted({m["evaluation_kind"] for m in evaluated})
    registry["evaluated_candidates"] = len(evaluated)
    incomplete = bool(registry["errors"] or registry["missing_requested_sessions"]) or len(evaluated) != len(registry["models"])
    registry["status"] = "partial" if evaluated and incomplete else "complete" if evaluated else "unavailable"
    summary = [dict(symbol=m["symbol"], feed=m["feed"], horizon=m["horizon"], model=m["model"], split=m["split"],
                    **m["metrics"]) for m in evaluated]
    pd.DataFrame(summary).to_csv(output/"metrics.csv", index=False)
    lines = ["# L1 held-out horizon diagnostic", "", f"Status: {registry['status']}; evaluated candidates: {len(evaluated)}.",
             f"Evaluation kinds: {', '.join(registry['evaluation_kinds'])}.", "",
             "No trading PnL, model promotion, or live orders. Full-day trained artifacts were not reused.", "",
             "Grid: exchange-calendar open anchored, fixed observation-clock intervals. Every candidate uses identical eligible rows.",
             "Labels: first same-segment quote at/after decision+horizon within tolerance; training label maturity must precede cutoff.",
             "Direction accuracy excludes zero targets and zero forecasts (abstentions); coverage and zero fractions are separate.",
             "Metrics use future venue-mid marks, with MSE in bps²; IC is Pearson and rank IC is Spearman.", "",
             "| Stock | Horizon | Model | Test rows | RMSE bps | IC | Rank IC | Direction accuracy |", "|---|---|---|---:|---:|---:|---:|---:|"]
    def fmt(value):
        return "—" if value is None else f"{value:.4f}"
    for m in evaluated:
        metric = m["metrics"]
        lines.append(f"| {m['symbol']} | {m['horizon']} | {m['model']} | {metric['rows']} | {fmt(metric['rmse_bps'])} | {fmt(metric['ic'])} | {fmt(metric['rank_ic'])} | {fmt(metric['direction_accuracy_nonzero'])} |")
    lines.extend(["", "## Interpretation limits", ""]+[f"- {a}" for a in registry["assumptions"]])
    (output/"REPORT.md").write_text("\n".join(lines)+"\n")
    (output/"registry.json").write_text(json.dumps(registry, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
    (output/"registry.sha256").write_text(digest(output/"registry.json")+"\n")
    return registry
