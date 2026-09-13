"""Causal portfolio replay of the *same* signed-return policy used by live_runner.

An integer-share cash ledger is maintained across bars and sessions. A signal
uses a completed five-minute bar and may fill at the next bar's open. The
precommitted 15:55 liquidation fills at that bar's open. There are no implicit
constant-weight returns, same-bar fills, synthetic data, or broker calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from .causal_week_replay import NY, prepare_sessions


@dataclass(frozen=True)
class ExecutionConfig:
    starting_equity: float = 100_000.0
    slippage_bps: float = 2.0
    commission_bps: float = 0.0
    gross_limit: float = 0.95
    symbol_limit: float = 0.70

    def __post_init__(self) -> None:
        values = (self.starting_equity, self.slippage_bps, self.commission_bps,
                  self.gross_limit, self.symbol_limit)
        if not all(np.isfinite(values)) or self.starting_equity <= 0:
            raise ValueError("Execution values must be finite and equity positive")
        if min(self.slippage_bps, self.commission_bps) < 0:
            raise ValueError("Execution costs must be nonnegative")
        if self.slippage_bps + self.commission_bps >= 1_000:
            raise ValueError("Unsupported cost level")
        if not 0 < self.symbol_limit <= self.gross_limit <= 1:
            raise ValueError("Require 0 < symbol_limit <= gross_limit <= 1")


def complete_universe(
    frames: Mapping[str, pd.DataFrame], requested_dates: list[str],
) -> tuple[dict[str, dict[str, pd.DataFrame]], list[str], list[dict[str, Any]]]:
    """Require every requested day and symbol, rejecting rather than substituting."""
    sessions, coverage = {}, []
    for symbol, frame in frames.items():
        sessions[symbol], rows = prepare_sessions(frame, requested_dates)
        coverage.extend(dict(symbol=symbol, **r) for r in rows)
    if not sessions:
        raise ValueError("At least one symbol is required")
    common = sorted(set.intersection(*(set(s) for s in sessions.values())))
    missing = sorted(set(requested_dates).difference(common))
    if missing:
        raise ValueError(f"Requested sessions missing/incomplete in universe: {missing}")
    return sessions, common, coverage


class ShareLedger:
    """Net cash, signed shares, execution costs and exact marked attribution.

    Short-sale cash does not create buying power: additions must independently
    satisfy gross/equity and per-symbol/equity constraints after their costs.
    Price movement can carry an existing position beyond a limit; this is
    measured and disclosed, and never treated as free rebalance capacity.
    """

    def __init__(self, symbols: list[str], config: ExecutionConfig,
                 starting_equity: float | None = None):
        self.symbols = tuple(symbols)
        self.config = config
        self.cash = float(starting_equity if starting_equity is not None else config.starting_equity)
        self.initial_equity = self.cash
        self.shares = {s: 0 for s in self.symbols}
        self.symbol_cash = {s: 0.0 for s in self.symbols}
        self.costs = 0.0
        self.turnover_dollars = 0.0
        self.fills: list[dict[str, Any]] = []
        self.marks: list[dict[str, Any]] = []
        self.peak = self.cash
        self.max_drawdown = 0.0

    def state(self, prices: Mapping[str, float]) -> dict[str, Any]:
        values = {s: self.shares[s] * float(prices[s]) for s in self.symbols}
        equity = self.cash + sum(values.values())
        if not np.isfinite(equity) or equity <= 0:
            raise ValueError("Insolvent or invalid portfolio path")
        return {
            "cash": self.cash, "equity": equity,
            "gross_dollars": sum(abs(v) for v in values.values()),
            "net_dollars": sum(values.values()),
            "gross_exposure": sum(abs(v) for v in values.values()) / equity,
            "net_exposure": sum(values.values()) / equity,
            "weights": {s: values[s] / equity for s in self.symbols},
            "symbol_pnl": {s: self.symbol_cash[s] + values[s] for s in self.symbols},
        }

    def mark(self, prices: Mapping[str, float], timestamp: pd.Timestamp,
             phase: str, date: str, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        state = self.state(prices)
        self.peak = max(self.peak, state["equity"])
        self.max_drawdown = min(self.max_drawdown, state["equity"] / self.peak - 1)
        record = {"date": date, "timestamp": timestamp.isoformat(), "phase": phase,
                  **{k: v for k, v in state.items() if not isinstance(v, dict)},
                  "costs_to_date": self.costs, "turnover_dollars_to_date": self.turnover_dollars,
                  "drawdown": state["equity"] / self.peak - 1}
        for s in self.symbols:
            record[f"{s}_shares"] = self.shares[s]
            record[f"{s}_price"] = float(prices[s])
            record[f"{s}_weight"] = state["weights"][s]
            record[f"{s}_pnl"] = state["symbol_pnl"][s]
        record.update(extra or {})
        self.marks.append(record)
        return state

    def _fill(self, symbol: str, delta: int, prices: Mapping[str, float],
              timestamp: pd.Timestamp, signal_time: pd.Timestamp | None,
              date: str, reason: str) -> None:
        if not delta:
            return
        reference = float(prices[symbol])
        slip = abs(delta) * reference * self.config.slippage_bps / 10_000
        commission = abs(delta) * reference * self.config.commission_bps / 10_000
        fill_price = reference * (1 + np.sign(delta) * self.config.slippage_bps / 10_000)
        cash_change = -delta * fill_price - commission
        self.cash += cash_change
        self.symbol_cash[symbol] += cash_change
        self.shares[symbol] += int(delta)
        self.costs += slip + commission
        self.turnover_dollars += abs(delta) * reference
        state = self.mark(prices, timestamp, "after_fill", date)
        self.fills.append({
            "date": date, "fill_time": timestamp.isoformat(),
            "signal_data_cutoff": signal_time.isoformat() if signal_time is not None else None,
            "symbol": symbol, "quantity": int(delta), "side": "buy" if delta > 0 else "sell",
            "reference_price": reference, "fill_price": fill_price,
            "slippage_cost": slip, "commission_cost": commission,
            "cost": slip + commission, "notional": abs(delta) * reference,
            "shares_after": self.shares[symbol], "cash_after": self.cash,
            "equity_after": state["equity"], "gross_exposure_after": state["gross_exposure"],
            "net_exposure_after": state["net_exposure"], "reason": reason,
        })

    def _feasible_addition(self, symbol: str, delta: int, prices: Mapping[str, float]) -> bool:
        state = self.state(prices)
        cost = abs(delta) * prices[symbol] * (
            self.config.slippage_bps + self.config.commission_bps) / 10_000
        equity_after = state["equity"] - cost
        new_shares = self.shares[symbol] + delta
        gross_after = state["gross_dollars"] + (
            abs(new_shares) - abs(self.shares[symbol])) * prices[symbol]
        cash_after = self.cash - delta * prices[symbol] - cost
        return bool(
            equity_after > 0 and cash_after >= -1e-8
            and gross_after <= self.config.gross_limit * equity_after + 1e-8
            and abs(new_shares) * prices[symbol] <= self.config.symbol_limit * equity_after + 1e-8
        )

    def execute_targets(self, target_shares: Mapping[str, int], prices: Mapping[str, float],
                        timestamp: pd.Timestamp, signal_time: pd.Timestamp | None,
                        date: str, reason: str = "policy_rebalance") -> None:
        """Close/reduce all existing positions before opening/increasing any.

        Target shares are fixed before fills. Only infeasible *additions* are
        clipped, using a monotone integer search; there is no force-one-share
        fallback or cash-from-shorts multiplier. Symbol order is predeclared.
        """
        desired = {s: int(target_shares.get(s, 0)) for s in self.symbols}
        # Cash-releasing long reductions first, then short covers; all reductions
        # precede any additions. Covers are allowed even if gaps breach a limit.
        for positive in (True, False):
            for s in self.symbols:
                old, target = self.shares[s], desired[s]
                if not old or (old > 0) != positive:
                    continue
                if target == 0 or np.sign(target) != np.sign(old):
                    delta = -old
                elif abs(target) < abs(old):
                    delta = target - old
                else:
                    continue
                self._fill(s, delta, prices, timestamp, signal_time, date, reason)
        for s in self.symbols:
            delta = desired[s] - self.shares[s]
            if not delta:
                continue
            direction, wanted = int(np.sign(delta)), abs(delta)
            lo, hi = 0, wanted
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if self._feasible_addition(s, direction * mid, prices):
                    lo = mid
                else:
                    hi = mid - 1
            self._fill(s, direction * lo, prices, timestamp, signal_time, date, reason)


TargetFunction = Callable[[int, dict[str, float]], Mapping[str, float]]


def replay_day(
    ledger: ShareLedger, bars: Mapping[str, pd.DataFrame], date: str,
    target_function: TargetFunction | None,
    integer_sizer: Callable[[Mapping[str, float], Mapping[str, float], float], Mapping[str, int]],
    opening_weights: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Mark real shares, use completed-bar decisions, liquidate at 15:55 open."""
    symbols = ledger.symbols
    index = bars[symbols[0]].index
    if any(not bars[s].index.equals(index) for s in symbols):
        raise ValueError("All portfolio bars must share the exact timestamps")
    if len(index) != 78 or index[-1].tz_convert(NY).strftime("%H:%M") != "15:55":
        raise ValueError("A complete 78-bar regular session is required")
    if any(ledger.shares.values()):
        raise ValueError("Prior session was not liquidated")
    start_equity, start_costs = ledger.cash, ledger.costs
    start_turnover, start_fills, start_marks = ledger.turnover_dollars, len(ledger.fills), len(ledger.marks)
    start_symbol_cash = ledger.symbol_cash.copy()
    pending = None
    signal_time = None
    for i, timestamp in enumerate(index):
        prices = {s: float(bars[s]["Open"].iloc[i]) for s in symbols}
        state = ledger.mark(prices, timestamp, "open_before_orders", date)
        liquidation = i == len(index) - 1
        if liquidation:
            ledger.execute_targets({s: 0 for s in symbols}, prices, timestamp, None, date,
                                   reason="scheduled_1555_liquidation")
        elif i == 0 and opening_weights is not None:
            desired = integer_sizer(opening_weights, prices, state["equity"])
            ledger.execute_targets(desired, prices, timestamp, None, date, reason="precommitted_opening_benchmark")
        elif pending is not None:
            ledger.execute_targets(pending, prices, timestamp, signal_time, date)
        close_prices = {s: float(bars[s]["Close"].iloc[i]) for s in symbols}
        close_time = timestamp + pd.Timedelta(minutes=5)
        state = ledger.mark(close_prices, close_time, "bar_close", date)
        pending = None
        if target_function is not None and i < len(index) - 2:
            target_weights = dict(target_function(i, state["weights"]))
            if set(target_weights).difference(symbols) or not all(np.isfinite(list(target_weights.values()))):
                raise ValueError("Policy returned unknown symbols or invalid weights")
            # Match live: completed-bar prices/equity fix the integer intent.
            # The next-open gap can constrain an addition, never improve sizing.
            pending = integer_sizer(target_weights, close_prices, state["equity"])
            signal_time = close_time
    if any(ledger.shares.values()):
        raise AssertionError("End-of-session holdings must be flat")
    marks = ledger.marks[start_marks:]
    equity_values = np.asarray([start_equity] + [m["equity"] for m in marks])
    drawdown = float(np.min(equity_values / np.maximum.accumulate(equity_values) - 1))
    symbol_pnl = {s: ledger.symbol_cash[s] - start_symbol_cash[s] for s in symbols}
    net_pnl = ledger.cash - start_equity
    if not np.isclose(sum(symbol_pnl.values()), net_pnl, atol=1e-7):
        raise AssertionError("Per-symbol PnL does not reconcile with portfolio cash")
    result = {
        "date": date, "starting_equity": start_equity, "ending_equity": ledger.cash,
        "net_pnl": net_pnl, "net_return": net_pnl / start_equity,
        "costs": ledger.costs - start_costs, "gross_pnl": net_pnl + ledger.costs - start_costs,
        "turnover_dollars": ledger.turnover_dollars - start_turnover,
        "turnover_equity_multiple": (ledger.turnover_dollars - start_turnover) / start_equity,
        "fill_count": len(ledger.fills) - start_fills, "max_drawdown": drawdown,
        "max_gross_exposure": max(m["gross_exposure"] for m in marks),
        "max_abs_net_exposure": max(abs(m["net_exposure"]) for m in marks),
        "max_symbol_exposure": max(abs(m[f"{s}_weight"]) for m in marks for s in symbols),
        "min_cash": min(m["cash"] for m in marks), "ending_cash": ledger.cash,
        "ending_gross_exposure": 0.0, "ending_net_exposure": 0.0,
    }
    day_fills = ledger.fills[start_fills:]
    for s in symbols:
        result[f"{s}_net_pnl"] = symbol_pnl[s]
        result[f"{s}_costs"] = sum(f["cost"] for f in day_fills if f["symbol"] == s)
        result[f"{s}_fill_count"] = sum(f["symbol"] == s for f in day_fills)
    return result


def summarize(daily: list[dict[str, Any]], marks: list[dict[str, Any]]) -> dict[str, Any]:
    if not daily:
        raise ValueError("No evaluated sessions")
    dates = {d["date"] for d in daily}
    equity = [daily[0]["starting_equity"]] + [m["equity"] for m in marks if m["date"] in dates]
    values = np.asarray(equity, dtype=float)
    return {
        "start": daily[0]["date"], "end": daily[-1]["date"], "sessions": len(daily),
        "starting_equity": daily[0]["starting_equity"],
        "ending_equity": daily[-1]["ending_equity"],
        "net_pnl": sum(d["net_pnl"] for d in daily),
        "net_return": daily[-1]["ending_equity"] / daily[0]["starting_equity"] - 1,
        "gross_pnl": sum(d["gross_pnl"] for d in daily),
        "costs": sum(d["costs"] for d in daily),
        "turnover_dollars": sum(d["turnover_dollars"] for d in daily),
        "fill_count": sum(d["fill_count"] for d in daily),
        "max_drawdown": float(np.min(values / np.maximum.accumulate(values) - 1)),
        "max_gross_exposure": max(d["max_gross_exposure"] for d in daily),
        "max_symbol_exposure": max(d["max_symbol_exposure"] for d in daily),
        "profitable_sessions": int(sum(d["net_pnl"] > 0 for d in daily)),
    }


def fixed_order_cost_stress(
    base_fills: list[dict[str, Any]], base_marks: list[dict[str, Any]],
    config: ExecutionConfig,
) -> dict[str, Any]:
    """Reprice exact recorded quantities, never reselect or rescale exposures.

    This is a fixed-orderflow sensitivity, not a second executable simulation.
    It flags any gross/cash feasibility breach under the reduced equity.
    """
    extra_costs: list[tuple[str, float, str]] = []
    total = 0.0
    by_date: dict[str, dict[str, Any]] = {}
    for fill in base_fills:
        new_cost = fill["notional"] * (config.slippage_bps + config.commission_bps) / 10_000
        extra = new_cost - fill["cost"]
        total += extra
        extra_costs.append((fill["fill_time"], extra, fill["symbol"]))
        row = by_date.setdefault(fill["date"], {"extra_cost": 0.0, "new_cost": 0.0})
        row["extra_cost"] += extra
        row["new_cost"] += new_cost
        row[f'{fill["symbol"]}_extra_cost'] = row.get(f'{fill["symbol"]}_extra_cost', 0.0) + extra
    # Match after-fill records sequentially, because several fills can share a
    # timestamp. This avoids attributing later fills' fees to a pre-order mark.
    fill_index = 0
    accumulated_extra = 0.0
    stressed_equity, breaches = [config.starting_equity], 0
    for mark in base_marks:
        if mark["phase"] == "after_fill":
            accumulated_extra += extra_costs[fill_index][1]
            fill_index += 1
        eq = mark["equity"] - accumulated_extra
        cash = mark["cash"] - accumulated_extra
        stressed_equity.append(eq)
        symbols = [k[:-7] for k in mark if k.endswith("_weight")]
        largest = max((abs(mark[f"{s}_shares"] * mark[f"{s}_price"]) for s in symbols), default=0)
        if (eq <= 0 or cash < -1e-8 or mark["gross_dollars"] > config.gross_limit * eq + 1e-8
                or largest > config.symbol_limit * eq + 1e-8):
            breaches += 1
    values = np.asarray(stressed_equity)
    return {
        "kind": "fixed_recorded_integer_orderflow_cost_sensitivity",
        "slippage_bps_per_side": config.slippage_bps,
        "commission_bps_per_side": config.commission_bps,
        "starting_equity": config.starting_equity,
        "ending_equity": float(values[-1]),
        "net_pnl": float(values[-1] - config.starting_equity),
        "net_return": float(values[-1] / config.starting_equity - 1),
        "extra_cost": total, "costs": sum(r["new_cost"] for r in by_date.values()),
        "max_drawdown": float(np.min(values / np.maximum.accumulate(values) - 1)),
        "constraint_breach_marks_including_market_drift": breaches,
        "requires_feasibility_review": breaches > 0,
        "same_quantities_and_reference_prices": True,
        "daily": [{"date": day, **values} for day, values in sorted(by_date.items())],
    }
