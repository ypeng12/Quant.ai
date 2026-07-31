---
title: Quant AI - Advanced Quant Trading Engine & Backtest Simulator
emoji: 📈
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# 📈 Quant.ai — Institutional Alpha Research & Live/Paper Trading Platform

<p align="center">
  <a href="https://huggingface.co/spaces/Ypeng12/quant-ai" target="_blank">
    <img src="https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Live%20Demo-FFD21E.svg?style=for-the-badge&logo=huggingface&logoColor=black" alt="Hugging Face Space" />
  </a>
  <a href="https://github.com/ypeng12/Quant.ai" target="_blank">
    <img src="https://img.shields.io/badge/GitHub-Quant.ai-181717.svg?style=for-the-badge&logo=github&logoColor=white" alt="GitHub Repository" />
  </a>
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-v0.95%2B-009688.svg?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Alpaca-Paper%20%26%20Live-F58220.svg?style=for-the-badge&logo=alpaca&logoColor=white" alt="Alpaca Trading" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED.svg?style=for-the-badge&logo=docker&logoColor=white" alt="Docker Ready" />
</p>

> 🚀 **Interactive Terminal Demo**: Experience the deployed terminal live on Hugging Face Spaces 👉 **[huggingface.co/spaces/Ypeng12/quant-ai](https://huggingface.co/spaces/Ypeng12/quant-ai)**

**Quant.ai** is an end-to-end, **Point-in-Time Consistent Quantitative Trading & Paper/Live Execution Platform**. Designed following Hudson River Trading (HRT) and Quantitative Hedge Fund engineering standards, it bridges the gap between **rigorous signal research**, **microstructure execution**, and **real-time broker integration (Alpaca API)**.

---

## 🔥 Key Platform Highlights

### ⚡ 1. Real-Time Live & Paper Trading (Alpaca Integration)
* **Direct Broker Connectivity**: Seamless REST & WebSocket integration with **Alpaca Markets** for real-time order routing, position tracking, and market streaming.
* **Paper & Live Mode Switch**: Flexible environment toggling (`https://paper-api.alpaca.markets` for risk-free simulation vs. live brokerage execution).
* **Execution Algorithmic Suite**: Smart order routing with TWAP, VWAP, and Implementation Shortfall (IS) execution algorithms.
* **Dynamic Portfolio Risk Controls**:
  * Real-time position tracking and ledger recording.
  * Trailing stop-loss triggers and volatility-based position sizing.
  * Drawdown-contingent risk multipliers & consecutive loss protections.

### 🔬 2. HRT-Standard Alpha Research Engine
* **Point-in-Time Data Hygiene**: Strict timestamp truncation at date $t$ to eliminate lookahead bias across U.S. Equity & ETF universes.
* **Purged Walk-Forward Cross Validation + Embargo**: Eliminates overlap leakage across rolling 3-year train / 6-month validation / 6-month OOS test windows with a 5-day embargo.
* **Novel Risk-Adjusted Signals**:
  * **Sortino Momentum**: $\text{Return}_{20d} / \text{DownsideVol}_{20d}$
  * **Residual Momentum**: 60-day rolling OLS stripping `SPY` Market Beta: $R_i(\tau) = \alpha_i + \beta_i R_{\text{SPY}}(\tau) + \epsilon_i(\tau)$
  * **Robust Z-Score Normalization**: Cross-sectional Median/MAD standardization.
* **Multiple Testing Correction**: Deflated Sharpe Ratio (DSR) and Stationary Bootstrap 95% Confidence Intervals.

### 📊 3. Microstructure & Orderbook Engine
* **Order Flow Imbalance (OFI)**: Real-time L2/L3 orderbook imbalance calculation for high-frequency price impact prediction.
* **Friction & Shortfall Modeling**: Multi-tiered transaction cost models with 2–15 bps slippage sensitivity checks.
* **Low-Latency Engine Core**: C++ accelerated order matching engine headers (`orderbook.hpp`).

### 🤖 4. Natural Language Alpha Hypothesis Parser
* LLM-assisted hypothesis compilation translating natural language ideas into validated, executable Pydantic model configurations.

---

## 🎯 Core Research Hypothesis

> **"Can volatility-adjusted and market-beta-residualized cross-sectional momentum signals across liquid U.S. ETFs predict short-term excess returns after transaction costs and execution friction?"**

---

## ⚡ Quick Start & Setup

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/ypeng12/Quant.ai.git
cd Quant.ai

# Install Python requirements
pip install -r requirements.txt
```

### 2. Configure Environment & Alpaca Credentials
Create a `.env` file in the project root:
```env
# Alpaca Broker Credentials (Use Paper Trading for risk-free testing)
ALPACA_API_KEY=your_alpaca_paper_key
ALPACA_SECRET_KEY=your_alpaca_paper_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Server Configuration
PORT=7860
```

### 3. Run Unit Tests (Zero Future Leakage Verification)
```bash
python -m pytest tests/ -v
```

### 4. Execute Out-of-Sample Alpha Experiment (`make oos`)
```bash
python run_experiment.py
```

Outputs:
```text
================================================================================
  QUANT.AI OUT-OF-SAMPLE EXPERIMENT RUNNER
  Hypothesis: Volatility-Adjusted Momentum across Liquid U.S. ETFs
  Lookback: 20d | Holding: 5d | Transaction Cost: 5.0 bps
================================================================================
  --> Raw_Momentum_Baseline        | OOS Rank IC: -0.0182 | Net Sharpe: 0.33 | MaxDD: -55.2%
  --> Vol_Adj_Momentum_Baseline    | OOS Rank IC: -0.0196 | Net Sharpe: 0.33 | MaxDD: -59.4%
  --> Ridge_Linear                 | OOS Rank IC:  0.0102 | Net Sharpe: 1.58 | MaxDD: -23.5%
```

### 5. Launch Local Dashboard / FastAPI Backend
```bash
# Launch FastAPI Backend
uvicorn backend.app.main:app --host 0.0.0.0 --port 7860 --reload
```
Navigate to `http://localhost:7860` in your browser.

---

## 📁 Repository Architecture

```text
Quant.ai/
├── .github/
│   └── workflows/
│       └── sync_to_hf.yml        # CI/CD GitHub Action auto-syncing to Hugging Face
├── backend/
│   └── app/
│       ├── trading_engine.py     # Live/Paper Trading Engine & Portfolio Risk Control
│       ├── simulator.py          # Execution Simulator & Implementation Shortfall Model
│       ├── orderbook_ofi.py      # Microstructure Order Flow Imbalance (OFI) Engine
│       ├── execution_algo.py     # TWAP / VWAP Order Execution Algorithms
│       ├── low_latency_engine.py # High-Frequency Matching Engine Adapter
│       └── cpp_engine/           # C++ Orderbook & Level-2 Matching Headers
├── frontend/                     # React / TypeScript Institutional Dashboard UI
├── src/
│   ├── data/
│   ├── features/
│   ├── labels/
│   ├── validation/
│   ├── models/
│   └── portfolio/
├── tests/                        # Zero Future Leak & Purged CV Unit Tests
├── Dockerfile                    # Hugging Face Space Docker Deployment spec
├── run_experiment.py             # One-command OOS research executable
└── requirements.txt              # Production Python dependencies
```

---

## 🔄 CI/CD & Hugging Face Auto-Sync Workflow

This repository features automated **GitHub Actions CI/CD** (`.github/workflows/sync_to_hf.yml`). 

Whenever changes are merged into the `main` branch, GitHub automatically mirrors and deploys the latest codebase directly to the [Hugging Face Space](https://huggingface.co/spaces/Ypeng12/quant-ai), guaranteeing 24/7 live deployment without manual intervention.

---

## 🤝 Collaborative Development & Branching Model

To ensure platform stability:
* **Feature Branches**: Developers work on dedicated feature branches (e.g. `ypeng12`, `lxc`).
* **Pull Requests (PR)**: Code is tested locally and submitted via PRs to `main`.
* **Deployment Trigger**: Merging to `main` automatically triggers Hugging Face live deployment.

---

<p align="center">
  <i>Developed with ❤️ for Quantitative Finance, Machine Learning, and Automated Execution Research.</i>
</p>
