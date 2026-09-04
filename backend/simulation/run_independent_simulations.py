# backend/simulation/run_independent_simulations.py
"""
Master Runner for Zero-Overlap Independent Ticker Simulations
Based on Dr. GP Saggese's Quant Research Principles:
1. No cross-asset overlap or pooled dilution.
2. Separate dedicated pipelines for distinct stock characteristics:
   - SNDK: High Momentum Breakout / Trend-Holding Leader
   - TSLA: Bear Expansion / Breakdown & Long Prohibition
   - NVDA: Morning Pop & Fade / Mean-Reversion Specialist
   - MSTR: High-Beta Crypto Proxy Momentum
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.simulation.simulate_sndk import run_sndk_simulation
from backend.simulation.simulate_tsla import run_tsla_simulation
from backend.simulation.simulate_nvda import run_nvda_simulation
from backend.simulation.simulate_mstr import run_mstr_simulation

def main():
    print("\n" + "#" * 85)
    print("      QUANT.AI - 独立个股零重叠 (ZERO-OVERLAP) 量化模拟与环境实证套件")
    print("      参考标准: Dr. GP Saggese 因子-残差解构与 5~30 分钟波段趋势持仓论")
    print("#" * 85 + "\n")

    print("\n>>> [1/4] 启动 SNDK 独立模拟 (大动量突破与单边锁仓)...")
    run_sndk_simulation()

    print("\n>>> [2/4] 启动 TSLA 独立模拟 (单边下行与破位严禁抄底)...")
    run_tsla_simulation()

    print("\n>>> [3/4] 启动 NVDA 独立模拟 ('先涨后跌' 冲高回落与均值防守)...")
    run_nvda_simulation()

    print("\n>>> [4/4] 启动 MSTR 独立模拟 (高贝塔加密叙事共振波段)...")
    run_mstr_simulation()

if __name__ == "__main__":
    main()
