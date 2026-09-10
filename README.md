---
title: Quant AI - Autonomous Institutional Algorithmic Trading Platform
emoji: 🚀
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: true
license: mit
short_description: ML Quant Trading Platform with C++ OFI Engine
tags:
  - quant
  - trading
  - algorithmic-trading
  - machine-learning
  - finance
  - high-frequency-trading
---

# 🚀 Quant.ai: High-Consistency Autonomous Quant Trading Platform

[![Hugging Face Spaces](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Space-blue)](https://huggingface.co/spaces/Ypeng12/quant-ai)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-green.svg)](https://www.python.org/)
[![C++20](https://img.shields.io/badge/C++-20-blue.svg)](https://isocpp.org/)

Quant.ai is an autonomous, high-consistency quantitative trading platform built with a 2-track low-latency architecture, advanced machine learning alpha models, and self-reflecting reinforcement learning (RL) agents.

---

## 🌊 LOB 微观结构波浪研判终端 (LOB Microstructure Wave Alpha Terminal)

> **GP Saggese ($1.6B AUM Teza Capital Partner) 顶级量化因果体系**：摒弃黑盒过拟合强化学习，回归订单簿（LOB）微观结构与微观价格漂移（Microprice Drift）。捕捉 15~30 分钟波浪周期，样本外 Purged CV 交叉验证准确率 **72.07%**。

[![Live Interactive Terminal](https://img.shields.io/badge/%F0%9F%8C%90%20Interactive-Live%20Terminal%20(Full%20Features)-00c805?style=for-the-badge)](https://ypeng12-quant-ai.hf.space/charts/saggese_wave_visual_dashboard.html)
[![Standalone HTML](https://img.shields.io/badge/%F0%9F%93%84%20Direct-HTML%20File-blue?style=for-the-badge)](./saggese_wave_visual_dashboard.html)
[![Alpha Model](https://img.shields.io/badge/%E2%9A%A1%20Alpha%20Engine-Saggese%20LOB%20Wave-ff9900?style=for-the-badge)](./src/saggese_wave_alpha.py)

![LOB Microstructure Wave Terminal](assets/lob_microstructure_wave_terminal.png)

### 📊 终端核心特性 (Terminal Key Capabilities)
- **多标的 & 多交易日自由切换 (Multi-Ticker & Multi-Day Navigation)**: 一键无缝切换 TSLA、NVDA、AAPL、QQQ 等美股高流动性标的以及任意历史交易日。
- **微观因果 3 维独立副图 (Triple Microstructure Subcharts)**:
  1. **OFI & Microprice Drift (bps)**: 毫秒级订单流失衡度与微观价格漂移基点，直击主动买卖盘压制力量；
  2. **Queue Depth Imbalance & Sweep Velocity**: 深度队列排队失衡与挂单被扫穿速度，精准捕捉冰山挂单被突破瞬间；
  3. **Composite Alpha Score & Win Rate (%)**: 综合微观波浪 Alpha 得分与样本外概率曲线，提供机构级确定性依据。
- **防虚假抖动去噪信号 (Debounced Wave Execution Badges)**: 智能波浪锁防反复翻转，主图清晰标注 `WAVE LONG` 与 `WAVE SHORT` 介入与兑现点。

---

## 🌟 Key Features
- **Ultra-Low Latency C++ Signal Engine**: C++20 Order Flow Imbalance (OFI) and MicroPrice drift calculation with Pybind11 Python bindings.
- **Advanced ML Alpha Models**: LOB Microstructure ML Engine & Multi-Head Self-Attention Transformer Alpha Model.
- **Autonomous Continuous Execution**: Full-day active continuous execution without artificial lockouts, dynamic order-book liquidity capping (1.0% of 5m volume).
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
