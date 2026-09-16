"""Read-only daily broker fills and observed prices for the price replay UI.

No order submission or runner import. Account-scoped evidence stays in ignored
runtime storage; unavailable inventory/basis is never replaced by a zero.
"""
from __future__ import annotations

from collections import deque
from decimal import Decimal
from pathlib import Path
import copy
import hashlib
import json
import math
import os
import re
import threading
import time

import exchange_calendars as xcals
import pandas as pd
import requests

from ..broker.credentials import BrokerCredentials, normalize_endpoint, resolve_trading_credentials

NY = "America/New_York"
ROOT = Path(__file__).resolve().parents[2] / ".runtime_state" / "broker_replay"


def stamp(value):
    value = pd.Timestamp(value)
    if value.tzinfo is None:
        raise ValueError("Timezone-aware evidence required")
    return value.tz_convert(NY)


def display_credentials(env):
    # Follow the account shown by the dashboard when it has an explicit pair.
    if env.get("ALPACA_ACCOUNT_API_KEY") or env.get("ALPACA_ACCOUNT_SECRET_KEY"):
        key, secret = env.get("ALPACA_ACCOUNT_API_KEY"), env.get("ALPACA_ACCOUNT_SECRET_KEY")
        if not key or not secret:
            raise ValueError("Incomplete account display credentials")
        return BrokerCredentials(key, secret, normalize_endpoint(env.get("ALPACA_ACCOUNT_BASE_URL")), "ACCOUNT_DISPLAY")
    return resolve_trading_credentials(env)


def save_private(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, allow_nan=False))
    temporary.chmod(0o600)
    temporary.replace(path)


def session_dates(events, now):
    dates = [stamp(row["transaction_time"]).date().isoformat() for row in events]
    start = min(dates) if dates else (now - pd.Timedelta(days=30)).date().isoformat()
    calendar = xcals.get_calendar("XNYS", start=start, end=now.date().isoformat())
    return sorted(set(dates) | {str(day.date()) for day in calendar.sessions}, reverse=True)


def build_broker_payload(symbol, day, snapshot, market, *, now):
    """Pure accounting. Prices are raw, and explicit broker fees are unknown."""
    now = stamp(now)
    start = pd.Timestamp(day, tz=NY)
    end = min(start + pd.Timedelta(days=1), now)
    raw = {}
    for row in snapshot["events"]:
        if row.get("symbol") == symbol:
            raw[row["id"]] = row
    events = sorted(raw.values(), key=lambda row: (stamp(row["transaction_time"]), row["id"]))
    net = Decimal(0)
    for row in events:
        qty, price = Decimal(str(row["qty"])), Decimal(str(row["price"]))
        if not qty.is_finite() or not price.is_finite() or qty <= 0 or price <= 0 or row["side"] not in {"buy", "sell", "sell_short"}:
            raise ValueError("Invalid fill activity")
        net += qty if row["side"] == "buy" else -qty
    actual = sum((Decimal(str(row["qty"])) for row in snapshot["positions"] if row["symbol"] == symbol), Decimal(0))
    reconciled = bool(snapshot.get("history_complete")) and abs(net - actual) <= Decimal("0.00000001")
    position, opening = Decimal(0), Decimal(0)
    lots = deque()
    fills = []
    for row in events:
        when = stamp(row["transaction_time"])
        quantity, price = Decimal(str(row["qty"])), Decimal(str(row["price"]))
        sign = 1 if row["side"] == "buy" else -1
        before = position
        remaining = quantity
        realized = Decimal(0)
        while remaining and lots and lots[0][0] != sign:
            lot = lots[0]
            amount = min(remaining, lot[1])
            realized += (price - lot[2]) * lot[0] * amount
            remaining -= amount
            lot[1] -= amount
            if not lot[1]:
                lots.popleft()
        if remaining:
            lots.append([sign, remaining, price])
        position += sign * quantity
        if when < start:
            opening = position
            continue
        if when >= end:
            continue
        if not reconciled:
            segments = [("BUY" if sign == 1 else "SELL", quantity)]
        else:
            closing = min(quantity, abs(before)) if before * sign < 0 else Decimal(0)
            segments = []
            if closing:
                segments.append(("C" if sign == 1 else "S", closing))
            if quantity > closing:
                segments.append(("B" if sign == 1 else "X", quantity - closing))
        segment_position = before
        for index, (action, amount) in enumerate(segments):
            segment_position += sign * amount
            fills.append(dict(time=when.isoformat(), action=action, shares=float(amount), quantity=float(sign * amount),
                              price=float(price), reference_price=float(price),
                              shares_after=float(segment_position) if reconciled else None,
                              commission_cost=None, assumed_cost=None,
                              realized_pnl=float(realized) if reconciled and action in {"C", "S"} else (0.0 if reconciled else None),
                              fill_id=row["id"], segment=index, order_id=row.get("order_id"),
                              source="alpaca_fill_activity", broker_side=row["side"]))
    bars = []
    total_pv = total_v = 0.0
    for row in sorted(market.get("bars", []), key=lambda row: row["t"]):
        opened = stamp(row["t"])
        available = opened + pd.Timedelta(minutes=5)
        if opened.date().isoformat() != day or available > now:
            continue
        o, h, l, c, v = (float(row[key]) for key in ("o", "h", "l", "c", "v"))
        if not all(math.isfinite(x) for x in (o, h, l, c, v)) or min(o, h, l, c) <= 0 or v < 0:
            raise ValueError("Invalid observed bar")
        total_pv += (h + l + c) / 3 * v
        total_v += v
        bars.append(dict(time=available.isoformat(), bar_open=opened.isoformat(), open=o, high=h, low=l,
                         close=c, volume=v, vwap=total_pv / total_v if total_v else None))
    prior_close = market.get("previous_close")
    basis_known = reconciled and (opening == 0 or prior_close is not None)
    # Day PnL is mark-to-market from previous regular close, not lifetime FIFO
    # and not account equity change. Trade cash uses actual fills with no bps.
    cash = -float(opening) * float(prior_close or 0)
    shares = float(opening)
    timeline = [(stamp(bar["time"]), 0, index, bar) for index, bar in enumerate(bars)]
    timeline += [(stamp(fill["time"]), 1, index, fill) for index, fill in enumerate(fills)]
    marks = []
    for when, kind, _, record in sorted(timeline, key=lambda item: item[:3]):
        if kind == 1:
            shares += record["quantity"]
            cash -= record["quantity"] * record["price"]
            price = record["price"]
        else:
            price = record["close"]
        marks.append(dict(time=when.isoformat(), shares=shares if reconciled else None,
                          pnl=cash + shares * price if basis_known else None,
                          valuation_price=price, price_kind="broker_fill" if kind else "completed_bar"))
    earliest = min([stamp(row["time"]) for row in fills + bars] + [start + pd.Timedelta(hours=9, minutes=30)])
    latest = max([stamp(row["time"]) for row in fills + bars] + [start + pd.Timedelta(hours=16)])
    session_open = start + pd.Timedelta(hours=9, minutes=30)
    minutes = lambda value: (value - session_open).total_seconds() / 60
    is_today = day == now.date().isoformat()
    observed = stamp(snapshot["observed_at"])
    return dict(success=True, ticker=symbol, date=day, variant="broker", variants=[],
                available_dates=session_dates(snapshot["events"], now), source_label="Alpaca Paper 券商确认成交" if snapshot["is_paper"] else "Alpaca 券商确认成交",
                is_simulated=False, is_paper=snapshot["is_paper"], is_live=is_today,
                as_of=now.isoformat() if is_today else latest.isoformat(),
                fills_updated_at=observed.isoformat(), market_updated_at=market.get("observed_at"),
                last_bar_end=bars[-1]["time"] if bars else None,
                stale=bool(snapshot.get("stale")) or (now - observed).total_seconds() > 60,
                partial=is_today and now < start + pd.Timedelta(hours=20),
                starting_equity=None, cost_bps=None, actual_fees_verified=False,
                opening_shares=float(opening) if reconciled else None, inventory_reconciled=reconciled,
                previous_close=prior_close, pnl_basis="当日成交现金流＋持仓市值变化（以前收为基准，实际费用未核）",
                mark_timing="event_time_after_fill", chart_start=minutes(earliest), chart_end=minutes(latest),
                price_source=market.get("source"), market_error=market.get("error"),
                bars=bars, fills=fills, marks=marks,
                summary=dict(net_pnl=marks[-1]["pnl"] if marks else (0 if reconciled and opening == 0 else None),
                             gross_pnl=None, cost=None, fill_count=len(fills),
                             broker_fill_count=len({row["fill_id"] for row in fills}),
                             ending_shares=shares if reconciled else None,
                             realized_fifo_pnl=sum(row["realized_pnl"] for row in fills) if reconciled else None))


class BrokerReplayService:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.market_lock = threading.Lock()
        self.key = None
        self.state = None
        self.running = False
        self.checked = 0
        self.error = None
        self.prices = {}

    @staticmethod
    def scope(credentials):
        return hashlib.sha256((credentials.endpoint + credentials.key).encode()).hexdigest()

    def snapshot(self, env=None):
        credentials = display_credentials(os.environ if env is None else env)
        if credentials is None:
            return None, "账户凭证未配置", None
        scope = self.scope(credentials)
        with self.lock:
            if self.key != scope:
                self.key, self.state, self.checked = scope, None, 0
                path = self.root / scope / "account_fills.json"
                if path.exists():
                    try:
                        self.state = json.loads(path.read_text())
                        self.state["stale"] = True
                    except (OSError, ValueError):
                        pass
            if not self.running and time.monotonic() - self.checked >= 15:
                self.running = True
                threading.Thread(target=self.refresh, args=(credentials, scope), daemon=True).start()
            return copy.deepcopy(self.state), self.error or "正在同步券商逐笔成交", credentials

    def refresh(self, credentials, scope=None):
        scope = scope or self.scope(credentials)
        try:
            with self.lock:
                prior = copy.deepcopy(self.state) if self.key == scope else None
            today = pd.Timestamp.now(tz=NY).date().isoformat()
            full = not prior or str(prior.get("full_refresh_date")) != today
            events = {} if full else {row["id"]: row for row in prior["events"]}
            params = dict(direction="asc", page_size=100)
            if events:
                params["after"] = (max(stamp(row["transaction_time"]) for row in events.values()) - pd.Timedelta(days=1)).isoformat()
            tokens = set()
            with requests.Session() as session:
                session.headers.update({"APCA-API-KEY-ID": credentials.key, "APCA-API-SECRET-KEY": credentials.secret})
                while True:
                    response = session.get(credentials.endpoint + "/v2/account/activities/FILL", params=params, timeout=15)
                    response.raise_for_status()
                    page = response.json()
                    if not isinstance(page, list):
                        raise ValueError("Invalid activity response")
                    for row in page:
                        events[row["id"]] = row
                    if len(page) < 100:
                        break
                    token = page[-1]["id"]
                    if token in tokens:
                        raise ValueError("Repeated activity page")
                    tokens.add(token)
                    params["page_token"] = token
                response = session.get(credentials.endpoint + "/v2/positions", timeout=15)
                response.raise_for_status()
                positions = response.json()
                if not isinstance(positions, list):
                    raise ValueError("Invalid inventory response")
            state = dict(events=list(events.values()), positions=[{"symbol": row["symbol"], "qty": row["qty"]} for row in positions],
                         history_complete=True, is_paper=credentials.is_paper, observed_at=pd.Timestamp.now(tz=NY).isoformat(),
                         full_refresh_date=today if full else prior["full_refresh_date"], stale=False)
            save_private(self.root / scope / "account_fills.json", state)
            with self.lock:
                if self.key in (None, scope):
                    self.key, self.state, self.error = scope, state, None
        except Exception as exc:
            with self.lock:
                if self.key in (None, scope):
                    self.error = "券商同步暂不可用：" + type(exc).__name__
                    if self.state is not None:
                        self.state["stale"] = True
        finally:
            with self.lock:
                self.running = False
                self.checked = time.monotonic()

    def market(self, symbol, day, credentials, now):
        today = now.date().isoformat()
        feed = "iex" if day == today and now.hour < 21 else "sip"
        key = (symbol, day, feed)
        with self.market_lock:
            cached = self.prices.get(key)
            if cached and (day != today or time.monotonic() - cached[0] < 15):
                return copy.deepcopy(cached[1])
            path = self.root / "market" / day / f"{symbol}_{feed}.json"
            if day != today and path.exists():
                result = json.loads(path.read_text())
                self.prices[key] = (time.monotonic(), result)
                return result
            previous = cached[1] if cached else None
            try:
                start = pd.Timestamp(day, tz=NY)
                calendar = xcals.get_calendar("XNYS", start=(start - pd.Timedelta(days=15)).date(), end=start.date())
                if calendar.is_session(pd.Timestamp(day)):
                    prior_session = calendar.previous_session(pd.Timestamp(day))
                else:
                    prior_session = calendar.date_to_session(pd.Timestamp(day), direction="previous")
                prior_start = calendar.session_open(prior_session).tz_convert(NY)
                prior_end = calendar.session_close(prior_session).tz_convert(NY)
                finish = min(start + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1), now)
                params = dict(symbols=symbol, timeframe="5Min", start=prior_start.isoformat(), end=finish.isoformat(),
                              feed=feed, adjustment="raw", sort="asc", limit=10000)
                rows, tokens = [], set()
                with requests.Session() as session:
                    session.headers.update({"APCA-API-KEY-ID": credentials.key, "APCA-API-SECRET-KEY": credentials.secret})
                    while True:
                        response = session.get("https://data.alpaca.markets/v2/stocks/bars", params=params, timeout=15)
                        response.raise_for_status()
                        payload = response.json()
                        if "bars" not in payload:
                            raise ValueError("Missing stock bars")
                        rows.extend((payload["bars"] or {}).get(symbol, []))
                        token = payload.get("next_page_token")
                        if not token:
                            break
                        if token in tokens:
                            raise ValueError("Repeated bar page")
                        tokens.add(token)
                        params["page_token"] = token
                unique = {row["t"]: row for row in rows}
                prior_close = next((float(row["c"]) for row in unique.values() if stamp(row["t"]) == prior_end - pd.Timedelta(minutes=5)), None)
                result = dict(bars=[row for row in unique.values() if stamp(row["t"]).date().isoformat() == day],
                              previous_close=prior_close, source=f"Alpaca {feed.upper()} · 已完成5分钟行情", feed=feed,
                              observed_at=now.isoformat(), error=None)
                save_private(path, result)
                self.prices[key] = (time.monotonic(), result)
                return result
            except Exception as exc:
                result = copy.deepcopy(previous) if previous else dict(bars=[], previous_close=None, source=f"Alpaca {feed.upper()}")
                result["error"] = "行情同步暂不可用：" + type(exc).__name__
                return result

    def payload(self, ticker, date="", *, now=None, env=None):
        now = stamp(now) if now is not None else pd.Timestamp.now(tz=NY)
        symbol = str(ticker).strip().upper()
        day = date or now.date().isoformat()
        if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", symbol) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("Invalid symbol/date")
        if pd.Timestamp(day).date() > now.date():
            raise ValueError("Future date")
        snapshot, message, credentials = self.snapshot(env)
        if snapshot is None:
            return dict(success=False, status="syncing", ticker=symbol, date=day, error=message,
                        available_dates=[now.date().isoformat()], bars=[], fills=[], marks=[])
        market = self.market(symbol, day, credentials, now)
        return build_broker_payload(symbol, day, snapshot, market, now=now)


BROKER_REPLAY = BrokerReplayService()
