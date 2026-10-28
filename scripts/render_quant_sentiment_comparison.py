#!/usr/bin/env python3
"""Render the validated public comparison; no trading or data acquisition."""
import argparse
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.financial_sentiment_comparison import validate_public_comparison


def render(source, destination):
    data = validate_public_comparison(json.loads(Path(source).read_text()))
    models = {m["id"]: m for m in data["models"]}
    x = np.arange(data["sessions"] + 1)
    values = {key: np.array([data["starting_capital"]] + [r[key] for r in data["curves"]])
              for key in ("A", "B", "C")}
    fig = plt.figure(figsize=(13, 9), facecolor="#f6f8fc")
    grid = fig.add_gridspec(2, 1, height_ratios=[3, 1.25], hspace=0.28,
                           top=0.79, bottom=0.18, left=0.10, right=0.96)
    fig.text(0.10, 0.94, "Quant.ai | Old model vs new candidate", fontsize=22, weight="bold", color="#15233b")
    fig.text(0.10, 0.90, f"{data['evaluated_start']} to {data['evaluated_end']}  |  {data['sessions']} sessions  |  $50,000 each",
             fontsize=12, color="#4a5b71")
    fig.text(0.10, 0.865, "Retrospective simulation · 2 bps per side assumed friction · not live account returns",
             fontsize=10, color="#5c6678")
    ax = fig.add_subplot(grid[0])
    for key, color, style in (("A", "#c44e52", "-"), ("B", "#2463b5", "-"), ("C", "#249882", "--")):
        label = {"A": "A · Old model", "B": "B · Improved price + text", "C": "C · Improved price only"}[key]
        ax.plot(x, values[key], color=color, linestyle=style, linewidth=2.3 if key != "C" else 1.5,
                label=f"{label}   ({models[key]['net_pnl']:+,.2f} USD)")
    ax.axhline(data["starting_capital"], color="#8793a4", linewidth=0.8, alpha=0.7)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.set_ylabel("Simulated account equity", color="#34455b")
    ax.legend(loc="lower left", fontsize=10, frameon=True, framealpha=0.95)
    ax.grid(axis="y", alpha=0.18)
    labels = ["Start"] + [r["date"][5:] for r in data["curves"]]
    ticks = sorted(set([0, *range(5, len(x), 5), len(x) - 1]))
    ax.set_xticks(ticks, [labels[i] for i in ticks])
    ax2 = fig.add_subplot(grid[1], sharex=ax)
    ax2.plot(x, values["B"] - values["A"], color="#2463b5", label="B minus A · full system change")
    ax2.plot(x, values["B"] - values["C"], color="#d17b24", label="B minus C · entire text adapter")
    ax2.axhline(0, color="#8793a4", linewidth=0.8)
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax2.set_ylabel("Equity difference", color="#34455b")
    ax2.grid(axis="y", alpha=0.18)
    ax2.legend(loc="upper left", fontsize=9)
    for axes in (ax, ax2):
        axes.set_facecolor("white")
        axes.spines[["top", "right"]].set_visible(False)
        axes.spines[["left", "bottom"]].set_color("#cdd5e1")
    fig.text(0.10, 0.105,
        f"Main finding: B loses less than A, but B itself loses money. Text adapter B − C: ${models['B']['net_pnl'] - models['C']['net_pnl']:+,.2f}.",
        fontsize=11, weight="bold", color="#15233b")
    fig.text(0.10, 0.065,
        f"Average gross exposure: A {models['A']['mean_gross_exposure']:.1%}, B {models['B']['mean_gross_exposure']:.1%}. Different actual risk explains part of the change.\n"
        "Only 25 portfolio times had revised forecasts; limited source batches. At 5 bps, all three strategies lose money.",
        fontsize=10, color="#4a5b71", linespacing=1.7)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", default=str(ROOT / "reports/financial_sentiment_strategy_comparison.json"))
    p.add_argument("--output", default=str(ROOT / "reports/financial_sentiment_strategy_comparison.png"))
    a = p.parse_args()
    render(a.input, a.output)
