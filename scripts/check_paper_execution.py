#!/usr/bin/env python3
"""Read-only paper connection, model, forecast and liquidation preflight.

Does not import/construct LiveTradingRunner, start workers, change Space secrets,
or send/cancel/replace orders. Forecast diagnostics use an explicit historical
decision time and CURRENT account inventory; they are not a historical backtest.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def preflight(env_file, model_path, forecast_at=None, watchlist_path=None):
    from dotenv import load_dotenv
    import pandas as pd
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest
    from app.broker.credentials import resolve_trading_credentials
    from app.broker.alpaca_adapter import AlpacaAdapter
    from app.broker.intraday_liquidation import liquidation_plan
    from app.broker.research_execution import closed_bars
    from app.quant_policy import PolicyModel, integer_targets, target_weights

    if env_file:
        load_dotenv(env_file)
    credentials = resolve_trading_credentials(os.environ)
    if credentials is None or not credentials.is_paper:
        raise ValueError("This diagnostic requires configured Alpaca Paper credentials")
    adapter = AlpacaAdapter(api_key=credentials.key, api_secret=credentials.secret, base_url=credentials.endpoint)
    account = adapter.get_account_summary()
    clock = adapter.get_clock()
    if account.get("success") is not True or clock.get("success") is not True:
        raise ValueError("Broker account or exchange clock unavailable")
    now = pd.Timestamp(clock["timestamp"])
    positions = [dict(ticker=p.symbol, shares=float(p.qty), current_price=float(p.current_price))
                 for p in adapter.client.get_all_positions()]
    raw_orders = adapter.client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
    orders = []
    for order in raw_orders:
        def value(name):
            raw = getattr(order, name, None)
            return getattr(raw, "value", raw)
        orders.append(dict(order_id=str(order.id), client_order_id=value("client_order_id"), ticker=order.symbol,
            side=value("side"), type=value("type"), status=value("status"), qty=float(order.qty or 0),
            filled_qty=float(order.filled_qty or 0), position_intent=value("position_intent"),
            extended_hours=bool(order.extended_hours), limit_price=float(order.limit_price or 0),
            submitted_at=order.submitted_at.isoformat() if order.submitted_at else None,
            updated_at=order.updated_at.isoformat() if order.updated_at else None))
    model = PolicyModel.load(model_path)
    if model.trained_before > str(now.tz_convert("America/New_York").date()):
        raise ValueError("Model training cutoff is in the future")
    report = dict(checked_at=now.isoformat(), mode="paper_read_only_preflight",
        credentials=credentials.public_metadata(), account_connected=True, equity=float(account["equity"]),
        account_fingerprint=hashlib.sha256(str(account.get("account_number", "")).encode()).hexdigest(),
        market_is_open=bool(clock["is_open"]), positions=positions, open_orders_count=len(orders),
        broker_order_mutations=0, cloud_configuration_changed=False,
        model=dict(path=str(model_path), sha256=hashlib.sha256(Path(model_path).read_bytes()).hexdigest(),
                   name=model.spec.name, feature_count=len(model.feature_names), symbols=list(model.symbols),
                   trained_before=model.trained_before, assumed_one_way_cost_bps=model.spec.cost_bps))
    session = adapter.get_liquidation_session(now)
    quotes, quote_errors = {}, {}
    for position in positions:
        symbol = position["ticker"]
        try:
            quotes[symbol] = adapter.get_liquidation_quote(symbol, session)
        except Exception as exc:
            quote_errors[symbol] = type(exc).__name__
    report["liquidation"] = dict(session=session, quotes=quotes, quote_errors=quote_errors,
        plan=liquidation_plan(positions, orders, quotes, now=now, session=session))
    if forecast_at is not None:
        decision = pd.Timestamp(forecast_at)
        if decision.tzinfo is None or decision > now or model.trained_before > str(decision.tz_convert("America/New_York").date()):
            raise ValueError("Forecast diagnostic requires a past timezone-aware decision after the training cutoff")
        # Importing app.config calls load_watchlist(), which can overwrite the
        # local watchlist from the broker. This diagnostic must not do that.
        watchlist_path = Path(watchlist_path or ROOT / "backend/watchlist.json")
        watchlist = {str(s).strip().upper() for s in json.loads(watchlist_path.read_text())}
        from app.data_manager import fetch_and_prepare_data
        frames, errors = {}, {}
        for symbol in model.symbols:
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    frame = fetch_and_prepare_data(symbol, period="5d", interval="5m")
                frames[symbol] = closed_bars(frame, decision)
                local = frames[symbol].index.tz_convert("America/New_York")
                frames[symbol] = frames[symbol].loc[local.date == decision.tz_convert("America/New_York").date()]
            except Exception as exc:
                errors[symbol] = type(exc).__name__
        report["forecast_diagnostic"] = dict(decision_time=decision.isoformat(),
            data_source="existing_runner_fetch_and_prepare_data", errors=errors,
            watchlist_source=str(watchlist_path), watchlist=sorted(watchlist),
            scope="historical decision bars with current account inventory; no orders and not a backtest")
        if not errors:
            forecast = model.forecast(frames)
            params = json.loads((ROOT / "backend/runner_config.json").read_text())["strategy_params"]
            allowed = tuple(symbol for symbol in model.symbols if symbol in watchlist)
            prices = {symbol: float(frame.close.iloc[-1]) for symbol, frame in frames.items()}
            current = dict.fromkeys(model.symbols, 0.0)
            for position in positions:
                if position["ticker"] in current:
                    current[position["ticker"]] = position["shares"] * prices[position["ticker"]] / account["equity"]
            shortable = {symbol: bool(params.get("allow_shorting", True) and account["shorting_enabled"]
                                     and adapter.client.get_asset(symbol).shortable) for symbol in allowed}
            indices = [model.symbols.index(symbol) for symbol in allowed]
            weights = dict.fromkeys(model.symbols, 0.0)
            weights.update(target_weights({s: forecast.mu[s] for s in allowed},
                forecast.covariance.take(indices, axis=0).take(indices, axis=1),
                {s: current[s] for s in allowed}, model.spec, shortable=shortable, symbols=allowed))
            cap = float(params.get("max_single_position_equity_pct", model.spec.symbol_limit))
            weights = {s: max(-cap, min(cap, w)) for s, w in weights.items()}
            report["forecast_diagnostic"].update(component_state="ready",
                bar_times={s: frame.index[-1].isoformat() for s, frame in frames.items()},
                expected_return_bps={s: float(v) * 10000 for s, v in forecast.mu.items()}, target_weights=weights,
                target_shares=integer_targets(weights, prices, account["equity"], spec=model.spec),
                unmodeled_watchlist_symbols=sorted(watchlist.difference(model.symbols)))
        else:
            report["forecast_diagnostic"]["component_state"] = "unavailable"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--model", type=Path, default=ROOT / "reports/quant_research_20260913/selected_policy.json")
    parser.add_argument("--forecast-at", help="Past decision timestamp, for example 2026-09-14T15:50:00-04:00")
    parser.add_argument("--watchlist", type=Path, help="Read this local symbol list without importing app.config")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = preflight(args.env_file, args.model, args.forecast_at, args.watchlist)
    text = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(text)
    print(text)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "preflight_failed", "error_type": type(exc).__name__, "broker_order_mutations": 0}))
        raise SystemExit(1)
