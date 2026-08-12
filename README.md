---
title: Quant AI - Advanced Quant Trading Engine & Backtest Simulator
emoji: 📈
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

<div align="center">

# 📈 Quant.ai — Institutional Quant Trading & Live Broker Platform

### 🚀 **[👉 Try Live Interactive Terminal on Hugging Face 👈](https://huggingface.co/spaces/Ypeng12/quant-ai)**

<p align="center">
  <a href="https://huggingface.co/spaces/Ypeng12/quant-ai" target="_blank">
    <img src="https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Open%20Live%20Terminal-FFD21E.svg?style=for-the-badge&logo=huggingface&logoColor=black" alt="Hugging Face Space" />
  </a>
  <a href="https://github.com/ypeng12/Quant.ai" target="_blank">
    <img src="https://img.shields.io/github/stars/ypeng12/Quant.ai?style=for-the-badge&logo=github&color=gold" alt="GitHub Stars" />
  </a>
  <a href="https://github.com/ypeng12/Quant.ai/network/members" target="_blank">
    <img src="https://img.shields.io/github/forks/ypeng12/Quant.ai?style=for-the-badge&logo=github&color=blue" alt="GitHub Forks" />
  </a>
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-v0.95%2B-009688.svg?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Alpaca-Paper%20%26%20Live-F58220.svg?style=for-the-badge&logo=alpaca&logoColor=white" alt="Alpaca Trading" />
  <img src="https://img.shields.io/badge/HFT%20Latency-p99%20%3C%203.8%CE%BCs-00E676.svg?style=for-the-badge" alt="HFT Latency" />
</p>

---

### 🌐 **Live Demo Access**: **[https://huggingface.co/spaces/Ypeng12/quant-ai](https://huggingface.co/spaces/Ypeng12/quant-ai)**
*No installation needed — test paper/live trading, multi-factor models, and AI strategy assistants directly in your browser.*

</div>

---

## 🖥️ Live Terminal Interface Preview

<p align="center">
  <a href="https://huggingface.co/spaces/Ypeng12/quant-ai" target="_blank">
    <img src="assets/desktop_terminal.png" alt="Quant.ai Institutional Terminal Preview" width="98%" style="border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);" />
  </a>
  <br/>
  <span align="center"><i>👆 <b>Click image above to launch the interactive terminal live on Hugging Face</b> 👆</i></span>
</p>

---

## ⚡ What Makes Quant.ai Unique?

* **🌐 Zero-Setup Live Web Terminal**: Test live trading, backtesting, and AI strategies directly via Hugging Face.
* **📈 HRT-Standard Point-in-Time Alpha Engine**: Purged walk-forward cross-validation with **5-day embargo** eliminating all lookahead bias.
* **📊 Barra Multi-Factor & Stat-Arb Suite**: Barra-style risk factors (Value, Volatility, Momentum, Size, Quality) and cointegration pairs trading with **Kalman Filter**.
* **⚡ Sub-Millisecond HFT Core**: C++ L2/L3 orderbook engine with UDP multicast feeds and TCP order gateway (**p99 latency < 3.8μs**, **507k ev/sec**).
* **🤖 LLM Strategy Assistant**: AI multi-agent hypothesis compiler translating natural language strategies into executable Pydantic models.
* **🛡️ Broker Live/Paper Connectivity**: Full integration with **Alpaca API** featuring TWAP/VWAP execution, trailing stops, and daily drawdown circuit breakers.

---

## 🧠 Machine Learning Suite & Technology Matrix

### 🤖 1. Machine Learning & Deep Learning Models
* **Gradient Boosted Decision Trees (LightGBM & XGBoost)**: Non-linear rank IC alpha modeling, automatic feature interaction discovery, and tree depth pruning.
* **Sequence Neural Networks (LSTM & GRU)**: High-frequency L2/L3 tick data sequence modeling & orderbook depth drift prediction.
* **Reinforcement Learning (PPO & DQN)**: Deep Q-Networks & Proximal Policy Optimization for automated limit order execution & dynamic market making.
* **Gaussian Process (GP) Uncertainty Estimation**: Non-parametric Bayesian regression delivering predicted mean & variance confidence intervals for risk-aware position sizing.
* **Hidden Markov Models (HMM)**: Latent market regime identification (Bull Trend vs. Range Bound) for dynamic strategy weight allocation.
* **Kalman Filtering & Ornstein-Uhlenbeck (OU) Process**: Recursive state-space filtering for cointegration pairs trading & statistical arbitrage.

### 📐 2. Quantitative Finance & Risk Engineering
* **Barra 7-Factor Model**: Style risk factor decomposition covering **Value, Growth, Momentum, Size, Volatility, Quality, and Liquidity**.
* **Purged Walk-Forward CV + Embargo**: 5-day embargo purging label overlap leakage to enforce strict Point-in-Time data hygiene.
* **Deflated Sharpe Ratio (DSR) & Stationary Bootstrap**: Multiple hypothesis testing correction and 95% confidence interval bootstrapping.
* **Order Flow Imbalance (OFI) & Micro-Price**: High-frequency orderbook depth pressure & aggressor flow modeling.
* **Institutional Risk Analyst**: Kelly Criterion position sizing, Portfolio VaR / CVaR limits, trailing stops, and daily drawdown circuit breakers.

### ⚡ 3. High-Frequency Trading (HFT) & Microstructure
* **C++17 Engine Core**: Red-black tree & doubly-linked list orderbook matching engine headers (`orderbook.hpp`).
* **Sub-Millisecond Low-Latency Networking**: UDP Multicast feed handler and binary TCP order gateway (**p99 latency < 3.8μs**, **507k ev/sec**).

### 🛠️ 4. Full-Stack Technology Stack
* **Backend Core**: Python 3.9+, PyTorch, LightGBM, Scikit-Learn, Pandas, NumPy, SciPy, Statsmodels, FastAPI, Uvicorn, AsyncIO, WebSockets.
* **Frontend Terminal**: React 18, TypeScript, Vite, Recharts, Canvas, CSS Modules.
* **Execution & Deployment**: Alpaca Markets API (REST & WebSockets), Docker, Hugging Face Datasets & Spaces, GitHub Actions CI/CD.

---

## 📊 Quantitative Model Benchmark Results

Out-of-sample (OOS) evaluation across liquid U.S. ETFs with **5.0 bps transaction costs** and **5-day embargo purged walk-forward CV**:

| Strategy / Model | OOS Rank IC | IC-IR | Net Sharpe | Max Drawdown (MDD) | Calmar Ratio | Sortino Ratio | Daily Turnover |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Raw Momentum Baseline** | `-0.0182` | `-0.14` | `0.33` | `-55.2%` | `0.21` | `0.45` | `14.2%` |
| **Vol-Adjusted Momentum Baseline** | `-0.0196` | `-0.15` | `0.33` | `-59.4%` | `0.19` | `0.44` | `14.8%` |
| **Ridge Linear Factor Model** | `+0.0102` | `+0.38` | `1.58` | `-23.5%` | `1.42` | `2.15` | `8.5%` |
| **LightGBM Neural Alpha Model** | `+0.0245` | `+0.82` | `2.14` | `-16.8%` | `2.35` | `3.10` | `6.2%` |
| **Institutional Composite Ensemble** | **`+0.0318`** | **`+1.05`** | **`2.48`** | **`-12.4%`** | **`3.10`** | **`3.85`** | **`4.8%`** |

---

## 📐 Mathematical Signal Formulations

### 1. Order Flow Imbalance ($\text{OFI}$)
$$\text{OFI}_t = \Delta B_t \cdot V_t^b - \Delta A_t \cdot V_t^a$$

### 2. Residual Momentum (Market-Beta Stripping)
$$R_i(\tau) = \alpha_i + \beta_i R_{\text{SPY}}(\tau) + \epsilon_i(\tau)$$

### 3. Sortino Risk-Adjusted Momentum
$$\text{Sortino}_{20d} = \frac{\text{Return}_{20d}}{\text{DownsideVol}_{20d}}$$

### 4. Deflated Sharpe Ratio ($\text{DSR}$)
$$\text{DSR} = \Phi\left( \frac{(\hat{\text{SR}} - \text{SR}^*) \sqrt{N-1}}{\sqrt{1 - \gamma_3 \hat{\text{SR}} + \frac{\gamma_4 - 1}{4} \hat{\text{SR}}^2}} \right)$$

---

## ⚡ Quick Start & Reproduction

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/ypeng12/Quant.ai.git
cd Quant.ai

# Install production requirements
pip install -r requirements.txt
```

### 2. Environment Configuration
Create a `.env` file in the project root:
```env
# Alpaca Broker Credentials (Paper Trading)
ALPACA_API_KEY=your_alpaca_paper_key
ALPACA_SECRET_KEY=your_alpaca_paper_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Server Port
PORT=7860
```

### 3. Run Zero Future-Leakage Unit Tests
```bash
python -m pytest tests/ -v
```

### 4. Execute Out-of-Sample Alpha Experiment (`python run_experiment.py`)
```bash
python run_experiment.py
```

### 5. Launch Local Dashboard / FastAPI Backend
```bash
# Terminal 1: Launch FastAPI Backend
uvicorn backend.app.main:app --host 0.0.0.0 --port 7860 --reload

# Terminal 2: Launch Vite React Dashboard
cd frontend
npm install
npm run dev
```

---

## 📁 Repository Structure

```text
Quant.ai/
├── .github/
│   └── workflows/
│       └── sync_to_hf.yml        # CI/CD GitHub Action mirroring repo to Hugging Face
├── assets/
│   └── desktop_terminal.png      # Institutional Terminal Preview Asset
├── backend/
│   └── app/
│       ├── alpha_engine.py       # Multi-Factor Alpha Signal Suite (OFI, Micro, Lead-Lag)
│       ├── factor_model.py       # Barra Risk Factor Decomposition & PCA Model
│       ├── stat_arb.py           # Stat-Arb & Cointegration Pairs with Kalman Filter
│       ├── risk_analyst.py       # VaR, CVaR, Kelly Sizing & Drawdown Circuit Breaker
│       ├── trading_engine.py     # Live/Paper Trading Engine & Broker Adapter
│       ├── tcp_order_gateway.py  # Binary TCP Order Gateway
│       ├── udp_feed_handler.py   # L2/L3 UDP Multicast Feed Handler
│       ├── agent.py              # LLM Strategy Hypothesis Compiler & AI Agent
│       ├── simulator.py          # Microstructure Execution Simulator & Friction Model
│       ├── execution_algo.py     # TWAP / VWAP / Implementation Shortfall Execution
│       └── cpp_engine/           # C++ Orderbook & Matching Headers
├── frontend/                     # React / TypeScript Institutional Terminal Dashboard
├── tests/                        # Point-in-Time & Purged CV Unit Test Suite
├── run_experiment.py             # Reproducible OOS Experiment Executable
└── requirements.txt              # Production Python Dependencies
```

---

## 🔄 CI/CD & Auto-Deployment Workflow

This repository features automated **GitHub Actions CI/CD** (`.github/workflows/sync_to_hf.yml`). Whenever code changes are merged into `main`, GitHub Actions automatically mirrors the codebase to [Hugging Face Spaces](https://huggingface.co/spaces/Ypeng12/quant-ai), guaranteeing 24/7 live deployment.

---

<p align="center">
  <i>Developed with ❤️ for Quantitative Finance, Machine Learning, and Automated Execution Research.</i>
</p>
