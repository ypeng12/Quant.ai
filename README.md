---
title: Quant AI - Autonomous Institutional Algorithmic Trading Platform
emoji: 🚀
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: true
license: mit
short_description: Institutional ML Trading Platform with C++20 OFI Engine & LOB Alpha
tags:
  - quant
  - trading
  - algorithmic-trading
  - machine-learning
  - finance
  - high-frequency-trading
---

# 🚀 Quant.ai: Autonomous Institutional Quantitative Trading Platform
### Ultra-Low Latency C++20 Engine · Microstructure LOB Causal Alpha · Self-Evolving Reinforcement Learning

<div align="center">

[![Hugging Face Spaces](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Live%20Space%20Demo-blue?style=for-the-badge&logo=huggingface)](https://huggingface.co/spaces/Ypeng12/quant-ai)
[![Live LOB Terminal](https://img.shields.io/badge/%F0%9F%8C%90%20Live%20Terminal-LOB%20Wave%20Alpha-00c805?style=for-the-badge)](https://ypeng12-quant-ai.hf.space/charts/saggese_wave_visual_dashboard.html)
[![C++20 Engine](https://img.shields.io/badge/C++20-Low%20Latency%20Engine-00599C?style=for-the-badge&logo=c%2B%2B)](https://isocpp.org/)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

**[🌐 Launch Live Web App (Hugging Face Space)](https://huggingface.co/spaces/Ypeng12/quant-ai)** · 
**[🌊 Live Real-Time LOB Wave Terminal](https://ypeng12-quant-ai.hf.space/charts/saggese_wave_visual_dashboard.html)** · 
**[📚 Quantitative Research Handbook](docs/QUANT_RESEARCH_HANDBOOK.md)** · 
**[📜 System Evolution Chronicle](docs/STRATEGY_EVOLUTION_HISTORY.md)**

</div>

---

## 🌟 Executive Overview

**Quant.ai** is an institutional-grade, fully autonomous quantitative trading platform designed for high-volatility US equities (e.g., TSLA, NVDA, MSTR, SNDK). The system bridges **nano-second C++20 execution mechanics**, **causal limit order book (LOB) machine learning**, and **self-reflective reinforcement learning (RL)** into a unified, high-expectancy trading architecture.

Unlike naive retail bots relying on lagging technical indicators or rigid stop-halt lockouts, Quant.ai operates strictly on **continuous probabilistic pricing**, **dynamic microstructural order flow signals**, and **maximum expected utility $E[R]$**. It delivers relentless round-the-clock bidirectional long/short alpha while enforcing rigorous mathematical risk budgeting.

```
                         ┌─────────────────────────────────────────┐
                         │    Alpaca SIP / IEX Real-Time Feeds     │
                         └───────────────────┬─────────────────────┘
                                             │ WebSocket / Raw Ticks
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ⚡ Ultra-Low Latency C++20 Core Engine                                                          │
│ ├─ NASDAQ ITCH 5.0 Binary Deserializer ────► Microsecond L2/L3 Order Book Reconstruction       │
│ ├─ Lock-Free SPSC RingBuffer ──────────────► Sub-50μs POSIX Shared Memory IPC (SHM)            │
│ └─ AVX-2 SIMD Vector Acceleration ─────────► Real-time Vectorized OFI & Microprice Drift       │
└────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                             │ Zero-Copy IPC / Pybind11
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 🧠 Institutional ML & Decision Intelligence Core                                              │
│ ├─ GP Saggese Limit Order Book Wave Model ─► 15~30m Microstructure Alpha (Purged CV 72.07%)    │
│ ├─ Multi-Model Calibrated Probabilities ──► Platt Scaling Win Rate + MFE/MAE Dynamic Regressors│
│ ├─ Hidden Markov Model (HMM) ──────────────► Dynamic Regime Classification (Bull / Bear / Chop)│
│ └─ Post-Market Self-Reflecting RL ─────────► Autonomous Mistake Attribution & Q-Policy Update  │
└────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                             │ Actionable Orders
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 🚀 Max-Profit Dynamic Execution Matrix                                                         │
│ ├─ Cross-Sectional Leader Concentration ───► 60% Capital Allocation to Top Momentum Alpha      │
│ ├─ Staged Dynamic Golden Pyramid (60%) ────► Aggressive Profit Compounding on Trend Discovery │
│ └─ Smart Order Routing (SOR) ──────────────► Maker/Taker Cost Optimization & Impact Modeling   │
└────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                             │ HTTP & WebSockets
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 🖥️ Next-Gen Institutional Interactive Terminals                                               │
│ ├─ 🌊 Live LOB Wave Terminal ──────────────► Real-time 5m Intraday Streaming + 7 Causal Panels │
│ ├─ 📈 Robinhood-Style Forecast Overlay ────► Neon Real-Time Track vs ML Extrapolated Trajectory│
│ └─ 📊 Full-Stack React Executive Cockpit ──► Live Equity Radar, Exposure Gauges, & Audit Logs  │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 💎 Core Architectural Pillars

### 1. ⚡ Ultra-Low Latency C++20 Engine (`cpp_engine/`)
* **Binary Feed Parsing**: High-performance binary decoders for NASDAQ ITCH 5.0 and OUCH protocol, processing millions of market events per second with zero memory allocations on the critical path.
* **Microsecond Limit Order Book**: Cache-friendly contiguous memory order book supporting tick-by-tick level insertions, cancels, price-level sweeps, and cross-matching.
* **Lock-Free SPSC & Shared Memory**: Sub-50 microsecond IPC across C++ market-feed daemons and Python AI inference engines using lock-free single-producer single-consumer ring buffers in POSIX shared memory.
* **AVX-2 SIMD Feature Computation**: Vectorized math pipelines computing rolling volatility, correlation matrices, and Order Flow Imbalance (OFI) across multi-asset universes.

### 2. 🧠 Institutional Causal Microstructure ML (`backend/app/ml/`)
* **Giacinto Paolo (GP) Saggese (Teza Capital) Order Book Dynamics**:
  Replacing uninterpretable deep black-boxes with causal limit order book physics. The engine computes **7 core microstructural alphas**:
  1. **Order Flow Imbalance (OFI)**: Normalized tick-by-tick changes in bid/ask depth volume;
  2. **Microprice Drift (bps)**: Depth-weighted center-of-mass price drift relative to mid-price;
  3. **Queue Imbalance Ratio**: Dynamic queue exhaustion metrics detecting iceberg walls;
  4. **Sweep Velocity**: Aggressive market taker consumption speed;
  5. **Volume Acceleration**: 5-minute surge acceleration over historical baseline;
  6. **Wick Absorption Ratio**: Intraday candle wick capital rejection index;
  7. **HRT Toxic Flow**: Adverse selection toxicity gauge inspired by high-frequency market making.
* **Strict Purged & Embargoed Cross-Validation**:
  Designed strictly under Marcos Lopez de Prado’s framework. Features zero lookahead bias with out-of-sample purged validation accuracy reaching **61.97% ~ 72.07%**.
* **Calibrated Win-Rate & Dynamic Expectancy Boundary**:
  Platt-scaled win-rate probabilities $P_{\text{win}}$ coupled with Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE) regressors to dynamically size positions based on pure mathematical expectancy:
  $$E[R] = P_{\text{win}} \cdot \mathbb{E}[\text{MFE}] - (1 - P_{\text{win}}) \cdot \mathbb{E}[\text{MAE}]$$

![Microstructure Wave Terminal](assets/lob_microstructure_wave_terminal.png)

### 3. 🔄 Self-Reflecting Reinforcement Learning (`scripts/run_daily_reflection.py`)
* **Autonomous Mistake Taxonomy**:
  End-of-day automated audit analyzing every completed execution. It automatically classifies execution anomalies into a causal taxonomy (e.g., knife-catching against institutional distribution sweeps, false-breakout chase, low-volatility overtrading).
* **Dynamic Q-Table Policy Gating**:
  The RL agent updates strategy decision weights (`Q-Policy Gate`) iteratively based on daily real-world feedback without manual code modifications, allowing the system to continuously adapt to changing market volatility regimes.

### 4. 🚀 Max-Profit Aggressive Execution & Position Compounding
* **Continuous Multi-Regime Execution**:
  No artificial lockouts or circuit breakers. The system maintains continuous long/short deployment wherever positive mathematical expectation exists.
* **Cross-Sectional Leader Momentum Concentration**:
  Real-time relative strength scoring concentrates up to 60% of available capital into the single strongest market leader (e.g., riding full-day trend expansions like MSTR +5.7%).
* **Dynamic Staged 60% Golden Pyramid**:
  Once an initial base position generates positive floating alpha and structure confirmation, the system triggers a secondary pyramid scale-in to compound winning waves to maximum profit capacity.
* **Smart Order Routing (SOR)**:
  Real-time estimation of queue replenishment rates, dynamically balancing passive maker fills (earning rebates) against aggressive taker sweeps (guaranteeing fill urgency).

| Win-Rate Calibration Curve | Monte Carlo CVaR Tail Risk | SOR Maker vs Taker Optimization |
| :---: | :---: | :---: |
| ![Calibration](assets/probability_calibration_curve.png) | ![CVaR](assets/monte_carlo_cvar_distribution.png) | ![SOR](assets/sor_maker_vs_taker_comparison.png) |

### 5. 🖥️ Next-Gen Visual Analytics Terminals
* **🌊 Real-Time LOB Microstructure Wave Terminal ([Try Live on Hugging Face](https://ypeng12-quant-ai.hf.space/charts/saggese_wave_visual_dashboard.html))**:
  * Seamless instant ticker switching (TSLA, NVDA, MSTR, SNDK, etc.);
  * **🌟 Live TODAY Intraday Streaming**: Auto-polls fresh 5m bars, microprice drift, and OFI volume histograms every 8 seconds;
  * Smart debounced wave inflection markers clearly highlighting `WAVE LONG` and `WAVE SHORT` reversal opportunities.
* **📈 Robinhood-Style Forecast Trajectory Overlay**:
  * Neon-lit real-time historical path juxtaposed with dashed ML forecasted trajectory bands;
  * Forward extrapolation of expected 15~30 minute order book wave trajectories.
* **📊 Full Institutional React Cockpit ([frontend/](frontend/))**:
  * Real-time portfolio NAV equity curve, sector concentration radar, live order stream, and risk metrics.

![Desktop Terminal](assets/desktop_terminal.png)

---

## 📂 Repository Architecture

```bash
Quant.ai/
├── .github/          # GitHub Actions CI/CD & Automated Hugging Face Space Synchronization
├── assets/           # Institutional terminal screenshots, microstructure charts, and badges
├── backend/          # FastAPI Async Backend, WebSocket Services & ML Alpha Algorithms
│   ├── app/          # Core Trading Platform
│   │   ├── broker/   # Alpaca Direct Market Access (DMA) Gateway & Ledger
│   │   ├── ml/       # 7 Causal LOB Models, Probability Calibration, & Real-time Wave Services
│   │   └── ipc/      # POSIX Shared Memory & Lock-Free IPC Interop Bridge
│   └── data/         # Historical Dataset Stores & Visual Chart Pipelines
├── cpp_engine/       # C++20 Nano-Second Low Latency Core (ITCH/OUCH, LOB, RingBuffers)
├── cpp_quant_engine/ # Pre-compiled C++ Binary Python Extensions
├── docs/             # 📚 Academic Research Handbook, Foundational Papers (PDFs), & System Logs
│   ├── papers/       # Cont-Stoikov, Saggese, Bouchaud, Almgren-Chriss Reference Papers
│   ├── QUANT_RESEARCH_HANDBOOK.md    # Mathematical Proofs & Model Formulations
│   └── STRATEGY_EVOLUTION_HISTORY.md # Complete Development History & Architectural Decisions
├── frontend/         # React + Vite + TypeScript Institutional Trading Cockpit
├── reports/          # Strategy Backtest Audits & Monte Carlo Risk Reports
├── scripts/          # 🛠️ 12 Simulation, Optimization, Training, & Visual Generation Scripts
├── tests/            # Automated Unit & Regression Test Suite
├── Dockerfile        # Production Multi-Stage Container Image
├── Makefile          # One-Click Build, Test, & Execution Commands
├── requirements.txt  # Python Core Dependencies
└── README.md         # Master Institutional Repository Documentation
```

---

## 🛠️ Quick Start Guide

### 1. Clone Repository & Install Dependencies
```bash
git clone https://github.com/ypeng12/Quant.ai.git
cd Quant.ai

# Install Python 3.11 core dependencies
pip install -r requirements.txt
```

### 2. Compile C++20 Core Engine (Optional / Production)
```bash
cd cpp_engine
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j4
cd ../..
```

### 3. Launch Local FastAPI Backend & Real-Time Terminals
```bash
# Start FastAPI backend with live microstructural computing engine on port 8000
python3 -m uvicorn backend.main_api:app --host 127.0.0.1 --port 8000 --reload
```
Once launched, open in your browser:
* 🌊 **Live LOB Wave Terminal**: [http://127.0.0.1:8000/saggese_wave_visual_dashboard.html](http://127.0.0.1:8000/saggese_wave_visual_dashboard.html)
* 📈 **Interactive API Docs (Swagger UI)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 4. Run Strategy Simulations & Model Calibration
```bash
# Run full automated test suite
make test

# Execute institutional max-profit multi-asset simulation
python3 scripts/run_max_profit_simulation.py --capital 500000

# Execute post-market self-reflection & RL Q-table update
python3 scripts/run_daily_reflection.py --date 2026-09-11

# Re-generate full multi-ticker LOB wave visual data
python3 scripts/generate_saggese_wave_dashboard.py
```

---

## 📚 Academic & Quantitative Foundations

Quant.ai's mathematical modeling is strictly grounded in peer-reviewed quantitative finance literature:
1. **Cont, R., Kukanov, A., & Stoikov, S. (2014)**: *The Price Impact of Order Book Events*. Journal of Financial Econometrics (Foundational OFI dynamics).
2. **Saggese, G. P. (Teza Capital / University of Maryland)**: *Simple First & Interpretable Tree Models on Limit Order Book Dynamics*.
3. **Almgren, R., & Chriss, N. (2000)**: *Optimal Execution of Portfolio Transactions*. Journal of Risk (Dynamic market impact & Smart Order Routing).
4. **Marcos Lopez de Prado (2018)**: *Advances in Financial Machine Learning*. Wiley (Purged K-Fold Cross-Validation & Deflated Sharpe Ratio audit).
5. **Ledoit, O., & Wolf, M. (2004)**: *A Well-Conditioned Estimator for Large-Dimensional Covariance Matrices*. Journal of Multivariate Analysis (Spectral shrinkage).

For complete mathematical derivations, proof of convergence, and backtest audit trails, please refer to **[docs/QUANT_RESEARCH_HANDBOOK.md](docs/QUANT_RESEARCH_HANDBOOK.md)**.

---

## ⚖️ Disclaimer

*This repository is intended strictly for quantitative finance research, algorithmic engineering, and academic analysis. Live trading involves substantial risk of financial loss. Users must thoroughly evaluate their own risk tolerance and assume full responsibility for all capital deployment and execution outcomes.*
