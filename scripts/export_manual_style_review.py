"""Export observed volume, forecasts, holdings and fills from a frozen study.

Does not fit models, select candidates, regenerate trades, or contact a broker.
Source files must still match the recorded experiment hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_index(values):
    return pd.DatetimeIndex(pd.to_datetime(values, utc=True)).tz_convert("America/New_York")


def export(study, output):
    registry = json.loads((study / "registry.json").read_text())
    evidence = json.loads((study / "SHA256SUMS.json").read_text())
    for name, expected in evidence.items():
        if digest(study / name) != expected:
            raise ValueError(f"Changed experiment artifact: {name}")
    frames = []
    for name, expected in registry["sources"].items():
        path = Path(name)
        if path.name != "SNDK.parquet":
            continue
        if digest(path) != expected:
            raise ValueError(f"Changed market source: {name}")
        frame = pd.read_parquet(path)
        frame.columns = frame.columns.str.lower()
        frame.index = utc_index(frame.index)
        frames.append(frame[["open", "high", "low", "close", "volume"]])
    bars = pd.concat(frames).sort_index()
    if not bars.index.is_unique:
        raise ValueError("Overlapping input snapshots")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"source_study": str(study.resolve()),
                "source_registry_sha256": digest(study / "registry.json"),
                "source_evidence_sha256": digest(study / "SHA256SUMS.json"),
                "purpose": "Post-run inspection; no trading decisions changed",
                "bar_timing": "bar_open + 5 minutes = completed-bar availability",
                "shares_timing": "Fill events determine position immediately; not shifted to next close",
                "options_used": False, "l1_used": False}
    for result in registry["results"]:
        day, variant = result["day"], result["variant"]
        source = study / day / variant
        target = output / day / variant
        target.mkdir(parents=True)
        feature = pd.read_csv(source / "SNDK_features.csv", index_col=0)
        feature.index = utc_index(feature.index)
        review = bars.loc[feature.index].join(feature, validate="one_to_one")
        review.index.name = "bar_open"
        review.insert(0, "available_at", review.index + pd.Timedelta(minutes=5))
        decisions = json.loads((source / "decisions.json").read_text())
        for decision in decisions:
            stamp = pd.Timestamp(decision["bar_open"])
            review.loc[stamp, "target_weight"] = decision["targets"]["SNDK"]
            for key, prefix in (("cumulative_forecast_bps", "calibrated"),
                                ("raw_cumulative_forecast_bps", "raw")):
                for horizon, prediction in decision.get(key, {}).get("SNDK", {}).items():
                    review.loc[stamp, f"{prefix}_forecast_{horizon}m_bps"] = prediction
        marks = pd.read_csv(source / "marks.csv")
        marks = marks.loc[marks.phase.eq("bar_close")].copy()
        marks.index = utc_index(marks.timestamp)
        for field in ("shares", "weight", "pnl"):
            review[f"marked_{field}"] = marks[f"SNDK_{field}"].reindex(
                utc_index(review.available_at)).to_numpy()
        review.to_csv(target / "SNDK_review.csv")

        orders = pd.read_csv(source / "SNDK_orders.csv")
        orders["time"] = utc_index(orders.time)
        x = utc_index(review.available_at)
        fig, axes = plt.subplots(4, 1, figsize=(16, 11), sharex=True,
                                 gridspec_kw={"height_ratios": [4, 1, 1, 1]})
        axes[0].plot(x, review.close, color="#2474ac", label="Completed 5m close")
        vwap = ((review.high + review.low + review.close) / 3 * review.volume).cumsum() / review.volume.cumsum()
        axes[0].plot(x, vwap, color="#dfa452", label="OHLCV VWAP proxy")
        colors = {"B": "#d94d67", "S": "#159c76", "C": "#9b70c9", "X": "#d69826"}
        seen = set()
        for order in orders.itertuples():
            label = {"B": "Buy long", "S": "Sell long", "C": "Cover short", "X": "Open short"}[order.action]
            buy = order.action in {"B", "C"}
            axes[0].scatter(order.time, order.price, s=25 + order.quantity * 3,
                            marker="^" if buy else "v", color=colors[order.action],
                            label=label if order.action not in seen else None, zorder=4)
            axes[0].annotate(f"{order.action}{order.quantity}", (order.time, order.price),
                             xytext=(0, 7 if buy else -12), textcoords="offset points",
                             ha="center", fontsize=7, color=colors[order.action])
            seen.add(order.action)
        axes[0].legend(ncol=3, fontsize=8)
        axes[0].set_ylabel("Price ($)")
        axes[0].set_title(f"SNDK {day} | {variant} | through {x[-1]:%H:%M} ET\n"
                          f"Simulated fills on saved prices; net ${result['sndk_net']:.2f}; "
                          "5 bps assumed one-way friction")
        axes[1].bar(x, review.volume / 1000, width=4 / 1440,
                    color=["#159c76" if c >= o else "#d94d67" for c, o in zip(review.close, review.open)])
        axes[1].set_ylabel("Volume (000s)")
        # Use actual fill timestamps. A close mark alone would show a position
        # change five minutes later than its matching entry/exit marker.
        times = [review.index[0], *orders.time, x[-1]]
        holdings = [0, *orders.shares_after, result["sndk_ending_shares"]]
        axes[2].step(times, holdings, where="post", color="#5d5795")
        axes[2].set_ylabel("Shares")
        axes[3].plot(x, review.marked_pnl, color="#278c80")
        axes[3].set_ylabel("Net PnL ($)")
        for axis in axes:
            axis.grid(alpha=.15)
        axes[-1].xaxis.set_major_locator(mdates.MinuteLocator(byminute=[0, 30], tz=ZoneInfo("America/New_York")))
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=ZoneInfo("America/New_York")))
        fig.tight_layout()
        fig.savefig(target / "SNDK_volume_orders.png", dpi=135)
        plt.close(fig)
    manifest["export_script_sha256"] = digest(Path(__file__))
    (output / "registry.json").write_text(json.dumps(manifest, indent=2))
    (output / "SHA256SUMS.json").write_text(json.dumps({
        str(p.relative_to(output)): digest(p) for p in output.rglob("*") if p.is_file()
    }, indent=2))
    print(f"Exported six volume/order charts and complete decision tables to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export(args.study, args.output)
