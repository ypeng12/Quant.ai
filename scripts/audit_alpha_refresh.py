#!/usr/bin/env python3
"""Independently reconcile recorded alpha-refresh artifacts; no broker access."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def require(value, description):
    if not value:
        raise ValueError(description)


def audit(root):
    reg = json.loads((root / "registry.json").read_text())
    require(reg["status"] == "complete", "Experiment incomplete")
    out = {}
    for name, r in reg["results"].items():
        folder = root / name
        d = pd.read_csv(folder / "daily.csv.gz")
        f = pd.read_csv(folder / "fills.csv.gz")
        t = json.loads((folder / "training.json").read_text())
        require(all(x["last_training_session"] < x["date"] for x in t), "Training leakage")
        require(len(d) == r["sessions"] and not d.date.duplicated().any(), "Session mismatch")
        require(np.allclose(d.gross_pnl - d.costs, d.net_pnl), "Daily cost reconciliation")
        require(np.isclose(f.cost.sum(), r["costs"]), "Fill cost reconciliation")
        require(np.isclose(d.net_pnl.sum(), r["net_pnl"]), "Net reconciliation")
        require(np.isclose(r["gross_pnl"], r["fixed_order_cost_stress"]["0"]["net_pnl"]), "Gross stress reconciliation")
        require(np.isclose(r["net_pnl"], r["fixed_order_cost_stress"]["2"]["net_pnl"]), "Base stress reconciliation")
        timed = f.dropna(subset=["signal_data_cutoff"])
        require((pd.to_datetime(timed.fill_time, utc=True) >=
                 pd.to_datetime(timed.signal_data_cutoff, utc=True)).all(), "Premature execution")
        require((d.ending_gross_exposure == 0).all(), "Unclosed session inventory")
        out[name] = dict(gross_pnl=r["gross_pnl"], net_2bps=r["net_pnl"],
            fixed_path_net_5bps=r["fixed_order_cost_stress"]["5"]["net_pnl"],
            gross_exposure=r["mean_gross_exposure"], abs_net_exposure=r["mean_abs_net_exposure"],
            daily_volatility=r["daily_return_std"], max_drawdown=r["max_drawdown"],
            daily_turnover=r["mean_daily_turnover"],
            break_even_friction_bps=r["gross_pnl"] / r["turnover_dollars"] * 10000,
            first_half_pnl=r["chronological_halves"][0]["net_pnl"],
            second_half_pnl=r["chronological_halves"][1]["net_pnl"],
            without_best_day=r["net_pnl"] - d.net_pnl.max(),
            per_symbol_net={s: float(d[s + "_net_pnl"].sum()) for s in reg["traded_symbols"]})
    for p, h in reg["source_hashes"].items():
        require(hashlib.sha256((root / "source" / p).read_bytes()).hexdigest() == h, "Source hash mismatch")
    return dict(checks="Training chronology, fill timing, session inventory, gross/net/cost reconciliation and source hashes passed",
                registry_sha256=hashlib.sha256((root / "registry.json").read_bytes()).hexdigest(), results=out)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--comparison", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = audit(Path(args.comparison))
    with Path(args.output).open("x") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps(result, indent=2))
