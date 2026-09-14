"""Inventory-only liquidation plans. No alpha, broker mutation or price forecasts."""
from collections import defaultdict
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import math

import pandas as pd

from .research_execution import TERMINAL_STATUSES


def extended_session(now, calendar):
    """Use broker session boundaries, including half days and holiday weekends."""
    now = pd.Timestamp(now)
    if pd.isna(now) or now.tzinfo is None:
        raise ValueError("Timezone-aware broker time required")
    now = now.tz_convert("America/New_York")
    for row in calendar:
        day = str(row["date"])[:10]
        def at(value):
            value = str(value)
            if ":" not in value:
                value = value[:2] + ":" + value[2:]
            return pd.Timestamp(f"{day} {value}", tz="America/New_York")
        start, end = at(row["open"]), at(row["close"])
        pre, post = at(row["session_open"]), at(row["session_close"])
        overnight_start = post - pd.DateOffset(days=1)
        for kind, left, right in [("overnight", overnight_start, pre),
                                   ("premarket", pre, start), ("regular", start, end),
                                   ("afterhours", end, post)]:
            if left <= now < right:
                return {"kind": kind, "trade_date": day, "until": right.isoformat()}
    return {"kind": "closed", "trade_date": str(now.date())}


def quote_limit(quote, side, now, max_age_seconds):
    """Opposite-side quote, rounded to a valid tick; never use a stale position mark."""
    bid, ask = float(quote["bid_price"]), float(quote["ask_price"])
    timestamp, now = pd.Timestamp(quote["timestamp"]), pd.Timestamp(now)
    if side not in {"buy", "sell"}:
        raise ValueError("Explicit closing side required")
    if pd.isna(timestamp) or pd.isna(now) or timestamp.tzinfo is None or now.tzinfo is None:
        raise ValueError("Quote timestamps must be timezone aware")
    age = (now - timestamp).total_seconds()
    if not (math.isfinite(bid + ask) and 0 < bid <= ask) or not -5 <= age <= max_age_seconds:
        raise ValueError("Fresh uncrossed quote unavailable")
    price = ask if side == "buy" else bid
    tick = Decimal("0.01") if price >= 1 else Decimal("0.0001")
    return float(Decimal(str(price)).quantize(tick, rounding=ROUND_CEILING if side == "buy" else ROUND_FLOOR))


def liquidation_plan(positions, orders, quotes, *, now, session,
                     quote_max_age_seconds=30, reprice_seconds=20):
    """Cancel entries first; a pending/unknown order prevents another close of its symbol."""
    held = {p["ticker"]: float(p["shares"]) for p in positions if float(p["shares"]) != 0}
    if any(not math.isfinite(qty) for qty in held.values()):
        raise ValueError("Non-finite broker inventory")
    working = defaultdict(list)
    for order in orders:
        if order.get("status") not in TERMINAL_STATUSES:
            working[order.get("ticker") or order.get("symbol")].append(order)
    cancel, submit, waiting = [], [], {}
    eligible = session["kind"] in {"premarket", "afterhours", "overnight"}
    for symbol in sorted(set(held) | set(working)):
        qty = held.get(symbol, 0)
        side = "sell" if qty > 0 else "buy"
        limit = None
        if qty and eligible:
            try:
                limit = quote_limit(quotes[symbol], side, now, quote_max_age_seconds)
            except (KeyError, TypeError, ValueError, OverflowError):
                waiting[symbol] = "awaiting_fresh_quote"
        for order in working[symbol]:
            remaining = float(order.get("qty") or 0) - float(order.get("filled_qty") or 0)
            safe_exit = (len(working[symbol]) == 1 and qty and 0 < remaining <= abs(qty)
                         and order.get("side") == side
                         and (str(order.get("client_order_id", "")).startswith("QP-EXIT-")
                              or order.get("position_intent") == ("sell_to_close" if qty > 0 else "buy_to_close"))
                         and order.get("type") == "limit" and order.get("extended_hours") is True)
            if safe_exit and limit is not None:
                old_price = float(order.get("limit_price") or 0)
                # Replace only an unmarketable close after the configured refresh interval.
                changed = old_price < limit if side == "buy" else old_price > limit
                stamp = order.get("updated_at") or order.get("submitted_at")
                try:
                    age = (pd.Timestamp(now) - pd.Timestamp(stamp)).total_seconds() if stamp else math.inf
                    if not math.isfinite(age):
                        age = math.inf
                except (TypeError, ValueError):
                    age = math.inf
                if changed and age >= reprice_seconds:
                    safe_exit = False
            if not safe_exit and order.get("order_id") and order.get("status") != "pending_cancel":
                cancel.append(order["order_id"])
            waiting[symbol] = "awaiting_order_reconciliation"
        if qty and not working[symbol] and eligible and limit is not None:
            fingerprint = f"{session['trade_date']}:{symbol}:{qty}"
            submit.append(dict(symbol=symbol, quantity=abs(qty), side=side, limit_price=limit,
                               position_intent="sell_to_close" if qty > 0 else "buy_to_close",
                               client_order_id="QP-EXIT-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:36]))
        elif qty and not eligible:
            waiting[symbol] = "awaiting_eligible_session"
    return dict(cancel=cancel, submit=submit, waiting=waiting,
                flat_confirmed=not held and not working, inventory=held)
