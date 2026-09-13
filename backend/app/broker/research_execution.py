"""Broker-independent accounting and execution for the shared research policy.

No signal scores live here. A target is a desired inventory; an accepted order is
not inventory. The broker's open orders and positions remain authoritative.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import math

import pandas as pd


TERMINAL_STATUSES = frozenset({"filled", "canceled", "cancelled", "expired", "rejected", "replaced"})
BUY_ACTIONS = frozenset({"BUY", "PYRAMID_BUY", "TIER2_ADD_BUY", "COVER", "PARTIAL_COVER", "BUY_TO_COVER", "BUY_TO_CLOSE"})
SELL_ACTIONS = frozenset({"SELL", "PARTIAL_SELL", "SHORT", "PYRAMID_SHORT", "TIER2_ADD_SHORT", "SELL_SHORT", "SELL_TO_OPEN", "SELL_TO_CLOSE"})
CLOSE_ACTIONS = frozenset({"SELL", "PARTIAL_SELL", "COVER", "PARTIAL_COVER", "BUY_TO_COVER", "BUY_TO_CLOSE", "SELL_TO_CLOSE"})


def closed_bars(frame: pd.DataFrame, now) -> pd.DataFrame:
    """Keep completed, start-labelled 5m regular-session bars; never relabel 1m."""
    if frame is None or frame.empty:
        raise ValueError("Five-minute bars unavailable")
    result = frame.copy()
    if not isinstance(result.index, pd.DatetimeIndex) or result.index.tz is None:
        raise ValueError("Five-minute bars require a timezone-aware DatetimeIndex")
    result.columns = [str(column).lower() for column in result.columns]
    required = ["open", "high", "low", "close", "volume"]
    if not set(required).issubset(result.columns):
        raise ValueError("OHLCV schema incomplete")
    if result.index.has_duplicates:
        raise ValueError("Duplicate bar timestamps")
    result = result.loc[:, required].sort_index()
    local = result.index.tz_convert("America/New_York")
    if ((local.minute % 5 != 0) | (local.second != 0)).any():
        raise ValueError("Expected start-labelled five-minute bars")
    now = pd.Timestamp(now)
    if now.tzinfo is None:
        raise ValueError("Clock must be timezone aware")
    minute = local.hour * 60 + local.minute
    result = result.loc[(minute >= 570) & (minute < 960) & (result.index + pd.Timedelta(minutes=5) <= now)]
    if result.empty or result.index[-1].tz_convert("America/New_York").date() != now.tz_convert("America/New_York").date():
        raise ValueError("No completed current-session bar")
    expected = now.floor("5min") - pd.Timedelta(minutes=5)
    if result.index[-1] != expected:
        raise ValueError(f"Stale bars: last {result.index[-1]}, expected {expected}")
    if not result.apply(pd.to_numeric, errors="coerce").notna().all().all():
        raise ValueError("Non-numeric or missing OHLCV")
    return result.astype(float)


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: str
    quantity: float
    reducing: bool
    client_order_id: str


def plan_rebalance(targets, positions, prices, open_orders, *, equity,
                   buying_power, gross_limit, buying_power_utilization, cycle_id,
                   symbol_limit=None, cost_bps=0):
    """Whole-share deltas; reductions settle before additions or reversals.

    Pending orders reserve exposure, including orders outside the model universe.
    A submitted reduction never releases budget before a broker position update.
    """
    symbol_limit = gross_limit if symbol_limit is None else symbol_limit
    if not all(math.isfinite(float(x)) and float(x) >= 0 for x in (equity, buying_power, gross_limit, buying_power_utilization, symbol_limit, cost_bps)):
        raise ValueError("Account or risk settings are non-finite")
    current = {str(p["ticker"]): float(p["shares"]) for p in positions}
    marked = {str(p["ticker"]): float(p.get("current_price") or prices.get(p["ticker"], 0)) for p in positions}
    marked = {**prices, **marked}
    if any(not math.isfinite(float(p)) or p <= 0 for p in marked.values()):
        raise ValueError("A held position has no valid mark")
    pending_symbols, reserved = set(), 0.0
    for order in open_orders:
        if str(order.get("status", "")).lower() in TERMINAL_STATUSES:
            continue
        symbol = str(order.get("ticker") or order.get("symbol") or "")
        pending_symbols.add(symbol)
        unfilled = max(0.0, float(order.get("qty") or 0) - float(order.get("filled_qty") or 0))
        price = float(order.get("limit_price") or marked.get(symbol) or 0)
        if unfilled and price <= 0:
            raise ValueError(f"Cannot reserve exposure for pending {symbol}")
        # Conservative reservation: broker buying power already accounts for orders,
        # and reserving them again avoids relying on asynchronous snapshot timing.
        reserved += unfilled * price if unfilled else float(order.get("notional") or 0)
    gross = sum(abs(qty) * marked[symbol] for symbol, qty in current.items())
    cost = float(cost_bps) / 10000
    budget_equity = float(equity) - reserved * cost
    budget_gross = gross + reserved
    budget_buying_power = float(buying_power) * float(buying_power_utilization) - reserved * (1 + cost)
    reductions, additions = [], []
    for symbol, target in sorted(targets.items()):
        if symbol in pending_symbols:
            continue
        old = current.get(symbol, 0.0)
        target = int(target)
        delta = target - old
        if not delta:
            continue
        reducing = old != 0 and (target * old <= 0 or abs(target) < abs(old))
        # Closing an existing side must finish before opening the opposite side.
        if reducing and old * target < 0:
            delta = -old
        # The model opens whole shares, but inherited fractional broker inventory
        # must be reducible in full, without truncation into an unmanaged residue.
        qty = abs(delta) if reducing else math.floor(abs(delta))
        if qty == 0:
            continue
        side = "buy" if delta > 0 else "sell"
        fingerprint = f"{cycle_id}:{symbol}:{side}:{qty}:{reducing}:{old}:{target}"
        client_id = ("QP-EXIT-" if reducing else "QP-ENTRY-") + hashlib.sha256(fingerprint.encode()).hexdigest()[:36]
        item = OrderIntent(symbol, side, qty, reducing, client_id)
        (reductions if reducing else additions).append(item)
    if reductions:
        return sorted(reductions, key=lambda item: (item.side != "sell", item.symbol))
    result = []
    for item in additions:
        price = float(marked[item.symbol])
        gross_room = (float(gross_limit) * budget_equity - budget_gross) / (1 + float(gross_limit) * cost)
        held_notional = abs(current.get(item.symbol, 0)) * price
        symbol_room = (float(symbol_limit) * budget_equity - held_notional) / (1 + float(symbol_limit) * cost)
        available = max(0.0, min(gross_room, symbol_room, budget_buying_power / (1 + cost)))
        qty = min(item.quantity, math.floor(available / price))
        if qty <= 0:
            continue
        budget_equity -= qty * price * cost
        budget_gross += qty * price
        budget_buying_power -= qty * price * (1 + cost)
        fingerprint = f"{cycle_id}:{item.symbol}:{item.side}:{qty}:False:{current.get(item.symbol, 0.0)}:{int(targets[item.symbol])}"
        client_id = "QP-ENTRY-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:36]
        result.append(OrderIntent(item.symbol, item.side, qty, False, client_id))
    return result


def recalculate_fifo(trades):
    """Cross-day FIFO with short entries, fractional fills and explicit uncertainty.

    Mutates only accounting fields; exchange side, action, and actual fill size are
    retained. Unknown opening basis is disclosed, never manufactured at zero cost.
    """
    queues = defaultdict(deque)
    for trade in sorted(trades, key=lambda row: row.get("time", "")):
        action = str(trade.get("action") or "").upper()
        trade.setdefault("original_action", action)
        status = str(trade.get("order_status") or "").lower()
        if status and status not in {"filled", "partially_filled"} and not trade.get("broker_filled_qty"):
            trade.update(pnl=0.0, pnl_complete=False, accounting_status="unconfirmed_order")
            continue
        qty = float(trade.get("broker_filled_qty", trade.get("shares", 0)) or 0)
        price = float(trade.get("price") or 0)
        symbol = str(trade.get("ticker") or "")
        if not symbol or not math.isfinite(qty + price) or qty <= 0 or price <= 0:
            continue
        raw_side = str(trade.get("broker_side") or trade.get("side") or "").lower()
        side = 1 if raw_side == "buy" or (not raw_side and action in BUY_ACTIONS) else -1 if raw_side == "sell" or (not raw_side and action in SELL_ACTIONS) else 0
        if not side:
            continue
        trade.setdefault("broker_side", "buy" if side > 0 else "sell")
        remaining, pnl, matched_qty = qty, 0.0, 0.0
        queue = queues[symbol]
        while remaining > 1e-10 and queue and queue[0][0] != side:
            entry = queue[0]
            matched = min(remaining, entry[1])
            pnl += (price - entry[2]) * entry[0] * matched
            matched_qty += matched
            entry[1] -= matched
            remaining -= matched
            if entry[1] <= 1e-10:
                queue.popleft()
        unknown = 0.0
        if remaining > 1e-10:
            if action in CLOSE_ACTIONS:
                unknown = remaining
            else:
                queue.append([side, remaining, price])
        trade.update(pnl=round(pnl, 2), pnl_complete=unknown == 0,
                     matched_closing_qty=matched_qty, unknown_basis_qty=unknown,
                     accounting_status="unknown_opening_basis" if unknown else "known_basis")
    return trades
