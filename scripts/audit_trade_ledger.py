"""Read-only FIFO audit of archived fills; never imports the live trading app.

The archive's action names may be rewritten by live_runner, but BUY/COVER retain
buy side and SELL/SHORT retain sell side. Net-flat cashflow is an independent
check on archived PnL. Fees, missing fills and unknown opening inventory remain
outside the evidence available in these files.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict, deque
from datetime import datetime
from decimal import Decimal
from pathlib import Path

BUY_ACTIONS = {"BUY", "COVER", "PARTIAL_COVER", "PYRAMID_BUY", "TIER2_ADD_BUY"}
SELL_ACTIONS = {"SELL", "SHORT", "PARTIAL_SELL", "PYRAMID_SHORT", "TIER2_ADD_SHORT"}


def audit_fills(fills: list[dict]) -> tuple[dict, list[dict]]:
    """Audit one symbol/session, explicitly assuming zero opening inventory.

    Preserve source records. Reject ambiguous duplicated fills rather than
    silently treating repeated order snapshots as executions.
    """
    lots: deque = deque()
    seen: dict = {}
    matches = []
    cashflow = Decimal(0)
    recorded = Decimal(0)
    gross_notional = Decimal(0)
    accepted = 0
    duplicates = 0
    for fill in sorted(fills, key=lambda row: row["time"]):
        action = str(fill["action"]).upper()
        if action not in BUY_ACTIONS | SELL_ACTIONS:
            raise ValueError(f"Unknown action: {action}")
        status = fill.get("order_status")
        if status is not None and status != "filled":
            raise ValueError(f"Archive is not a final fill: {status}")
        side = 1 if action in BUY_ACTIONS else -1
        qty = Decimal(str(fill["shares"]))
        price = Decimal(str(fill["price"]))
        if not qty.is_finite() or not price.is_finite() or qty <= 0 or price <= 0:
            raise ValueError("Fill quantity and price must be finite and positive")
        signature = (fill.get("ticker"), fill["time"], side, qty, price)
        order_id = fill.get("order_id")
        if order_id and order_id in seen:
            if seen[order_id] != signature:
                raise ValueError(f"Conflicting snapshots for order {order_id}")
            duplicates += 1
            continue
        if order_id:
            seen[order_id] = signature
        accepted += 1
        cashflow -= side * qty * price
        gross_notional += qty * price
        recorded += Decimal(str(fill.get("pnl", 0)))
        remaining = qty
        while remaining > 0 and lots and lots[0]["side"] != side:
            entry = lots[0]
            matched = min(remaining, entry["qty"])
            pnl = entry["side"] * (price - entry["price"]) * matched
            hold_seconds = (datetime.fromisoformat(fill["time"]) - datetime.fromisoformat(entry["time"])).total_seconds()
            matches.append({
                "ticker": fill.get("ticker"), "date": fill["time"][:10],
                "direction": "long" if entry["side"] == 1 else "short",
                "entry_time": entry["time"], "exit_time": fill["time"],
                "entry_order_id": entry["order_id"], "exit_order_id": order_id,
                "shares": float(matched), "entry_price": float(entry["price"]),
                "exit_price": float(price), "pnl_before_fees": float(pnl),
                "holding_minutes": hold_seconds / 60,
                "entry_reason": entry["reason"], "exit_reason": fill.get("reason", ""),
            })
            entry["qty"] -= matched
            remaining -= matched
            if entry["qty"] == 0:
                lots.popleft()
        if remaining:
            lots.append({"qty": remaining, "side": side, "price": price,
                         "time": fill["time"], "order_id": order_id,
                         "reason": fill.get("reason", "")})
    net_qty = sum(lot["qty"] * lot["side"] for lot in lots)
    realized = sum(Decimal(str(match["pnl_before_fees"])) for match in matches)
    if not lots and abs(realized - cashflow) > Decimal("0.000001"):
        raise AssertionError("FIFO PnL and net-flat cashflow disagree")
    return {
        "fills": accepted, "duplicates_ignored": duplicates,
        "recorded_pnl": float(recorded), "fifo_realized_before_fees": float(realized),
        "net_quantity_change": float(net_qty), "cashflow": float(cashflow),
        "net_flat_cashflow_before_fees": float(cashflow) if net_qty == 0 else None,
        "recorded_minus_fifo": float(recorded - realized),
        "gross_traded_notional": float(gross_notional),
        "matched_lots": len(matches),
        "winning_matched_lots": sum(m["pnl_before_fees"] > 0 for m in matches),
        "long_pnl_before_fees": sum(m["pnl_before_fees"] for m in matches if m["direction"] == "long"),
        "short_pnl_before_fees": sum(m["pnl_before_fees"] for m in matches if m["direction"] == "short"),
        "assumption": "Opening inventory is zero; all source fills are complete; fees excluded.",
    }, matches


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives", type=Path, default=Path("backend/data/datasets/daily_archives"))
    parser.add_argument("--start", default="2026-08-31")
    parser.add_argument("--end", default="2026-09-11")
    parser.add_argument("--tickers", nargs="+", default=["SNDK", "TSLA", "MSTR", "NVDA"])
    parser.add_argument("--output-dir", type=Path, default=Path("reports/quant_audit_20260912/ledger"))
    args = parser.parse_args()
    rows, all_matches, sources = [], [], []
    for path in sorted(args.archives.glob("trades_*.json")):
        date = path.stem.removeprefix("trades_")
        if not args.start <= date <= args.end:
            continue
        raw = path.read_bytes()
        data = json.loads(raw)
        grouped = defaultdict(list)
        for fill in data["trade_history"]:
            if fill["time"][:10] != date:
                raise ValueError(f"Archive day mismatch in {path.name}")
            grouped[fill["ticker"]].append(fill)
        sources.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "rows": len(data["trade_history"])})
        for ticker in args.tickers:
            summary, matches = audit_fills(grouped[ticker])
            rows.append({"date": date, "ticker": ticker, **summary})
            all_matches.extend(matches)
    if not sources:
        raise ValueError("No archives in requested interval; no date substitution allowed")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "daily_pnl.csv", rows)
    write_csv(args.output_dir / "matched_lots.csv", all_matches)
    (args.output_dir / "audit.json").write_text(json.dumps({
        "start": args.start, "end": args.end, "source_type": "local archived fills; not independently broker-reconciled",
        "sources": sources, "days_present": sorted({row["date"] for row in rows}),
        "note": "A matched lot is not an independent round trip. Net-flat cashflow is only full PnL when opening inventory is zero and fills are complete. No commissions/financing included.",
        "daily": rows,
    }, indent=2))
    for ticker in args.tickers:
        recent = [row for row in rows if row["ticker"] == ticker and row["date"] >= "2026-09-08"]
        print(ticker, "recent-week archive FIFO before fees", round(sum(row["fifo_realized_before_fees"] for row in recent), 2), "fills", sum(row["fills"] for row in recent))


if __name__ == "__main__":
    main()
