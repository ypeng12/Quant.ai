#!/usr/bin/env python3
"""Read-only diagnostic reproductions of unsafe pre-existing execution behavior.

This is NOT a correctness test suite: bug_reproduced=true confirms a defect.
A zero exit code only means the diagnostic completed, not that trading is correct.
Only selected AST definitions are executed; live_runner imports, constructors,
network clients, trading loops, account access and order submission never run.

Run from any directory: python3 /path/to/reproduce_live_findings.py
"""

import ast
import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from types import ModuleType
from typing import Dict, Optional
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
LIVE_PATH = ROOT / "backend/app/broker/live_runner.py"
SIZER_PATH = ROOT / "backend/app/broker/risk_position_sizer.py"


def selected_class(path, class_name, methods=None, constants=()):
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    if methods is not None:
        node.body = [
            n for n in node.body
            if (isinstance(n, ast.FunctionDef) and n.name in methods)
            or (
                isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id in constants for t in n.targets)
            )
        ]
    namespace = {
        "datetime": datetime, "time": time, "math": math,
        "Dict": Dict, "Optional": Optional,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[class_name]


def main():
    runner_class = selected_class(
        LIVE_PATH,
        "LiveTradingRunner",
        methods={
            "_evaluate_aggressive_intraday", "_get_ticker_wave_profile",
            "_safe_float", "_aggressive_intraday_defaults",
        },
        constants={"TICKER_WAVE_PROFILES"},
    )
    runner = runner_class()  # The real __init__ was excluded above.
    runner.strategy_params = runner._aggressive_intraday_defaults()
    for key in (
        "position_extremes", "staged_entries", "pyramid_done", "pyramid_counts",
        "partial_tp_done", "last_exit_times", "entry_times",
    ):
        setattr(runner, key, {})
    runner.is_entry_locked = lambda ticker: False
    runner._can_open_short = lambda ticker: True
    quality_stub = ModuleType("app.broker.universe_screener")
    quality_stub.is_valid_quality_stock_symbol = lambda ticker: True
    opportunity = {
        "price": 100.0, "direction": "LONG", "regime": "LONG_TREND",
        "win_rate_pct": 35.0, "expected_value_r": -0.80, "is_positive_ev": False,
        "upper_wick_ratio": 0.0, "_atr": 1.0, "_stop_pct": 0.008,
        "alpha_ofi": 0.0, "alpha_micro_drift": 0.0, "toxic_flow": 0.0, "rvol": 1.0,
    }
    with patch.dict(sys.modules, {quality_stub.__name__: quality_stub}):
        low_ev_result = runner._evaluate_aggressive_intraday("NVDA", opportunity, 0, 0.0, 0)
        runner.staged_entries["NVDA"] = {"tier": 2}
        loss_result = runner._evaluate_aggressive_intraday(
            "NVDA", {**opportunity, "price": 90.0}, 100, 100.0, 1
        )

    sizer_class = selected_class(SIZER_PATH, "RiskPositionSizer")
    sizing = sizer_class().size_aggressive_entry(
        {"equity": 1000.0, "cash": 950.0, "buying_power": 950.0},
        1000.0,
        {"_atr": 300.0, "_stop_pct": 0.025, "win_probability": 0.35},
        runner.strategy_params,
    )
    result = {
        "diagnostic_only": True,
        "meaning": "bug_reproduced=true confirms a defect; it does not indicate a passing correctness test",
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (LIVE_PATH, SIZER_PATH)
        },
        "negative_ev_entry": {
            "input": {"p_win_pct": 35.0, "expected_value_r": -0.80, "position": "flat"},
            "observed": low_ev_result,
            "bug_reproduced": low_ev_result[0] == "BUY",
            "intended_correction": "Use a coherent expected-return decision, rather than silently ignoring predicted edge.",
        },
        "displayed_stop_not_executed": {
            "input": {"entry": 100.0, "price": 90.0, "displayed_stop_pct": 0.008},
            "observed": loss_result,
            "bug_reproduced": loss_result[0] == "HOLD",
            "intended_correction": "The documented per-position stop must match actual execution behavior.",
        },
        "share_exceeds_existing_budget": {
            "input": {"equity": 1000.0, "buying_power": 950.0, "price": 1000.0},
            "observed": sizing,
            "bug_reproduced": sizing["notional"] > sizing["available_buying_power"],
            "intended_correction": "Return quantities that respect the already configured budget.",
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
