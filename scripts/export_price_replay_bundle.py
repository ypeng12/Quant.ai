"""Package verified saved study into a portable read-only dashboard bundle.

No model fitting, trade regeneration, network requests or brokerage actions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(path, expected):
    if digest(path) != expected:
        raise ValueError(f"Source hash mismatch: {path.name}")


def times(values):
    return pd.DatetimeIndex(pd.to_datetime(values, utc=True)).tz_convert("America/New_York")


def export(study: Path, output: Path):
    evidence = json.loads((study / "SHA256SUMS.json").read_text())
    for name, expected in evidence.items():
        checked(study / name, expected)
    registry = json.loads((study / "registry.json").read_text())
    if registry["status"] != "complete":
        raise ValueError("Only complete registered studies can be exported")
    symbols = ["SNDK", "TSLA", "PLTR", "NVDA"]
    frames = {}
    for symbol in symbols:
        parts = []
        for name, expected in registry["sources"].items():
            path = Path(name)
            if path.stem != symbol:
                continue
            checked(path, expected)
            frame = pd.read_parquet(path)
            frame.columns = frame.columns.str.lower()
            frame.index = times(frame.index)
            parts.append(frame[["open", "high", "low", "close", "volume"]])
        frames[symbol] = pd.concat(parts).sort_index()
        if not frames[symbol].index.is_unique:
            raise ValueError("Overlapping input price snapshots")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": 1, "available_dates": sorted(registry["dates"]),
                "variants": registry["variants"], "tickers": symbols,
                "study": study.name, "source_registry_sha256": digest(study / "registry.json"),
                "source_evidence_sha256": digest(study / "SHA256SUMS.json"),
                "export_script_sha256": digest(Path(__file__)), "files": {}}
    for result in registry["results"]:
        day, variant = result["day"], result["variant"]
        source = study / day / variant
        trades = pd.read_csv(source / "fills.csv")
        marks = pd.read_csv(source / "marks.csv")
        marks = marks.loc[marks.phase.eq("bar_close")].copy()
        mark_times = times(marks.timestamp)
        as_of = pd.Timestamp(result["as_of"])
        for symbol in symbols:
            frame = frames[symbol]
            frame = frame.loc[frame.index.strftime("%Y-%m-%d") == day]
            available = frame.index + pd.Timedelta(minutes=5)
            frame = frame.loc[available <= as_of]
            available = frame.index + pd.Timedelta(minutes=5)
            if not available.equals(mark_times):
                raise ValueError("Price and ledger close timestamps differ")
            numeric = frame.to_numpy(dtype=float)
            if not np.isfinite(numeric).all() or (frame.volume < 0).any():
                raise ValueError("Invalid OHLCV source values")
            vwap = ((frame.high + frame.low + frame.close) / 3 * frame.volume).cumsum() / frame.volume.cumsum()
            bars = [{"time": stamp.isoformat(), "bar_open": opened.isoformat(),
                     **{key: float(row[key]) for key in frame.columns},
                     "vwap": float(weighted) if np.isfinite(weighted) else None}
                    for stamp, opened, (_, row), weighted in zip(available, frame.index, frame.iterrows(), vwap)]
            fills = []
            position = 0
            symbol_trades = trades.loc[trades.symbol.eq(symbol)]
            for row in symbol_trades.itertuples():
                delta = int(row.quantity)
                after = int(row.shares_after)
                if position + delta != after:
                    raise ValueError("Fill quantity does not reconcile with inventory")
                if position * after < 0:
                    raise ValueError("Reversal must be recorded as a close and an opening fill")
                action = "B" if delta > 0 and position >= 0 else "C" if delta > 0 else "S" if position > 0 else "X"
                fills.append({"time": pd.Timestamp(row.fill_time).isoformat(), "action": action,
                              "shares": abs(delta), "quantity": delta, "price": float(row.fill_price),
                              "reference_price": float(row.reference_price), "shares_before": position,
                              "shares_after": after, "assumed_cost": float(row.cost),
                              "commission_cost": float(row.commission_cost),
                              "signal_data_cutoff": row.signal_data_cutoff if pd.notna(row.signal_data_cutoff) else None,
                              "pnl": None})
                position = after
            snapshots = [{"time": stamp.isoformat(), "shares": int(row[f"{symbol}_shares"]),
                          "pnl": float(row[f"{symbol}_pnl"])}
                         for stamp, (_, row) in zip(mark_times, marks.iterrows())]
            # A close mark is recorded before the next-bar opening fills at the
            # same timestamp. Hold each fill from its exact event time in the UI.
            for mark, close in zip(snapshots, frame.close):
                seen = [f for f in fills if f["time"] < mark["time"]]
                qty = sum(f["quantity"] for f in seen)
                cash = -sum(f["quantity"] * f["price"] + f["commission_cost"] for f in seen)
                if qty != mark["shares"] or not np.isclose(cash + qty * close, mark["pnl"], atol=1e-7):
                    raise ValueError("Saved mark does not reconcile with fills and closing price")
            cost = float(symbol_trades.cost.sum())
            net = snapshots[-1]["pnl"]
            if symbol == "SNDK" and not np.isclose(net, result["sndk_net"], atol=1e-7):
                raise ValueError("Published SNDK result differs from ledger")
            full_close = pd.Timestamp(f"{day}T16:00:00", tz="America/New_York")
            payload = {"schema_version": 1, "ticker": symbol, "date": day, "variant": variant,
                       "source_label": "已保存历史行情与模型模拟成交", "price_source": "Saved Yahoo OHLCV",
                       "is_simulated": True, "as_of": as_of.isoformat(), "partial": as_of < full_close,
                       "starting_equity": registry["capital_by_day"][day], "capital_scope": "four_stock_portfolio",
                       "cost_bps": registry["execution_friction_bps"], "cost_label": "单边模拟摩擦假设；非实际券商收费",
                       "actual_fees_verified": False, "opening_shares": 0,
                       "session_open": pd.Timestamp(f"{day}T09:30:00", tz="America/New_York").isoformat(),
                       "session_close": full_close.isoformat(), "bar_interval_minutes": 5,
                       "bar_timing": "completed_bar_availability", "vwap_label": "OHLCV VWAP proxy",
                       "mark_timing": "bar_close_before_next_open_fills_at_same_timestamp",
                       "bars": bars, "fills": fills, "marks": snapshots,
                       "summary": {"net_pnl": net, "gross_pnl": net + cost, "cost": cost,
                                   "fill_count": len(fills), "ending_shares": position},
                       "source_hashes": {"fills_sha256": digest(source / "fills.csv"),
                                         "marks_sha256": digest(source / "marks.csv"),
                                         "registry_sha256": manifest["source_registry_sha256"]}}
            name = f"{day}/{variant}/{symbol}.json"
            dest = output / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
            manifest["files"][name] = digest(dest)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"Exported {len(manifest['files'])} verified replays to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    export(args.study, args.output)
