---
title: Quant AI High-Consistency Autonomous Trading Platform
emoji: 🚀
colorFrom: blue
colorTo: green
sdk: static
pinned: false
---

# 🚀 Quant.ai: High-Consistency Autonomous Quant Trading Platform

Quant.ai is an autonomous, high-consistency quantitative trading platform built with a 2-track low-latency architecture, advanced machine learning alpha models, and self-reflecting reinforcement learning (RL) agents.

---

## 🌟 Key Features
- **Ultra-Low Latency C++ Signal Engine**: C++20 Order Flow Imbalance (OFI) and MicroPrice drift calculation with Pybind11 Python bindings.
- **Advanced ML Alpha Models**: LOB Microstructure ML Engine & Multi-Head Self-Attention Transformer Alpha Model.
- **Autonomous Hands-Off Execution**: 09:45-11:30 & 13:30-15:45 EST timing window filtering, liquidity-capped execution (1.0% of 5m volume).
- **Max-Profit Pyramid Engine**: Cross-sectional capital concentration (60% allocated to top momentum leader) with dynamic 2.5x pyramid scaling on floating profit.
- **Daily EOD Auto-Reflection Engine**: EOD trade attribution, mistake taxonomy, and RL Q-Table auto-tuning (`rl_trading_agent.joblib`).

---

## 📚 Documentation & History Logs
- 📜 **Strategy Evolution & Dialogue History**: See [STRATEGY_EVOLUTION_HISTORY.md](file:///Users/yuliangpeng/Desktop/Quant/STRATEGY_EVOLUTION_HISTORY.md) for the complete narrative history of strategy discussions, user design directives, logic changes, and historical diagnostic reviews (7/31 ~ 8/22).
- 📋 **System Walkthrough**: See [walkthrough.md](file:///Users/yuliangpeng/.gemini/antigravity-ide/brain/19a15ef7-89b5-47d8-9844-cc56772c8655/walkthrough.md) for verification results and unit test logs.

---

## 🛠️ Quick Start

```bash
# 1. Run full backend test suite (24 tests)
python3 -m pytest backend/tests/ -v

# 2. Run Max-Profit Strategy Benchmark
python3 run_max_profit_simulation.py --capital 500000

# 3. Run Daily EOD Auto-Reflection Engine
python3 run_daily_reflection.py --date 2026-08-22
```
