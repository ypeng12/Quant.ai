#!/usr/bin/env python3
"""Audit an already downloaded paper-account capture; no broker or app imports.

All financial outputs are private owner artifacts. FIFO starts from an explicit
zero-inventory *scenario*, not a claim about the account's opening positions.
An activity id identifies a fill: multiple partial fills of one order survive.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
ZERO = Decimal(0)
EXTERNAL_CASH_TYPES = {"CSD", "CSW", "TRANS", "JNLC", "ACATC"}
INTERNAL_CASH_TYPES = {"FEE", "DIV", "INT", "DIVCGL", "DIVCGS", "DIVNRA", "DIVROC", "DIVTXEX", "INTNRA"}
NAV_REFERENCE = "https://docs.alpaca.markets/us/reference/getaccountportfoliohistory-1"


def stamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Naive activity timestamps cannot be audited")
    return dt.astimezone(timezone.utc)


def decimal(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Nonfinite financial value")
    return result


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def money(value):
    if value is None:
        return "unknown"
    return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"


def display(value, spec=".2f"):
    return "unknown" if value is None else format(value, spec)


def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def read_json(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def normalize_fills(rows):
    """Deduplicate only activity IDs, never order IDs/cumulative quantities."""
    unique, duplicates = {}, 0
    for row in rows:
        if row.get("activity_type") != "FILL":
            raise ValueError("Fill capture contains non-FILL records")
        activity_id = row.get("id")
        if not activity_id:
            raise ValueError("Missing fill activity id")
        side, qty, price = row.get("side"), decimal(row["qty"]), decimal(row["price"])
        if side not in {"buy", "sell", "sell_short"} or qty <= 0 or price <= 0:
            raise ValueError("Invalid fill side, size or price")
        normalized = dict(id_hash=digest(activity_id), order_hash=digest(row.get("order_id", "")),
                          symbol=str(row["symbol"]), side="buy" if side == "buy" else "sell",
                          qty=qty, price=price, time=stamp(row["transaction_time"]),
                          fill_type=row.get("type"))
        old = unique.get(activity_id)
        if old is not None:
            if old != normalized:
                raise ValueError("Conflicting records for a fill activity id")
            duplicates += 1
        else:
            unique[activity_id] = normalized
    fills = sorted(unique.values(), key=lambda row: (row["time"], row["id_hash"]))
    return fills, duplicates


def fifo_scenario(fills):
    """Match across days; return conditional lots, inventory deltas and cash."""
    inventory, matches = defaultdict(deque), []
    daily, symbols = {}, {}
    simultaneous = defaultdict(set)
    for fill in fills:
        symbol, when = fill["symbol"], fill["time"]
        day = when.astimezone(NY).date().isoformat()
        qty, price = fill["qty"], fill["price"]
        sign = 1 if fill["side"] == "buy" else -1
        signed, cash = qty * sign, -qty * price * sign
        simultaneous[(symbol, when)].add(sign)
        for container, key in ((daily, day), (symbols, symbol)):
            agg = container.setdefault(key, dict(fill_count=0, bought_qty=ZERO, sold_qty=ZERO,
                                                 gross_traded_notional=ZERO, trade_cash_change=ZERO,
                                                 conditional_fifo_realized_pnl=ZERO, matched_lot_fragments=0))
            agg["fill_count"] += 1
            agg["bought_qty" if sign == 1 else "sold_qty"] += qty
            agg["gross_traded_notional"] += qty * price
            agg["trade_cash_change"] += cash
        remaining = qty
        lots = inventory[symbol]
        while remaining > 0 and lots and lots[0]["sign"] != sign:
            old = lots[0]
            matched = min(remaining, old["qty"])
            pnl = (price - old["price"]) * matched * old["sign"]
            minutes = (when - old["time"]).total_seconds() / 60
            match = dict(symbol=symbol, open_time=old["time"], close_time=when,
                         open_fill_hash=old["id_hash"], close_fill_hash=fill["id_hash"],
                         direction="long" if old["sign"] == 1 else "short", qty=matched,
                         entry_price=old["price"], exit_price=price,
                         gross_pnl=pnl, holding_minutes=minutes,
                         same_ny_session=old["time"].astimezone(NY).date() == when.astimezone(NY).date(),
                         prediction_error="unknown_no_linked_decision_receipt",
                         actual_fee_allocation="unknown_not_allocated_to_fills")
            matches.append(match)
            for agg in (daily[day], symbols[symbol]):
                agg["conditional_fifo_realized_pnl"] += pnl
                agg["matched_lot_fragments"] += 1
            old["qty"] -= matched
            remaining -= matched
            if old["qty"] == 0:
                lots.popleft()
        if remaining > 0:
            lots.append(dict(qty=remaining, sign=sign, price=price, time=when, id_hash=fill["id_hash"]))
    net = {symbol: sum((lot["qty"] * lot["sign"] for lot in lots), ZERO)
           for symbol, lots in inventory.items()}
    gross_pnl = sum((match["gross_pnl"] for match in matches), ZERO)
    count = len(matches)
    matched_qty = sum((m["qty"] for m in matches), ZERO)
    holding = dict(matched_lot_fragments=count,
                   median_fragment_holding_minutes=median(m["holding_minutes"] for m in matches) if count else None,
                   quantity_weighted_holding_minutes=sum(float(m["qty"]) * m["holding_minutes"] for m in matches) / float(matched_qty) if matched_qty else None,
                   fragments_at_most_five_minutes=sum(m["holding_minutes"] <= 5 for m in matches),
                   fragments_at_most_thirty_minutes=sum(m["holding_minutes"] <= 30 for m in matches),
                   overnight_fragments=sum(not m["same_ny_session"] for m in matches),
                   gross_winning_fragments=sum(m["gross_pnl"] > 0 for m in matches),
                   gross_losing_fragments=sum(m["gross_pnl"] < 0 for m in matches),
                   gross_flat_fragments=sum(m["gross_pnl"] == 0 for m in matches),
                   note="Fragments are FIFO matches, not independent predictions, orders or round trips.")
    return dict(daily=daily, by_symbol=symbols, matches=matches, net_quantity_change=net,
                conditional_ending_lots={s: list(q) for s, q in inventory.items()},
                conditional_gross_realized_pnl=gross_pnl, holding=holding,
                same_timestamp_opposite_side_groups=sum(len(sides) > 1 for sides in simultaneous.values()),
                opening_inventory="unknown; zero inventory used only for conditional FIFO scenario",
                model_version_attribution="unknown; fill records do not contain decision/model receipts")


def audit_cashflows(rows, start_day, end_day, *, unfiltered_complete=False):
    unique, duplicates = {}, 0
    for row in rows:
        if row.get("activity_type") == "FILL":
            continue
        key = row.get("id")
        if not key:
            raise ValueError("Missing nontrade activity id")
        record = dict(activity_type=row["activity_type"], date=row["date"],
                      net_amount=decimal(row.get("net_amount", 0)),
                      subtype=row.get("activity_sub_type"), status=row.get("status"))
        if key in unique:
            if unique[key] != record:
                raise ValueError("Conflicting nontrade activity id")
            duplicates += 1
        unique[key] = record
    period = [r for r in unique.values() if start_day < r["date"] <= end_day]
    types, daily, subtypes = {}, {}, {}
    unknown = set()
    for row in period:
        kind, amount = row["activity_type"], row["net_amount"]
        for container, key in ((types, kind), (daily, row["date"]), (subtypes, row["subtype"] or kind)):
            agg = container.setdefault(key, dict(count=0, net_amount=ZERO))
            agg["count"] += 1
            agg["net_amount"] += amount
        if kind not in EXTERNAL_CASH_TYPES | INTERNAL_CASH_TYPES or row.get("status") not in {None, "executed", "correct"}:
            unknown.add(kind)
    external = sum((r["net_amount"] for r in period if r["activity_type"] in EXTERNAL_CASH_TYPES), ZERO)
    return dict(total_captured=len(unique), duplicates_removed=duplicates, period_count=len(period),
                excluded_baseline_day_or_outside_period=len(unique) - len(period),
                period_start_exclusive=start_day, period_end_inclusive=end_day,
                by_type=types, by_day=daily, by_subtype=subtypes,
                external_cashflow_net_in_recognized_types=external,
                external_cashflow_activity_count=sum(r["activity_type"] in EXTERNAL_CASH_TYPES and r["net_amount"] != 0 for r in period),
                unknown_or_nonfinal_activity_types=sorted(unknown),
                completeness="unfiltered_complete_capture" if unfiltered_complete else "filtered_activity_types_only",
                external_flow_adjustment_verified=bool(unfiltered_complete and not unknown),
                fee_amount=sum((r["net_amount"] for r in period if r["activity_type"] == "FEE"), ZERO))


def audit_nav(history, cashflows):
    fields = [history[k] for k in ("timestamp", "equity", "profit_loss", "profit_loss_pct")]
    if not fields[0] or len({len(v) for v in fields}) != 1 or history.get("timeframe") != "1D":
        raise ValueError("NAV arrays must have equal, positive lengths and 1D resolution")
    if fields[0] != sorted(set(fields[0])):
        raise ValueError("NAV timestamps must be unique and ordered")
    rows = []
    for timestamp, equity, pnl, pct in zip(*fields):
        when = datetime.fromtimestamp(timestamp, timezone.utc)
        rows.append(dict(timestamp_utc=when.isoformat(), ny_session=when.astimezone(NY).date().isoformat(),
                         equity=decimal(equity), broker_cumulative_pnl=decimal(pnl), broker_cumulative_pnl_pct=pct))
    first, last = rows[0], rows[-1]
    base = decimal(history["base_value"])
    base_consistent = all(abs(r["equity"] - base - r["broker_cumulative_pnl"]) <= Decimal("0.011") for r in rows)
    fees = cashflows["fee_amount"]
    delta = last["equity"] - first["equity"]
    ext = cashflows["external_cashflow_net_in_recognized_types"]
    peak, drawdown = first["equity"], ZERO
    for previous, row in zip(rows, rows[1:]):
        row["equity_change_from_previous"] = row["equity"] - previous["equity"]
        peak = max(peak, row["equity"])
        drawdown = min(drawdown, row["equity"] / peak - 1) if peak else drawdown
    # Deposits and withdrawals can cancel in total while still invalidating a
    # simple equity ratio as an investment return.
    no_flows = cashflows["external_flow_adjustment_verified"] and cashflows["external_cashflow_activity_count"] == 0
    return dict(rows=rows, baseline_session=first["ny_session"], end_session=last["ny_session"],
                beginning_equity=first["equity"], ending_equity=last["equity"],
                equity_change=delta, equity_change_pct=delta / first["equity"] if first["equity"] else None,
                recognized_flow_adjusted_change=delta - ext,
                flow_adjustment_verified=cashflows["external_flow_adjustment_verified"],
                return_without_external_flows=delta / first["equity"] if no_flows and first["equity"] else None,
                raw_equity_max_drawdown_pct=drawdown, raw_drawdown_may_include_cashflows=not no_flows,
                fees_in_captured_period=fees,
                broker_base_value=base, broker_base_value_asof=history.get("base_value_asof"),
                broker_pnl_is_cumulative=True, base_to_equity_pnl_reconciles=base_consistent,
                fee_handling="Fees already affect broker equity. Do not subtract them again from equity change.",
                reference=NAV_REFERENCE)


def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(data)


def audit_capture(root, output):
    manifest, manifest_hash = read_json(root / "manifest.json")
    if manifest.get("is_paper") is not True or not manifest.get("complete"):
        raise ValueError("A complete paper-only capture manifest is required")
    rows, provenance = [], []
    for request in manifest["requests"]:
        name = request["file"]
        if Path(name).name != name or not name.startswith("fills_") or request.get("http_status") != 200:
            raise ValueError("Unexpected or unsuccessful fill capture page")
        page, sha = read_json(root / name)
        if sha != request["sha256"] or len(page) != request["rows"]:
            raise ValueError("Fill page hash/count does not match capture manifest")
        provenance.append(dict(file=name, sha256=sha, rows=len(page)))
        rows.extend(page)
    fills, duplicates = normalize_fills(rows)
    if not fills:
        raise ValueError("No fills available")
    fifo = fifo_scenario(fills)
    history, nav_hash = read_json(root / "portfolio_history.json")
    nontrade, nontrade_hash = read_json(root / "nontrade_activities.json")
    supplement, supplement_hash = read_json(root / "supplement_manifest.json")
    for expected in (nav_hash, nontrade_hash):
        if not any(r.get("sha256") == expected and r.get("status") == 200 for r in supplement):
            raise ValueError("Supplement hash or success status not verified")
    start_day = datetime.fromtimestamp(history["timestamp"][0], NY).date().isoformat()
    end_day = datetime.fromtimestamp(history["timestamp"][-1], NY).date().isoformat()
    unfiltered_complete = False
    # Optional later capture of *all* activity types, with explicit provenance.
    all_root = root / "all_activities"
    all_manifest_path = all_root / "manifest.json"
    if all_manifest_path.exists():
        all_manifest, all_manifest_hash = read_json(all_manifest_path)
        if not all_manifest.get("complete") or all_manifest.get("activity_type_filter") not in {None, ""}:
            raise ValueError("All-activity manifest must be complete and unfiltered")
        requested_after = stamp(all_manifest["after"])
        requested_until = stamp(all_manifest["until"])
        needed_after = datetime.combine(date.fromisoformat(start_day) + timedelta(days=1), datetime.min.time(), NY)
        needed_until = datetime.combine(date.fromisoformat(end_day) + timedelta(days=1), datetime.min.time(), NY)
        if requested_after > needed_after or requested_until < needed_until:
            raise ValueError("Unfiltered activity window does not cover NAV comparison period")
        all_rows = []
        for request in all_manifest["pages"]:
            name = request["file"]
            if Path(name).name != name or request.get("http_status") != 200:
                raise ValueError("Invalid all-activity page")
            page, sha = read_json(all_root / name)
            if sha != request["sha256"] or len(page) != request["rows"]:
                raise ValueError("All-activity page provenance mismatch")
            all_rows.extend(page)
        if len(all_rows) != all_manifest["total_rows"]:
            raise ValueError("All-activity total row count mismatch")
        all_fills, _ = normalize_fills([r for r in all_rows if r.get("activity_type") == "FILL"])
        period_fills = [r for r in all_fills if start_day < r["time"].astimezone(NY).date().isoformat() <= end_day]
        if fills != period_fills:
            raise ValueError("All-activity fill content differs from fill-only capture")
        nontrade = [r for r in all_rows if r.get("activity_type") != "FILL"]
        unfiltered_complete = True
        provenance.append(dict(file="all_activities/manifest.json", sha256=all_manifest_hash))
    cashflows = audit_cashflows(nontrade, start_day, end_day, unfiltered_complete=unfiltered_complete)
    nav = audit_nav(history, cashflows)
    flat_delta = all(q == 0 for q in fifo["net_quantity_change"].values())
    total_cash = sum((row["trade_cash_change"] for row in fifo["by_symbol"].values()), ZERO)
    # When net inventory change is zero, cash P&L of the captured trading flow is
    # determined without choosing opening cost basis. The account may still have
    # unchanged pre-existing positions whose mark-to-market affects total NAV.
    flow_gross = total_cash if flat_delta else None
    flow_after_known_fees = flow_gross + cashflows["fee_amount"] if flat_delta else None
    reconciliation_gap = nav["recognized_flow_adjusted_change"] - flow_after_known_fees if flat_delta else None
    notional = sum((v["gross_traded_notional"] for v in fifo["by_symbol"].values()), ZERO)
    turnover = dict(sum_of_buy_and_sell_notional=notional,
                    notional_divided_by_beginning_equity=notional / nav["beginning_equity"] if nav["beginning_equity"] else None,
                    convention="Sum of absolute fill notional, both buys and sells; not divided by two. Not account gross exposure.")
    for day, stats in fifo["daily"].items():
        stats["captured_nontrade_net_amount"] = cashflows["by_day"].get(day, {}).get("net_amount", ZERO)
    summary = dict(schema_version=1, account_mode="paper", privacy="local_owner_only_do_not_publish",
                   created_at=datetime.now(timezone.utc).isoformat(),
                   script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   provenance=dict(fill_manifest_sha256=manifest_hash, supplement_manifest_sha256=supplement_hash,
                                   nav_sha256=nav_hash, original_nontrade_sha256=nontrade_hash, fill_pages=provenance),
                   coverage=dict(captured_fills=len(rows), unique_fills=len(fills), duplicate_activity_ids_removed=duplicates,
                                 unique_orders=len({r["order_hash"] for r in fills}),
                                 partial_fill_count=sum(r["fill_type"] == "partial_fill" for r in fills),
                                 first_fill=fills[0]["time"], last_fill=fills[-1]["time"],
                                 ny_calendar_fill_days=len(fifo["daily"]),
                                 utc_calendar_fill_days=len({r["time"].date() for r in fills}),
                                 ny_weekend_fill_count=sum(r["time"].astimezone(NY).weekday() >= 5 for r in fills),
                                 symbols=sorted(fifo["by_symbol"]),
                                 nav_observations=len(nav["rows"]), all_returned_fill_pages_verified=True),
                   fifo=fifo, nontrade=cashflows, nav=nav, turnover=turnover,
                   reconciliation=dict(net_quantity_change_zero_for_all_symbols=flat_delta,
                                       captured_flow_gross_cash_pnl_if_flat=flow_gross,
                                       captured_flow_after_known_fees_if_flat=flow_after_known_fees,
                                       nav_change_minus_flow_after_known_fees=reconciliation_gap,
                                       opening_inventory_verified=False,
                                       note="Zero inventory change does not prove zero opening holdings. Residual includes unobserved holdings, other cashflows/valuation timing; it is not automatically a model error."),
                   interpretation=dict(prediction_error="unknown_without_timestamped_forecast_and_model_receipt",
                                       version_causality="unidentified; historical fills may contain multiple strategies/manual actions",
                                       execution_slippage="unknown_without_arrival_quote_and_decision_target",
                                       sentiment_benefit="cannot be inferred from this account audit; requires matched A/C/B experiment"))
    private_write(output / "paper_account_audit.json", json.dumps(summary, ensure_ascii=False, indent=2, default=json_default) + "\n")
    h = fifo["holding"]
    quantity_text = "、".join(f"{s}: {q}" for s, q in sorted(fifo["net_quantity_change"].items()))
    flow_scope_text = "全部活动类型、完整分页" if unfiltered_complete else "仅捕获指定活动类型，完整性未确认"
    verified_flow_text = "已核验；本区间没有外部资金流，上述百分比可作为该 paper 账户的区间回报" if nav["return_without_external_flows"] is not None else "外部资金流尚不能排除或不为零，净值比例不直接当投资回报"
    reconciliation_text = "账务精确对平，但不能由此证明期初无持仓或某个模型的独立效果。" if reconciliation_gap == 0 else "差额须进一步核对未变化的期初持仓估值、其他活动和时间边界，不能强行归零。"
    text = f"""# Paper 账户成交与净值复盘（仅项目所有者）

这是 Alpaca **paper 模拟账户**，不是实钱收益；本文件和原始账户资料不得发布到公开网站或 GitHub。原始文件只读，逐页 SHA-256 和行数已核验。

## 已拿到的证据

- 成交覆盖 {fills[0]['time'].isoformat()} 至 {fills[-1]['time'].isoformat()}：{len(fills):,} 个唯一成交活动、{len(fifo['daily'])} 个纽约日历日期（含 {summary['coverage']['ny_weekend_fill_count']} 笔周末日期成交，不能直接称正常交易日）、{len(fifo['by_symbol'])} 支股票。重复 activity ID {duplicates} 个。{summary['coverage']['partial_fill_count']:,} 个是部分成交，同一订单的多个成交均保留。
- 日净值 {len(nav['rows'])} 点，纽约日期 {start_day}–{end_day}。API 的 UTC 时间标签是纽约前一日晚上，不能直接取 UTC 日期。
- 非成交活动范围：{flow_scope_text}。基线日 {start_day} 的活动已排除，避免把基线前费用再扣一次。
- 旧本地 ledger 截止 9/16 的缺口已由这批 broker 返回成交补充；仍不能凭 fill 反推出当时模型版本、预测值或原因。

## 账户层面

- 基线净值 {money(nav['beginning_equity'])} → 期末 {money(nav['ending_equity'])}；净值变化 {money(nav['equity_change'])}（{display(nav['equity_change_pct'], '.2%')}）。
- 识别到的外部资金净流入 {money(cashflows['external_cashflow_net_in_recognized_types'])}；{verified_flow_text}。
- 期间显式费用活动合计 {money(cashflows['fee_amount'])}，已体现在 broker 净值中，不能再次从净值变化扣除。买卖价差和滑点已混在成交价中，不能从这份活动记录单独测出来。
- 日线 `profit_loss` 相对 {nav['broker_base_value_asof']} 的固定 base_value 累计；不是每日损益。不能把它求和或把末点累计值当作 9–10 月损益。[官方口径]({NAV_REFERENCE})。

## 成交流与 FIFO

- 各股净成交股数变化：{quantity_text}。净成交变化**不能证明期初无持仓**。
- 在净变化为零时，捕获成交流的卖出收款减买入付款为 {money(flow_gross)}；加已知费用为 {money(flow_after_known_fees)}。与账户净值变化的差额为 {money(reconciliation_gap)}。{reconciliation_text}
- FIFO 以“期初零库存”为条件跨日配对，得到 {h['matched_lot_fragments']:,} 个配对片段；毛赢 {h['gross_winning_fragments']:,}、毛亏 {h['gross_losing_fragments']:,}、持平 {h['gross_flat_fragments']:,}。这不是独立策略交易次数或预测命中率。
- 片段持有期中位数 {display(h['median_fragment_holding_minutes'])} 分钟；≤5 分钟 {h['fragments_at_most_five_minutes']:,}；≤30 分钟 {h['fragments_at_most_thirty_minutes']:,}；跨纽约日期 {h['overnight_fragments']:,}。相同时间戳同股相反方向组 {fifo['same_timestamp_opposite_side_groups']} 个，此类 FIFO 顺序不唯一。
- 买入与卖出绝对成交额合计 {money(notional)}，相对初始净值约 {display(turnover['notional_divided_by_beginning_equity'], '.1f')} 倍。此处不除以二，也不是某一时刻的杠杆或风险暴露。
- 每日、每股成交额、现金变化、条件 FIFO 损益、每笔配对在同目录 JSON 中。真实费用未擅自按 fill 分摊；缺少下单前报价，无法量出真实滑点或把毛赢变净亏逐笔归因。

| 股票 | 成交活动数 | 条件 FIFO 毛损益 | 买卖绝对成交额合计 |
|---|---:|---:|---:|
"""
    for symbol, row in sorted(fifo["by_symbol"].items()):
        text += f"| {symbol} | {row['fill_count']:,} | {money(row['conditional_fifo_realized_pnl'])} | {money(row['gross_traded_notional'])} |\n"
    text += """

## 能据此改什么

先检查高换手、手续费和持有期，再用新旧策略同日期、同资金、同成本假设与风险上限做 A/C/B 重放。毛损益已经亏损时，单纯省手续费无法解释全部亏损。亏损本身不能证明“预测错误”；每次新决策必须保留当时模型版本、数据时间、预期收益、目标仓位和 broker order 关联，才能区分方向错、预期不够成本、过度换手和执行问题。情绪是否增加收益要靠 B−C 的受控结果，不能用整个 paper 账户的历史亏损替它背书。只从9/14开始的重放，也不能覆盖9/1–9/11的账户表现。
"""
    private_write(output / "paper_account_audit_zh.md", text)
    # A whitelist draft for review, kept private beside the audit. No money,
    # individual fills, order references, credentials or account identifiers.
    public_draft = dict(account_mode="paper", publication_authorized=False,
                        fill_capture_hashes_verified=True, cashflow_capture_complete=unfiltered_complete,
                        journal_cannot_backfill_historical_decisions=True,
                        model_version_causality="unidentified",
                        public_strategy_results_source="separate controlled A/C/B simulation")
    private_write(output / "coverage_whitelist_draft.json", json.dumps(public_draft, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = audit_capture(args.capture_dir, args.output_dir or args.capture_dir / "analysis")
    # Deliberately omit amounts, account identifiers and individual operations.
    print(json.dumps({"status": "complete", "account_mode": "paper", "unique_fills": result["coverage"]["unique_fills"],
                      "ny_calendar_fill_days": result["coverage"]["ny_calendar_fill_days"], "output": str(args.output_dir or args.capture_dir / "analysis")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
