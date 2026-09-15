# backend/app/broker/live_runner.py
"""
Live execution of the shared causal research policy.
Completed bars determine portfolio targets; broker orders and fills determine execution state.
"""

import asyncio
import datetime
import json
import math
import os
import pytz
import threading
import time
from typing import Dict, List, Optional
import pandas as pd

from app.broker.alpaca_adapter import AlpacaAdapter
from app.broker.mock_adapter import MockAlpacaAdapter
from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL, WATCHLIST, EXCLUDED_TICKERS, save_watchlist, load_watchlist
from app.data_manager import fetch_and_prepare_data
from app.data_cache import invalidate_cache
from app.broker.research_execution import closed_bars, plan_rebalance, recalculate_fifo, TERMINAL_STATUSES


class LiveTradingRunner:
    @staticmethod
    def _quant_policy_defaults() -> Dict:
        return {
            "strategy_version": "causal_quant_policy_v1",
            "strategy_mode": "quant_policy",
            "quant_policy_path": "../reports/quant_research_20260913/selected_policy.json",
            "bar_interval": "5m",
            "allow_shorting": True,
            # Preserve the existing account authorization. Model gross and symbol
            # limits are explicit in its artifact; these are execution settings.
            "paper_only_aggressive": True,
            "allow_aggressive_live": False,
            "buying_power_utilization_pct": 0.95,
            "max_single_position_equity_pct": 0.70,
            "orders_sync_interval_seconds": 2.0,
            "flatten_before_close_minutes": 5.0,
            "liquidation_quote_max_age_seconds": 30.0,
            "liquidation_reprice_seconds": 20.0,
            "liquidation_quote_feed": "iex",
        }

    @classmethod
    def _normalize_quant_params(cls, params) -> Dict:
        defaults = cls._quant_policy_defaults()
        defaults.update({key: value for key, value in params.items() if key in defaults})
        defaults.update(strategy_mode="quant_policy", strategy_version="causal_quant_policy_v1", bar_interval="5m")
        return defaults

    def load_runner_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, encoding="utf-8") as handle:
                    saved = json.load(handle).get("strategy_params", {})
                self.strategy_params = self._normalize_quant_params(saved)
        except (OSError, ValueError, TypeError) as exc:
            self.add_log(f"Quant policy configuration unavailable: {exc}")

    def recalculate_trade_pnls(self):
        recalculate_fifo(self.trade_history)

    def is_market_open(self) -> bool:
        clock = getattr(self, "_quant_clock", {})
        return bool(clock.get("success") and clock.get("is_open"))

    def _quant_broker_snapshot(self):
        """Read orders before fresh positions so a fill cannot free a stale target.

        The old adapter silently returned cached positions on errors. Execution
        requires an authoritative read, including orders placed on earlier dates.
        """
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        account = self.adapter.get_account_summary()
        if account.get("success") is False:
            raise ValueError("Authoritative account data unavailable")
        self._load_liquidation_submissions(account)
        raw_orders = self.adapter.client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
        orders = [self._serialize_alpaca_order(order) for order in raw_orders]
        by_client = {order["client_order_id"]: order for order in orders}
        # A submission with an unknown outcome remains an unresolved broker order,
        # not an invented holding or permission to submit the same order again.
        for client_id, submission in list(self._quant_submissions.items()):
            if submission.get("resolved"):
                continue
            order = by_client.get(client_id)
            if order is None:
                try:
                    raw = self.adapter.client.get_order_by_client_id(client_id)
                    order = self._serialize_alpaca_order(raw)
                except Exception:
                    orders.append(submission)
                    continue
            if order["status"] in TERMINAL_STATUSES:
                submission.update(order)
                submission["resolved"] = True
            elif client_id not in by_client:
                orders.append(order)
        positions = []
        for position in self.adapter.client.get_all_positions():
            positions.append({
                "ticker": str(self._order_field(position, "symbol")),
                "shares": float(self._order_field(position, "qty")),
                "current_price": float(self._order_field(position, "current_price")),
                "avg_entry_price": float(self._order_field(position, "avg_entry_price")),
            })
        current = {p["ticker"]: p["shares"] for p in positions}
        for submission in self._quant_submissions.values():
            if submission.get("status") == "filled" and "opening_signed_qty" in submission:
                if current.get(submission["ticker"], 0) != submission["opening_signed_qty"]:
                    submission["position_reconciled"] = True
        self._save_liquidation_submissions()
        return orders, positions, account

    def _load_liquidation_submissions(self, account):
        from pathlib import Path
        import hashlib
        owner = str(account.get("account_number") or "")
        if not owner:
            return
        key = hashlib.sha256((owner + str(getattr(self.adapter, "base_url", ""))).encode()).hexdigest()[:20]
        if getattr(self, "_liquidation_owner", None) == key:
            return
        if getattr(self, "_liquidation_owner", None) is not None:
            self._quant_submissions = {}
            self._quant_last_bar = None
        self._liquidation_saved = None
        backend = Path(__file__).resolve().parents[2]
        path = backend / ".runtime_state" / f"liquidation-{key}.json"
        if path.exists():
            self._quant_submissions.update(json.loads(path.read_text())["submissions"])
        self._liquidation_state_file, self._liquidation_owner = path, key

    def _save_liquidation_submissions(self):
        path = getattr(self, "_liquidation_state_file", None)
        if path is None:
            return
        rows = {k: v for k, v in self._quant_submissions.items() if k.startswith("QP-EXIT-")}
        content = json.dumps({"submissions": rows}, sort_keys=True)
        if content == getattr(self, "_liquidation_saved", None):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with temporary.open("w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        self._liquidation_saved = content

    def _run_intraday_cleanup(self, now, orders, positions):
        from app.broker.intraday_liquidation import liquidation_plan
        try:
            session = self.adapter.get_liquidation_session(now)
            session = {**session, "quote_feed": self.strategy_params.get("liquidation_quote_feed", "iex")}
        except Exception as exc:
            session = {"kind": "closed", "trade_date": str(now.date()), "reason": str(exc)}
        quotes, quote_errors = {}, {}
        if session["kind"] in {"premarket", "afterhours", "overnight"}:
            for position in positions:
                symbol = position["ticker"]
                try:
                    quotes[symbol] = self.adapter.get_liquidation_quote(symbol, session)
                except Exception as exc:
                    quote_errors[symbol] = str(exc)
        if quotes:
            # Account/calendar/quote reads take time. Validate quote age against
            # a subsequent broker clock, not the older cycle-start timestamp.
            refreshed_clock = self.adapter.get_clock()
            if not refreshed_clock.get("success"):
                raise ValueError("Exchange clock unavailable after liquidation quote reads")
            now = pd.Timestamp(refreshed_clock["timestamp"])
            self._quant_clock = refreshed_clock
            session = {**self.adapter.get_liquidation_session(now),
                       "quote_feed": self.strategy_params.get("liquidation_quote_feed", "iex")}
        plan = liquidation_plan(positions, orders, quotes, now=now, session=session,
            quote_max_age_seconds=float(self.strategy_params["liquidation_quote_max_age_seconds"]),
            reprice_seconds=float(self.strategy_params["liquidation_reprice_seconds"]))
        self._quant_targets = {p["ticker"]: 0 for p in positions}
        self._quant_status = dict(state="session_flat" if plan["flat_confirmed"] else "session_close_pending",
                                 session=session, inventory=plan["inventory"], waiting=plan["waiting"],
                                 quote_errors=quote_errors, target_shares=self._quant_targets,
                                 exchange_clock=pd.Timestamp(now).isoformat(), cancellation_errors={})
        for order_id in plan["cancel"]:
            try:
                self.adapter.client.cancel_order_by_id(order_id)
            except Exception as exc:
                self._quant_status["cancellation_errors"][order_id] = type(exc).__name__
        for intent in plan["submit"]:
            base = intent["client_order_id"]
            prior = next((v for v in reversed(list(self._quant_submissions.values()))
                          if v.get("base_client_order_id") == base), None)
            if prior and (not prior.get("resolved") or (prior.get("status") == "filled" and not prior.get("position_reconciled"))):
                self._quant_status["waiting"][intent["symbol"]] = "awaiting_broker_reconciliation"
                continue
            attempt = int(prior.get("attempt", 0)) + 1 if prior else 1
            client_id = base if attempt == 1 else f"{base[:36]}-{attempt}"
            submission = dict(client_order_id=client_id, base_client_order_id=base, attempt=attempt,
                              ticker=intent["symbol"], qty=intent["quantity"], filled_qty=0,
                              side=intent["side"], type="limit", extended_hours=True,
                              limit_price=intent["limit_price"], status="submission_unknown",
                              opening_signed_qty=plan["inventory"][intent["symbol"]])
            self._quant_submissions[client_id] = submission
            # Persist the ID before sending: a timeout/restart must be reconciled, not retried blindly.
            self._save_liquidation_submissions()
            result = self.adapter.submit_limit_order(intent["symbol"], intent["quantity"], intent["side"],
                limit_price=intent["limit_price"], extended_hours=True, client_order_id=client_id,
                position_intent=intent["position_intent"])
            submission.update(order_id=result.get("order_id"), status=result.get("status") or "submission_unknown")
            if submission["status"] in TERMINAL_STATUSES:
                submission["resolved"] = True
            self._save_liquidation_submissions()
            self.add_log(f"[Intraday close] {intent['symbol']} {intent['side']} {intent['quantity']}: {submission['status']}; awaiting confirmed flat inventory.")
        self._quant_status["pending_submissions"] = [dict(v) for v in self._quant_submissions.values() if not v.get("resolved")]

    def _quant_model(self):
        from app.quant_policy import PolicyModel
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        path = os.environ.get("QUANT_POLICY_PATH") or self.strategy_params["quant_policy_path"]
        path = path if os.path.isabs(path) else os.path.join(backend_dir, path)
        modified = os.stat(path).st_mtime_ns
        if getattr(self, "_quant_model_key", None) != (path, modified):
            with open(path) as handle:
                kind = json.load(handle).get("kind")
            if kind == "calibrated_direction_holding_v1":
                from app.research.calibrated_holding import CalibratedHoldingModel
                self._quant_fitted_model = CalibratedHoldingModel.load(path)
            elif kind == "direction_holding_v1":
                from app.research.holding_policy import HoldingModel
                self._quant_fitted_model = HoldingModel.load(path)
            else:
                self._quant_fitted_model = PolicyModel.load(path)
            self._quant_model_key = (path, modified)
            self._quant_last_bar = None
        return self._quant_fitted_model

    def _execution_mutex(self):
        if not hasattr(self, "_quant_execution_lock"):
            self._quant_execution_lock = threading.RLock()
        return self._quant_execution_lock

    def _holding_l1_adjustment(self, model, weights, diagnostics, current, now, allowed, shortable, liquidation_at=None):
        """Optional learned L1 residual; incompatible data preserves base decisions."""
        directory = os.environ.get("QUANT_L1_RESIDUAL_DIR")
        snapshot = os.environ.get("QUANT_L1_SNAPSHOT_PATH")
        if not directory or not snapshot:
            diagnostics["l1_state"] = "base_only_no_configured_residual_and_snapshot"
            return weights, diagnostics
        try:
            from app.research.holding_l1 import HoldingL1Residual, packet_books, apply_residuals, base_model_contract
            with open(snapshot) as handle:
                books = packet_books(json.load(handle), now)
            models = {}
            for symbol in model.symbols:
                path = os.path.join(directory, symbol + ".json")
                if os.path.isfile(path): models[symbol] = HoldingL1Residual.load(path)
            adjustment, status = apply_residuals(models, books, now, model.symbols, base_model_contract(model))
            if any(row["state"] == "applied" for row in status.values()):
                base_curve = diagnostics.get("raw_cumulative_forecast_bps", diagnostics["cumulative_forecast_bps"])
                forecasts = {s: {h: base_curve[s][str(h*5)] / 10000
                                  for h in model.spec.horizons} for s in model.symbols}
                stamp = now.floor("5min") - pd.Timedelta(minutes=5)
                weights, diagnostics = model.allocation(forecasts, current, stamp, allowed, shortable, adjustment, liquidation_at)
            diagnostics["l1_state"] = status
        except (OSError, ValueError, TypeError, KeyError) as exc:
            diagnostics["l1_state"] = "base_only_" + type(exc).__name__
        return weights, diagnostics

    def _run_quant_policy_cycle(self):
        with self._execution_mutex():
            return self._run_quant_policy_cycle_unlocked()

    def _run_quant_policy_cycle_unlocked(self):
        from app.quant_policy import integer_targets, target_weights
        if isinstance(self.adapter, MockAlpacaAdapter):
            connection = getattr(self, "_broker_connection", {})
            self._quant_status = {"state": "unavailable", "reason": connection.get("reason", "Broker connection unavailable"),
                                  "execution_connected": False}
            return
        clock = self.adapter.get_clock()
        self._quant_clock = clock
        if not clock.get("success"):
            raise ValueError("Exchange clock unavailable")
        now = pd.Timestamp(clock["timestamp"])
        close = pd.Timestamp(clock["next_close"])
        orders, positions, account = self._quant_broker_snapshot()
        equity = float(account["equity"])
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("Positive broker equity is required to express portfolio weights")
        # Honor the existing account authorization before any broker mutation,
        # including cancellation of working orders at the session boundary.
        permitted = not self.strategy_params.get("paper_only_aggressive", True) or self.strategy_params.get("allow_aggressive_live", False) or bool(getattr(self.adapter, "is_paper", False))
        if not permitted:
            self._quant_status = {"state": "execution_not_authorized", "reason": "Existing configuration permits paper execution only"}
            return
        if not clock.get("is_open"):
            self._run_intraday_cleanup(now, orders, positions)
            return
        # Keep the existing intraday-flat mandate. The research contract executes
        # at the last 5m interval, based on the exchange calendar (early closes too).
        flatten = now >= close - pd.Timedelta(minutes=float(self.strategy_params["flatten_before_close_minutes"]))
        prices = {position["ticker"]: position["current_price"] for position in positions}
        model = None
        if flatten:
            # A still-working entry can recreate inventory after a liquidation.
            # Cancel actual broker orders first; their disappearance/terminal state
            # must be reconciled before a same-symbol close can be submitted.
            active_order_counts = {}
            for order in orders:
                if order.get("status") not in TERMINAL_STATUSES:
                    symbol = order.get("ticker")
                    active_order_counts[symbol] = active_order_counts.get(symbol, 0) + 1
            cancellation_errors = {}
            for order in orders:
                order_id = order.get("order_id")
                held = next((position["shares"] for position in positions if position["ticker"] == order.get("ticker")), 0)
                remaining = float(order.get("qty") or 0) - float(order.get("filled_qty") or 0)
                working_exit = (str(order.get("client_order_id", "")).startswith("QP-EXIT-")
                                and active_order_counts.get(order.get("ticker")) == 1
                                and 0 < remaining <= abs(held)
                                and order.get("side") == ("sell" if held > 0 else "buy"))
                if working_exit:
                    continue
                if order_id and order.get("status") not in TERMINAL_STATUSES | {"pending_cancel"}:
                    try:
                        self.adapter.client.cancel_order_by_id(order_id)
                    except Exception as exc:
                        cancellation_errors[order_id] = type(exc).__name__
            self._quant_targets = {position["ticker"]: 0 for position in positions}
            cycle_id = f"{now.date()}:session_close"
            self._quant_status = {"state": "session_close", "target_shares": self._quant_targets,
                                  "exchange_close": close.isoformat(), "cancellation_errors": cancellation_errors}
        else:
            try:
                model = self._quant_model()
                if str(model.trained_before) > str(now.tz_convert("America/New_York").date()):
                    raise ValueError("Model training cutoff is later than this trading session")
                symbols = tuple(model.symbols)
                watchlist = set(load_watchlist())
                allowed_symbols = tuple(symbol for symbol in symbols if symbol in watchlist)
                self.active_tickers = list(allowed_symbols)
                inputs = tuple(getattr(model, "input_symbols", symbols))
                frames = {symbol: closed_bars(fetch_and_prepare_data(symbol, period="5d", interval="5m"), now) for symbol in inputs}
                session_date = now.tz_convert("America/New_York").date()
                if not hasattr(model, "live_target"):
                    frames = {symbol: frame.loc[frame.index.tz_convert("America/New_York").date == session_date] for symbol, frame in frames.items()}
                timestamps = {frame.index[-1] for frame in frames.values()}
                if len(timestamps) != 1:
                    raise ValueError("The portfolio requires synchronized completed bars")
                bar = next(iter(timestamps))
                prices.update({symbol: float(frame["close"].iloc[-1]) for symbol, frame in frames.items()})
                cycle_id = f"{self._quant_model_key}:{bar.isoformat()}:{allowed_symbols}"
                if self._quant_last_bar != cycle_id:
                    current = {symbol: 0.0 for symbol in symbols}
                    for position in positions:
                        if position["ticker"] in current:
                            current[position["ticker"]] = position["shares"] * prices[position["ticker"]] / equity
                    shortable = {}
                    for symbol in symbols:
                        asset = self.adapter.client.get_asset(symbol)
                        shortable[symbol] = bool(self.strategy_params["allow_shorting"] and account.get("shorting_enabled") and self._order_field(asset, "shortable", False))
                    if hasattr(model, "live_target"):
                        liquidation_at = close - pd.Timedelta(minutes=float(self.strategy_params["flatten_before_close_minutes"]))
                        weights, diagnostics = model.live_target(frames, current, allowed=allowed_symbols,
                            shortable=shortable, as_of=now, liquidation_at=liquidation_at)
                        weights, diagnostics = self._holding_l1_adjustment(model, weights, diagnostics,
                            current, now, allowed_symbols, shortable, liquidation_at)
                        forecast_mu = {s: diagnostics["cumulative_forecast_bps"][s]["5"] / 10000 for s in symbols}
                    else:
                        forecast = model.forecast(frames)
                        forecast_mu = forecast.mu
                        indices = [symbols.index(symbol) for symbol in allowed_symbols]
                        weights = dict.fromkeys(symbols, 0.0)
                        weights.update(target_weights(
                            {symbol: forecast.mu[symbol] for symbol in allowed_symbols},
                            forecast.covariance.take(indices, axis=0).take(indices, axis=1),
                            {symbol: current[symbol] for symbol in allowed_symbols},
                            model.spec, shortable=shortable, symbols=allowed_symbols))
                        diagnostics = {"feature_family": model.spec.feature_set, "l1_contributes": False,
                                       "cost_assumption_bps": model.spec.cost_bps, "cost_verified": False}
                    self._quant_decision_diagnostics = diagnostics
                    # User account concentration settings may be tighter than the
                    # validated artifact, never wider. No extra score multiplier.
                    cap = float(self.strategy_params["max_single_position_equity_pct"])
                    weights = {symbol: max(-cap, min(cap, weight)) for symbol, weight in weights.items()}
                    self._quant_targets = integer_targets(weights, prices, equity, spec=model.spec)
                    self._quant_last_bar = cycle_id
                    self.ticker_scores = {}
                    self.ticker_directions = {symbol: "LONG" if weight > 0 else "SHORT" if weight < 0 else "FLAT" for symbol, weight in weights.items()}
                    self.intraday_opportunities = {
                        symbol: {"ticker": symbol, "direction": self.ticker_directions[symbol],
                                 "expected_return_bps": float(forecast_mu[symbol]) * 10000,
                                 "round_trip_cost_bps": 2 * model.spec.cost_bps,
                                 "cost_kind": "unverified_execution_assumption_not_broker_fee",
                                 "target_weight": weights[symbol], "bar_time": bar.isoformat(),
                                 "model": model.spec.name, "status": "model_forecast"}
                        for symbol in allowed_symbols
                    }
                self._quant_status = {"state": "ready", "model": model.spec.name,
                                      "trained_before": model.trained_before,
                                      "bar_time": bar.isoformat(), "target_shares": dict(self._quant_targets),
                                      "unmodeled_watchlist_symbols": sorted(watchlist.difference(symbols)),
                                      "decision_diagnostics": dict(getattr(self, "_quant_decision_diagnostics", {})),
                                      "gross_limit": model.spec.gross_limit}
            except Exception as exc:
                self.ticker_scores = {}
                self.intraday_opportunities = {}
                self._quant_status = {"state": "unavailable", "reason": str(exc),
                                      "inventory": positions, "inventory_policy": "Retain confirmed inventory and existing broker protective orders; close at the established intraday session boundary."}
                return
        gross_limit = float(model.spec.gross_limit) if model else 0.0
        execution_marks = {**prices, **{position["ticker"]: position["current_price"] for position in positions}}
        intents = plan_rebalance(self._quant_targets, positions, execution_marks, orders,
                                 equity=equity, buying_power=float(account["buying_power"]),
                                 gross_limit=gross_limit,
                                 buying_power_utilization=float(self.strategy_params["buying_power_utilization_pct"]),
                                 symbol_limit=min(float(model.spec.symbol_limit), float(self.strategy_params["max_single_position_equity_pct"])) if model else 0,
                                 cost_bps=float(model.spec.cost_bps) if model else 0,
                                 cycle_id=cycle_id)
        for intent in intents:
            prior = next((submission for submission in reversed(list(self._quant_submissions.values()))
                          if submission.get("base_client_order_id") == intent.client_order_id), None)
            if prior and (not prior.get("resolved") or prior.get("status") == "filled"):
                continue
            # Forecast/data work can cross the already-established closing
            # boundary. Recheck before sending so a late market order cannot
            # become an unintended next-session entry or queued market exit.
            sending_clock = self.adapter.get_clock()
            if not sending_clock.get("success"):
                raise ValueError("Exchange clock unavailable before order submission")
            sending_time = pd.Timestamp(sending_clock["timestamp"])
            sending_close = pd.Timestamp(sending_clock["next_close"])
            closing_now = sending_time >= sending_close - pd.Timedelta(minutes=float(self.strategy_params["flatten_before_close_minutes"]))
            if not sending_clock.get("is_open") or (closing_now and not flatten):
                self._quant_clock = sending_clock
                self._quant_status = {"state": "session_boundary_recheck", "clock": sending_clock["timestamp"],
                                      "reason": "Session changed during this cycle; next cycle reconciles inventory before closing"}
                return
            attempt = int(prior.get("attempt", 0)) + 1 if prior else 1
            client_id = intent.client_order_id if attempt == 1 else f"{intent.client_order_id[:36]}-{attempt}"
            submission = {"client_order_id": client_id, "base_client_order_id": intent.client_order_id,
                          "attempt": attempt, "ticker": intent.symbol,
                          "qty": intent.quantity, "filled_qty": 0, "side": intent.side,
                          "status": "submission_unknown", "limit_price": execution_marks[intent.symbol]}
            self._quant_submissions[client_id] = submission
            self._save_liquidation_submissions()
            result = self.adapter.submit_market_order(intent.symbol, intent.quantity, intent.side,
                                                      price=execution_marks[intent.symbol], client_order_id=client_id)
            submission.update(order_id=result.get("order_id"), status=result.get("status") or "submission_unknown")
            if result.get("error"):
                submission["error"] = result["error"]
            if submission["status"] in TERMINAL_STATUSES:
                submission["resolved"] = True
            self.add_log(f"[Quant policy] {intent.symbol} {intent.side} {intent.quantity}: {submission['status']}; awaiting broker fill reconciliation.")
        self._save_liquidation_submissions()
        unresolved = [dict(submission) for submission in self._quant_submissions.values() if not submission.get("resolved")]
        self._quant_status["pending_submissions"] = unresolved
        if any(submission.get("status") == "submission_unknown" for submission in unresolved):
            self._quant_status.update(state="awaiting_broker_resolution", reason="A submission has no confirmed broker outcome; its client ID is being reconciled")
        # Genuine filled quantities/prices enter the ledger through the existing
        # order reconciliation worker. Submission success never enters inventory.

    async def _run_loop(self):
        while self.is_running:
            try:
                self._run_quant_policy_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._quant_status = {"state": "unavailable", "reason": str(exc)}
                self.add_log(f"[Quant policy] Broker/data reconciliation unavailable: {exc}")
            await asyncio.sleep(float(self.strategy_params["orders_sync_interval_seconds"]))

    def __init__(self):
        self.is_running = True
        self.logs = []
        self.action_logs = []
        self.trade_history = []
        self.history_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "trade_history.json")
        self.load_trade_history()
        self.config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "runner_config.json")
        self.init_alpaca_adapter()
        self.active_tickers = WATCHLIST.copy()
        self._account_cache = None
        self._account_cache_time = 0.0
        self._positions_cache = None
        self._positions_cache_time = 0.0
        self.intraday_opportunities = {}
        self.ticker_directions = {}
        self.loop_task = None
        self.order_sync_thread = None
        self._quant_execution_lock = threading.RLock()
        self._orders_lock = threading.RLock()
        self._orders_refresh_lock = threading.Lock()
        self._orders_cache = []
        self._orders_cache_updated_at = 0.0
        self._orders_cache_error = None
        self._orders_cache_latency_ms = None

        self.strategy_params = self._quant_policy_defaults()
        self.ticker_scores = {}
        self._quant_status = {"state": "initializing"}
        self._quant_submissions = {}
        self._quant_last_bar = None
        self._quant_targets = {}
        self._loaded_strategy_version = None
        self.load_runner_config()
        self.add_log("Quant policy execution initialized; model forecasts and actual broker fills are reported separately.")
        self.start()


    def _bg_refresh_account(self):
        try:
            res = self.adapter.get_account_summary()
            if res and res.get("success") is not False:
                res["engine"] = "Python High-Speed Keep-Alive Engine"
                self._account_cache = res
                self._account_cache_time = time.time()
        except Exception as e:
            print(f"[Warning] Account refresh error: {e}")

    def get_cached_account_summary(self) -> Dict:
        now = time.time()
        if self._account_cache is not None:
            if (now - self._account_cache_time) >= 3.0:
                threading.Thread(target=self._bg_refresh_account, daemon=True).start()
            return self._account_cache
        # Initial synchronous fetch on cold startup
        self._bg_refresh_account()
        return self._account_cache or self.adapter.get_account_summary()

    def _bg_refresh_positions(self):
        try:
            res = self.adapter.get_open_positions()
            self._positions_cache = res
            self._positions_cache_time = time.time()
        except Exception:
            pass

    def get_cached_open_positions(self) -> List[Dict]:
        now = time.time()
        if self._positions_cache is not None:
            if (now - self._positions_cache_time) >= 3.0:
                threading.Thread(target=self._bg_refresh_positions, daemon=True).start()
            return self._positions_cache
        self._bg_refresh_positions()
        return self._positions_cache or []


    def save_runner_config(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "is_running": self.is_running,
                    "strategy_params": self.strategy_params,
                    "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving runner_config.json: {e}")

    def set_market_mode(self, mode: str = "AUTO_EXCHANGE") -> Dict:
        msg = "⏱️ Market hours 100% synchronized to Alpaca exchange clock (AUTO_EXCHANGE)."
        self.save_runner_config()
        self.add_log(msg)
        return {"success": True, "market_mode": "AUTO_EXCHANGE", "message": msg}

    def load_trade_history(self):
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.trade_history = data.get("trade_history", [])
                    self.recalculate_trade_pnls()
                    raw_action_logs = data.get("action_logs", [])
                    self.action_logs = [l for l in raw_action_logs if "Waiting for bar data" not in str(l) and "MU" not in str(l)]
                    raw_logs = data.get("logs", [])
                    self.logs = [l for l in raw_logs if "Waiting for bar data" not in str(l) and "MU" not in str(l)]
        except Exception as e:
            print(f"Error loading trade_history.json: {e}")


    def save_trade_history(self):
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "trade_history": self.trade_history,
                    "action_logs": self.action_logs
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving trade_history.json: {e}")

    def add_log(self, msg: str):
        est = pytz.timezone('America/New_York')
        timestamp = datetime.datetime.now(est).strftime("%Y-%m-%d %H:%M:%S EDT")
        full_msg = f"[{timestamp}] {msg}"
        try:
            print(full_msg)
        except Exception:
            try:
                print(full_msg.encode('ascii', errors='ignore').decode('ascii'))
            except Exception:
                pass
        self.logs.append(full_msg)
        if len(self.logs) > 500:
            self.logs.pop(0)

    def add_trade_action(
        self,
        action: str,
        ticker: str,
        shares: int,
        price: float,
        reason: str,
        pnl: float = 0.0,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        order_status: Optional[str] = None,
    ):
        est = pytz.timezone('America/New_York')
        now = datetime.datetime.now(est)
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

        action_emoji = {"BUY": "🟢", "SELL": "🔴", "SHORT": "🔻", "COVER": "🔼"}.get(action, "⚪")
        pnl_str = f" | PnL: {'+'if pnl>=0 else ''}{pnl:.2f} USD" if pnl != 0.0 else ""
        feed_msg = f"[{timestamp_str}] {action_emoji} [{ticker}] {action} × {shares} shs @ ${price:.2f}{pnl_str} | {reason}"

        self.action_logs.append(feed_msg)
        if len(self.action_logs) > 300:
            self.action_logs.pop(0)

        if order_id:
            existing = next(
                (trade for trade in self.trade_history if str(trade.get("order_id") or "") == str(order_id)),
                None,
            )
            if existing is not None:
                existing["reason"] = reason
                if client_order_id:
                    existing["client_order_id"] = str(client_order_id)
                self.save_trade_history()

    def get_today_summary(self) -> dict:
        est = pytz.timezone('America/New_York')
        today = datetime.datetime.now(est).strftime("%Y-%m-%d")
        
        def parse_trade_date(t):
            raw = str(t.get("date") or t.get("time") or "").strip()
            return raw[:10] if len(raw) >= 10 else ""

        today_trades = [t for t in self.trade_history if parse_trade_date(t) == today]

        closed_trades = [t for t in today_trades if t.get("matched_closing_qty", 0) > 0 and t.get("pnl_complete")]
        unknown_basis = [t for t in today_trades if t.get("unknown_basis_qty", 0) > 0]
        wins = [t for t in closed_trades if (t.get("pnl") or 0.0) > 0]
        losses = [t for t in closed_trades if (t.get("pnl") or 0.0) < 0]
        realized_pnl = sum((t.get("pnl") or 0.0) for t in closed_trades)

        unrealized_pnl = None
        try:
            open_positions = self.adapter.get_open_positions()
            unrealized_pnl = sum(pos["unrealized_pnl"] for pos in open_positions)
        except Exception:
            pass

        alpaca_official_today_pnl = None
        try:
            acc_info = self.get_cached_account_summary()
            if acc_info and acc_info.get("success") and "today_pnl" in acc_info:
                alpaca_official_today_pnl = acc_info.get("today_pnl")
        except Exception:
            pass

        total_strategy_pnl = round(realized_pnl + unrealized_pnl, 2) if unrealized_pnl is not None else None
        official_pnl = round(alpaca_official_today_pnl, 2) if alpaca_official_today_pnl is not None else None
        return {
            "date": today,
            "total_trades": len(today_trades),
            "closed_trades": len(closed_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed_trades) * 100, 1) if closed_trades else None,
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
            "total_pnl": total_strategy_pnl,
            "alpaca_official_pnl": official_pnl,
            "official_pnl_source": "broker_account" if official_pnl is not None else "unavailable",
            "unknown_basis_trades": len(unknown_basis),
            "realized_pnl_complete": not unknown_basis,
            "realized_pnl_basis": "Known FIFO closing lots before fees; incomplete opening inventory is reported separately",
            "reconciliation_difference": round(official_pnl - total_strategy_pnl, 2) if official_pnl is not None and total_strategy_pnl is not None else None,
            "best_trade": round(max((t.get("pnl", 0.0) for t in closed_trades), default=0.0), 2),
            "worst_trade": round(min((t.get("pnl", 0.0) for t in closed_trades), default=0.0), 2)
        }

    def update_tickers(self, new_tickers: List[str]):
        previous_watchlist = load_watchlist() or WATCHLIST.copy()
        cleaned = []
        for t in new_tickers:
            if t and isinstance(t, str):
                sym = t.upper().strip()
                if sym and sym not in cleaned:
                    cleaned.append(sym)
        
        removed_tickers = [t for t in previous_watchlist if t not in cleaned]
        if removed_tickers and self.adapter:
            try:
                positions_list = self.adapter.get_open_positions()
                open_tickers = {pos['ticker']: pos for pos in positions_list}
                for r_sym in removed_tickers:
                    if r_sym in open_tickers:
                        pos = open_tickers[r_sym]
                        shares = pos.get('shares', 0)
                        self.add_log(f"🗑️ [Watchlist Removal] [{r_sym}] removed from Watchlist, submitting market liquidation order to Alpaca!")
                        close_res = {}
                        if hasattr(self.adapter, "close_position"):
                            close_res = self.adapter.close_position(r_sym) or {}
                        self.add_trade_action(
                            action="SELL" if shares > 0 else "COVER",
                            ticker=r_sym,
                            shares=abs(shares),
                            price=pos.get("current_price", 0.0),
                            reason="Watchlist Removal Auto Liquidation",
                            order_id=close_res.get("order_id") or close_res.get("id"),
                            order_status=close_res.get("status") or "submitted",
                        )
            except Exception as e:
                self.add_log(f"⚠️ Watchlist removal liquidation warning: {e}")

        if set(cleaned) != set(previous_watchlist):
            self.active_tickers = cleaned
            save_watchlist(cleaned, allow_empty=True)
            self.add_log(f"🔄 Updated seed watchlist: {cleaned}")

    def close_individual_position(self, ticker: str) -> dict:
        sym = ticker.upper().strip()
        try:
            if hasattr(self.adapter, "close_position"):
                res = self.adapter.close_position(sym)
                if res.get("success"):
                    self.add_log(f"⚡ [Manual Close] Submitted force close order for {sym}")
                    self.add_trade_action(
                        action="SELL",
                        ticker=sym,
                        shares=0,
                        price=0.0,
                        reason="User Manual Force Sell/Close",
                        order_id=res.get("order_id") or res.get("id"),
                        order_status=res.get("status") or "submitted",
                    )
                    return {"success": True, "message": f"Successfully submitted close order for {sym}."}
                else:
                    return {"success": False, "error": res.get("error", f"Failed to close position for {sym}")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def init_alpaca_adapter(self):
        from app.broker.credentials import resolve_trading_credentials, CredentialConfigurationError
        self._broker_connection = {"connected": False, "credential_source": None}
        try:
            credentials = resolve_trading_credentials(os.environ)
            if credentials is None:
                self.adapter = MockAlpacaAdapter()
                self._broker_connection["reason"] = "Trading credentials unavailable; account display alone does not establish execution connectivity"
                return
            self._broker_connection.update(credentials.public_metadata())
            adapter = AlpacaAdapter(api_key=credentials.key, api_secret=credentials.secret,
                                    base_url=credentials.endpoint)
            summary = adapter.get_account_summary()
            if summary.get("success") is not True:
                raise ValueError("Broker account read failed")
            self.adapter = adapter
            self._broker_connection.update(connected=True, reason=None,
                verified_at=datetime.datetime.now(pytz.UTC).isoformat())
        except CredentialConfigurationError as exc:
            self.adapter = MockAlpacaAdapter()
            self._broker_connection["reason"] = str(exc)  # Resolver messages contain variable families, never values.
        except Exception as exc:
            self.adapter = MockAlpacaAdapter()
            self._broker_connection["reason"] = f"Broker initialization failed ({type(exc).__name__})"

    @staticmethod
    def _get_alpaca_credentials():
        from app.broker.credentials import resolve_trading_credentials, PAPER_ENDPOINT
        credentials = resolve_trading_credentials(os.environ)
        return ((credentials.key, credentials.secret, credentials.endpoint)
                if credentials else (None, None, PAPER_ENDPOINT))

    @staticmethod
    def _credential_is_configured(value: Optional[str]) -> bool:
        text = str(value or "").strip().lower()
        return bool(text) and "your_" not in text and "placeholder" not in text

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) else float(default)
        except (TypeError, ValueError):
            return float(default)


    def start(self, strategy_params: Optional[Dict] = None, tickers: Optional[List[str]] = None, **kwargs):
        if getattr(self, '_loop_thread', None) is not None and self._loop_thread.is_alive():
            self.add_log("[Warning] AI Quant Bot is already running.")
            return False

        try:
            invalidate_cache()
            self.add_log("Cleared market data cache; using the fitted research policy and broker inventory.")
        except Exception as e:
            print(f"Cache clear warning on start: {e}")
            
        if strategy_params:
            self.strategy_params = self._normalize_quant_params({**self.strategy_params, **strategy_params})

        if tickers:
            self.update_tickers(tickers)

        self.save_runner_config()
        
        self.init_alpaca_adapter()
        if self._broker_connection["connected"]:
            mode = "Paper" if self._broker_connection["is_paper"] else "Live"
            self.add_log(f"Broker {mode} account verified using {self._broker_connection['credential_source']} credentials.")
        else:
            self.add_log(f"[Execution disconnected] {self._broker_connection['reason']}")
        self.is_running = True
        self._start_order_sync_worker()
        self.add_log(f"Execution loop started across {len(self.active_tickers)} tickers; broker_connected={self._broker_connection['connected']}.")
        
        def start_background_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._run_loop())
        t = threading.Thread(target=start_background_loop, name="quant-ai-engine-loop", daemon=True)
        self._loop_thread = t
        t.start()
        return True

    @staticmethod
    def _order_field(order, field: str, default=None):
        if isinstance(order, dict):
            return order.get(field, default)
        return getattr(order, field, default)

    @staticmethod
    def _enum_text(value) -> str:
        raw = getattr(value, "value", value)
        return str(raw or "").split(".")[-1].lower()

    @staticmethod
    def _number_or_none(value):
        if value in (None, ""):
            return None
        try:
            number = float(value)
            return int(number) if number.is_integer() else number
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _timestamp_iso(value):
        if value is None:
            return None
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    @staticmethod
    def _timestamp_et(value):
        if value is None:
            return None
        est = pytz.timezone("America/New_York")
        dt = value
        if isinstance(value, str):
            try:
                dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        if not isinstance(dt, datetime.datetime):
            return None
        if dt.tzinfo is None:
            dt = est.localize(dt)
        return dt.astimezone(est)

    def _serialize_alpaca_order(self, order) -> Dict:
        submitted_at = self._order_field(order, "submitted_at")
        filled_at = self._order_field(order, "filled_at")
        updated_at = self._order_field(order, "updated_at")
        event_time = filled_at or updated_at or submitted_at
        event_et = self._timestamp_et(event_time)
        return {
            "order_id": str(self._order_field(order, "id", "")),
            "client_order_id": str(self._order_field(order, "client_order_id", "") or ""),
            "ticker": str(self._order_field(order, "symbol", "") or "").upper(),
            "side": self._enum_text(self._order_field(order, "side")),
            "type": self._enum_text(self._order_field(order, "type")),
            "status": self._enum_text(self._order_field(order, "status")),
            "time_in_force": self._enum_text(self._order_field(order, "time_in_force")),
            "position_intent": self._enum_text(self._order_field(order, "position_intent")),
            "qty": self._number_or_none(self._order_field(order, "qty")),
            "notional": self._number_or_none(self._order_field(order, "notional")),
            "filled_qty": self._number_or_none(self._order_field(order, "filled_qty")) or 0,
            "filled_avg_price": self._number_or_none(self._order_field(order, "filled_avg_price")),
            "limit_price": self._number_or_none(self._order_field(order, "limit_price")),
            "stop_price": self._number_or_none(self._order_field(order, "stop_price")),
            "extended_hours": bool(self._order_field(order, "extended_hours", False)),
            "submitted_at": self._timestamp_iso(submitted_at),
            "filled_at": self._timestamp_iso(filled_at),
            "updated_at": self._timestamp_iso(updated_at),
            "date": event_et.strftime("%Y-%m-%d") if event_et else "",
            "time": event_et.strftime("%Y-%m-%d %H:%M:%S") if event_et else "",
        }

    def _cached_orders_snapshot(self) -> Dict:
        with self._orders_lock:
            updated_at = self._orders_cache_updated_at
            interval = max(1.0, float(self.strategy_params.get("orders_sync_interval_seconds", 2.0)))
            age_seconds = max(0.0, time.time() - updated_at) if updated_at else None
            return {
                "success": updated_at > 0 and self._orders_cache_error is None,
                "connected": not isinstance(self.adapter, MockAlpacaAdapter),
                "source": "alpaca_trading_api" if not isinstance(self.adapter, MockAlpacaAdapter) else "mock",
                "orders": [dict(order) for order in self._orders_cache],
                "count": len(self._orders_cache),
                "updated_at": datetime.datetime.fromtimestamp(updated_at, tz=pytz.UTC).isoformat() if updated_at else None,
                "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
                "stale": updated_at == 0 or age_seconds > max(6.0, interval * 3.0),
                "latency_ms": self._orders_cache_latency_ms,
                "error": self._orders_cache_error,
            }

    def refresh_alpaca_orders(self) -> Dict:
        if not self.adapter or isinstance(self.adapter, MockAlpacaAdapter):
            return self._cached_orders_snapshot()
        if not self._orders_refresh_lock.acquire(blocking=False):
            snapshot = self._cached_orders_snapshot()
            snapshot["refreshing"] = True
            return snapshot

        started = time.perf_counter()
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus

            est = pytz.timezone("America/New_York")
            today_start = datetime.datetime.now(est).replace(hour=0, minute=0, second=0, microsecond=0)
            request_kwargs = {
                "status": QueryOrderStatus.ALL,
                "limit": 500,
                "after": today_start,
                "nested": True,
            }
            try:
                from alpaca.trading.enums import Sort
                request_kwargs["direction"] = Sort.DESC
            except (ImportError, AttributeError):
                pass

            req = GetOrdersRequest(**request_kwargs)
            raw_orders = self.adapter.client.get_orders(filter=req)
            orders = [self._serialize_alpaca_order(order) for order in (raw_orders or [])]
            orders.sort(key=lambda order: order.get("submitted_at") or "", reverse=True)
            latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
            with self._orders_lock:
                self._orders_cache = orders
                self._orders_cache_updated_at = time.time()
                self._orders_cache_error = None
                self._orders_cache_latency_ms = latency_ms
            return self._cached_orders_snapshot()
        except Exception as exc:
            with self._orders_lock:
                self._orders_cache_error = f"{type(exc).__name__}: {exc}"
            return self._cached_orders_snapshot()
        finally:
            self._orders_refresh_lock.release()

    def _start_order_sync_worker(self):
        if isinstance(self.adapter, MockAlpacaAdapter):
            return
        if self.order_sync_thread and self.order_sync_thread.is_alive():
            return

        def sync_worker():
            while self.is_running and not isinstance(self.adapter, MockAlpacaAdapter):
                cycle_started = time.monotonic()
                snapshot = self.refresh_alpaca_orders()
                if snapshot.get("success"):
                    self.sync_alpaca_orders_to_history(snapshot=snapshot)
                interval = max(1.0, min(10.0, float(self.strategy_params.get("orders_sync_interval_seconds", 2.0))))
                time.sleep(max(0.25, interval - (time.monotonic() - cycle_started)))

        self.order_sync_thread = threading.Thread(
            target=sync_worker,
            name="alpaca-order-sync",
            daemon=True,
        )
        self.order_sync_thread.start()

    def _broker_action(self, order: Dict) -> str:
        intent = str(order.get("position_intent") or "").lower()
        client_id = str(order.get("client_order_id") or "").upper()
        side = str(order.get("side") or "").lower()
        if intent in ("sto", "sell_to_open"):
            return "SHORT"
        if intent in ("btc", "buy_to_close"):
            return "COVER"
        if intent in ("stc", "sell_to_close"):
            return "SELL"
        if intent in ("bto", "buy_to_open"):
            return "BUY"
        if "ENTRY" in client_id:
            return "SHORT" if side == "sell" else "BUY"
        if "EXIT" in client_id or "-TP" in client_id:
            return "COVER" if side == "buy" else "SELL"
        return "BUY" if side == "buy" else "SELL"

    def _find_provisional_trade(self, order: Dict):
        order_time = self._timestamp_et(order.get("submitted_at") or order.get("filled_at"))
        action = self._broker_action(order)
        side_actions = {"BUY", "PYRAMID_BUY", "COVER", "PARTIAL_COVER"} if order.get("side") == "buy" else {"SELL", "PARTIAL_SELL", "SHORT"}
        best = None
        best_delta = None
        for trade in reversed(self.trade_history):
            if trade.get("order_id"):
                continue
            if trade.get("ticker") != order.get("ticker") or trade.get("action") not in side_actions:
                continue
            try:
                if abs(float(trade.get("shares", 0)) - float(order.get("filled_qty", 0))) > 1e-6:
                    continue
            except (TypeError, ValueError):
                continue
            trade_time = self._timestamp_et(trade.get("time"))
            delta = abs((order_time - trade_time).total_seconds()) if order_time and trade_time else 999999
            if delta <= 300 and (best_delta is None or delta < best_delta):
                best = trade
                best_delta = delta
        if best is not None and action in ("SHORT", "COVER"):
            best["action"] = action
            best["action_cn"] = action
        return best

    def sync_alpaca_orders_to_history(self, snapshot: Optional[Dict] = None, force_refresh: bool = False):
        if not self.adapter or isinstance(self.adapter, MockAlpacaAdapter):
            return {"success": True, "added": 0, "updated": 0}
        try:
            if force_refresh or snapshot is None:
                snapshot = self.refresh_alpaca_orders()
            if not snapshot or not snapshot.get("success"):
                return {"success": False, "error": (snapshot or {}).get("error", "Order snapshot unavailable")}

            existing_by_id = {
                str(trade.get("order_id")): trade
                for trade in self.trade_history
                if trade.get("order_id")
            }
            added_count = 0
            updated_count = 0
            for order in snapshot.get("orders", []):
                qty = self._number_or_none(order.get("filled_qty")) or 0
                price = self._number_or_none(order.get("filled_avg_price")) or 0
                if qty <= 0 or price <= 0:
                    continue
                order_id = str(order.get("order_id") or "")
                if not order_id:
                    continue
                action = self._broker_action(order)
                record = existing_by_id.get(order_id)
                is_new_record = False
                if record is None:
                    record = self._find_provisional_trade(order)
                if record is None:
                    record = {}
                    self.trade_history.append(record)
                    added_count += 1
                    is_new_record = True

                before = dict(record)
                record.update({
                    "order_id": order_id,
                    "client_order_id": order.get("client_order_id", ""),
                    "order_status": order.get("status", ""),
                    "source": "alpaca_trading_api",
                    "broker_side": order.get("side", ""),
                    "broker_action": action,
                    "broker_filled_qty": qty,
                    "date": order.get("date", ""),
                    "time": order.get("time", ""),
                    "action": record.get("action") or action,
                    "action_cn": record.get("action_cn") or action,
                    "ticker": order.get("ticker", ""),
                    "shares": qty,
                    "price": price,
                    "pnl": float(record.get("pnl", 0.0) or 0.0),
                    "reason": record.get("reason") or "Alpaca Broker Confirmed Fill",
                })
                existing_by_id[order_id] = record
                if not is_new_record and record != before:
                    updated_count += 1

            if added_count or updated_count:
                self.recalculate_trade_pnls()
                self.trade_history.sort(key=lambda trade: trade.get("time", ""))
                self.save_trade_history()
                if added_count:
                    self.add_log(f"📥 Synced {added_count} new fills from Alpaca API, orders and local ledger aligned.")
            return {"success": True, "added": added_count, "updated": updated_count}
        except Exception as exc:
            print(f"Sync Alpaca orders warning: {exc}")
            return {"success": False, "error": str(exc)}

    def archive_to_hf_dataset(self, keep_days: int = 2) -> dict:
        try:
            from huggingface_hub import HfApi, hf_hub_download
            token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_HUB_TOKEN")
            repo_id = "Ypeng12/quant-ai-trade-history"
            api = HfApi(token=token) if token else HfApi()
            api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
            
            est = pytz.timezone('America/New_York')
            now_est = datetime.datetime.now(est)
            valid_dates = {(now_est - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(keep_days)}
            
            recent_trades = []
            older_trades = []
            for t in self.trade_history:
                d = (t.get("date") or (t.get("time", "")[:10] if t.get("time") else "")).strip()
                if d in valid_dates:
                    recent_trades.append(t)
                else:
                    older_trades.append(t)
            
            if not older_trades:
                return {"success": True, "message": "No older historical trades require archiving; local ledger is lean.", "archived_count": 0}
                
            dataset_trades = []
            try:
                local_dl = hf_hub_download(repo_id=repo_id, filename="historical_trades_archive.json", repo_type="dataset", token=token)
                with open(local_dl, 'r', encoding='utf-8') as f:
                    dataset_trades = json.load(f).get("trade_history", [])
            except Exception:
                dataset_trades = []
                
            existing_ids = {t.get("order_id") or f"{t.get('ticker')}-{t.get('time')}" for t in dataset_trades}
            added = 0
            for ot in older_trades:
                uid = ot.get("order_id") or f"{ot.get('ticker')}-{ot.get('time')}"
                if uid not in existing_ids:
                    dataset_trades.append(ot)
                    existing_ids.add(uid)
                    added += 1
                    
            dataset_trades.sort(key=lambda x: x.get("time", ""))
            temp_file = os.path.join(os.path.dirname(self.history_file), "temp_hf_archive.json")
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump({"trade_history": dataset_trades}, f, ensure_ascii=False, indent=2)
                
            api.upload_file(
                path_or_fileobj=temp_file,
                path_in_repo="historical_trades_archive.json",
                repo_id=repo_id,
                repo_type="dataset"
            )
            if os.path.exists(temp_file):
                os.remove(temp_file)

            msg = f"📦 Successfully uploaded {added} historical trades to Hugging Face Dataset ({repo_id})!"
            self.add_log(msg)
            return {"success": True, "message": msg, "archived_count": added, "local_remaining": len(self.trade_history)}
        except Exception as e:
            err_msg = f"HF Dataset archive failed: {str(e)}"
            self.add_log(f"⚠️ {err_msg}")
            return {"success": False, "error": err_msg}

    def stop(self):
        if not self.is_running:
            self.add_log("[Notice] AI Quant Bot is paused in standby mode.")
            return False
        self.is_running = False
        if self.loop_task:
            self.loop_task.cancel()
            self.loop_task = None
        self.save_runner_config()
        self.add_log("🤖 [AI Engine Reload] Configuration saved, background worker ready.")
        return True

    def toggle(self, strategy_params: Optional[Dict] = None, tickers: Optional[List[str]] = None) -> Dict:
        if self.is_running:
            self.stop()
            return {"status": "stopped", "is_running": False, "message": "Manually stopped AI Quant Trading Bot"}
        else:
            self.start(strategy_params=strategy_params, tickers=tickers)
            return {"status": "started", "is_running": True, "message": "Manually started AI Quant Trading Bot"}

    def submit_extended_hours_order(self, symbol: str, qty: int, side: str, limit_price: float) -> Dict:
        with self._execution_mutex():
            return self._submit_extended_hours_order_locked(symbol, qty, side, limit_price)

    def _submit_extended_hours_order_locked(self, symbol: str, qty: int, side: str, limit_price: float) -> Dict:
        try:
            permitted = (not self.strategy_params.get("paper_only_aggressive", True)
                         or self.strategy_params.get("allow_aggressive_live", False)
                         or bool(getattr(self.adapter, "is_paper", False)))
            if not permitted:
                return {"success": False, "error": "Existing configuration permits paper execution only"}
            clock = self.adapter.get_clock()
            if not clock.get("success"):
                return {"success": False, "error": "Broker clock unavailable."}
            closing_only = not clock.get("is_open") or pd.Timestamp(clock["timestamp"]) >= pd.Timestamp(clock["next_close"]) - pd.Timedelta(minutes=float(self.strategy_params["flatten_before_close_minutes"]))
            intent = None
            if closing_only:
                orders, positions, _ = self._quant_broker_snapshot()
                held = next((p["shares"] for p in positions if p["ticker"] == symbol.upper()), 0)
                closing_side = "sell" if held > 0 else "buy"
                if not math.isfinite(float(qty)) or not 0 < float(qty) <= abs(held) or side.lower() != closing_side:
                    return {"success": False, "error": "日内模式盘外仅可平仓：数量和方向必须减少实际持仓，不能开仓或反手。"}
                if any(o.get("ticker") == symbol.upper() and o.get("status") not in TERMINAL_STATUSES for o in orders):
                    return {"success": False, "error": "该股票已有未完成订单，请先核对或撤单，避免重复平仓。"}
                intent = "sell_to_close" if held > 0 else "buy_to_close"
            if hasattr(self.adapter, "submit_limit_order"):
                res = self.adapter.submit_limit_order(symbol, qty, side, limit_price=limit_price, extended_hours=True, position_intent=intent)
            else:
                return {"success": False, "error": "Extended-hours limit orders are unavailable on this broker connection."}
                
            if res.get("success"):
                action_type = "BUY" if side.lower() == "buy" else "SELL"
                self.add_log(f"🌙 [Extended-Hours Order] Submitted [{symbol}] {action_type} {qty} shs @ ${limit_price:.2f} (Extended-Hours Active)")
                self.add_trade_action(
                    action_type,
                    symbol,
                    qty,
                    limit_price,
                    f"Extended-Hours Limit Order @ ${limit_price:.2f}",
                    order_id=res.get("order_id") or res.get("id"),
                    order_status=res.get("status") or "submitted",
                )
            return res
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_status(self) -> Dict:
        orders_snapshot = self._cached_orders_snapshot()
        return {
            "is_running": self.is_running,
            "execution_connection": dict(getattr(self, "_broker_connection", {"connected": False})),
            "market_mode": "AUTO_EXCHANGE",
            "is_market_open": self.is_market_open(),
            "ticker_scores": self.ticker_scores,
            "ticker_directions": self.ticker_directions,
            "intraday_opportunities": sorted(
                self.intraday_opportunities.values(),
                key=lambda item: abs(item.get("expected_return_bps", 0.0)),
                reverse=True,
            ),
            "monitored_tickers": self.active_tickers,
            "strategy_params": self.strategy_params,
            "quant_policy": self._quant_status,
            "logs_count": len(self.logs),
            "orders": orders_snapshot["orders"],
            "orders_meta": {
                key: value
                for key, value in orders_snapshot.items()
                if key != "orders"
            }
        }

    def get_live_orders(self, force_refresh: bool = False) -> Dict:
        return self.refresh_alpaca_orders() if force_refresh else self._cached_orders_snapshot()


    def run_eod_reflection(self) -> Dict:
        """Produce ledger attribution without mutating a fitted research policy."""
        try:
            self.recalculate_trade_pnls()
            day = datetime.datetime.now(pytz.timezone("America/New_York")).date().isoformat()
            rows = [row for row in self.trade_history if str(row.get("date") or row.get("time") or "")[:10] == day]
            closed = [row for row in rows if row.get("matched_closing_qty", 0) > 0 and row.get("pnl_complete")]
            attribution = {
                "date": day, "total_trades": len(closed),
                "total_pnl": round(sum(row["pnl"] for row in closed), 2),
                "win_rate_%": 100 * sum(row["pnl"] > 0 for row in closed) / len(closed) if closed else None,
                "unknown_basis_trades": sum(row.get("unknown_basis_qty", 0) > 0 for row in rows),
                "basis": "Known-basis FIFO realized PnL, before fees; not broker account PnL",
                "policy_updated": False,
                "next_research_step": "Refit and compare candidates on prior sessions through the shared causal research pipeline",
            }
            report_dir = os.path.abspath(os.path.join(os.path.dirname(self.history_file), "..", "reports", "quant_research_20260913"))
            os.makedirs(report_dir, exist_ok=True)
            report_path = os.path.join(report_dir, f"ledger_attribution_{day}.json")
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump(attribution, handle, indent=2, ensure_ascii=False)
            return {"success": True, "report_path": report_path, "attribution": attribution}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def sync_to_huggingface(self) -> Dict:
        """Uploads full master trade_history.json and daily partitions to HuggingFace Dataset repository (Ypeng12/quant-ai-trade-history)."""
        try:
            from data.sync_full_history_to_hf import sync_full_history_to_hf
            self.add_log("☁️ [HF Auto-Sync] Pushing master dataset to HuggingFace (Ypeng12/quant-ai-trade-history)...")
            sync_full_history_to_hf()
            self.add_log("✅ [HF Auto-Sync] Remote Hugging Face Dataset synchronized successfully!")
            return {"success": True, "message": "Synced to HuggingFace Dataset (Ypeng12/quant-ai-trade-history)"}
        except Exception as e:
            err_msg = f"⚠️ [HF Auto-Sync Error] {str(e)}"
            self.add_log(err_msg)
            return {"success": False, "error": str(e)}
