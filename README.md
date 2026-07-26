---
title: Quant AI - Advanced Quant Trading Engine & Backtest Simulator
emoji: 📈
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Quant.ai - Advanced Quant Trading Engine & Backtest Simulator

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue.svg" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-v0.95%2B-009688.svg" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-v18-61dafb.svg" alt="React" />
  <img src="https://img.shields.io/badge/Vite-v4-646cff.svg" alt="Vite" />
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License" />
</p>

Quant.ai is an end-to-end, production-ready AI quantitative research platform, backtest engine, and live trading simulator. Built with a Python FastAPI backend and a React (TypeScript + Vite) interactive trading terminal, it combines natural language LLM tool calling, 22 vectorized K-line pattern recognizers, dynamic market regime routing, ATR volatility risk sizing, walk-forward optimization, and real-time Alpaca broker integration.

<p align="center">
  <img src="assets/desktop_terminal.png" width="100%" alt="Quant.ai Desktop Trading Terminal" />
</p>

---

## 🚀 Key Features

### 1. 🧠 AI Natural Language Strategy Agent & Tool Calling
- **Natural Language Parsing**: Translates raw strategy descriptions (e.g. *"Backtest TSLA Donchian breakout on daily bars with 2x ATR stop"*) into validated strategy JSON configurations using OpenAI / Gemini LLM tool calling.
- **Typed Tool Execution Graph**: Orchestrates multi-step workflow across backend execution tools (`fetch_market_data` → `compute_indicators` → `run_backtest` → `generate_risk_report`).
- **Resilient Fallback Engine**: Built-in regex rule parser guarantees 100% operational availability even without API keys.

### 2. 📊 Advanced K-Line Feature & Pattern Recognition
- **12 K-Line Numerical Features**: Computes body ratio, upper/lower shadow ratios, gaps, relative volume (RVOL), and trend context dynamically.
- **22 Quantifiable Candlestick Patterns**: Vectorized detection for patterns like Hammer, Shooting Star, Bullish/Bearish Engulfing, Piercing, Dark Cloud Cover, Morning/Evening Star, Three White Soldiers, Rising/Falling Three Methods, Gap Breakout, Exhaustion Gaps, and Neckline breakouts for W-Bottoms and M-Tops.

### 3. 🚦 Dynamic Market Regime Router
- Dynamically classifies the market into four regimes:
  - `trend_up`: Strong bullish trend. Activates trend-following strategies (Donchian breakout, EMA crossover).
  - `trend_down`: Bearish trend. Suspends buy operations and goes into defense.
  - `high_volatility`: Extreme volatility (ATR/Close in top 10%). Enforces cash preservation.
  - `range_bound`: Oscillating market. Activates mean reversion (Bollinger Bands oversold) and candlestick reversals.

### 4. 🛡️ Institutional-Grade Multi-Layer Risk Control
- **ATR-Based Volatility Sizing**: Dynamically calculates trade size based on account equity, ATR stop-distance, and risk percentage.
- **Soft Drawdown Circuit Breaker (7% DD / 5 Losses)**: Automatically cuts position sizes by 50%.
- **Hard Drawdown Lock (12% DD)**: Locks the trading engine (risk multiplier goes to 0) to protect capital from extreme market drawdowns.

### 5. 📉 Automated AI Risk Analyst
- **Diagnostic Risk Reports**: Evaluates Sharpe Ratio, Calmar Ratio, Profit Factor, max drawdown duration, transaction friction, and regime distribution post-backtest.
- **Overfitting Risk Assessment**: Identifies fragile parameters and detects potential over-optimization.

### 6. 🔄 Walk-Forward Parameter Optimization
- Features a rolling optimization pipeline (`walk_forward.py`) that divides history into training and test intervals.
- Optimizes parameters (strategy mode, ATR multiplier, RSI) by maximizing the drawdown-penalized net profit (Calmar-like metric) and validates performance out-of-sample.

### 7. ⚡ Alpaca Live & Paper Trading Integration
- Integrates Alpaca Broker REST & WebSocket APIs (`alpaca_adapter.py`, `live_runner.py`) for live market execution, active order management, position monitoring, and paper trading account syncing.

### 8. 🧪 SQLite Experiment Tracking & Reproducibility
- SQLite-backed experiment manager (`experiment_manager.py`) persisting full strategy configurations, benchmark performance metrics, and trade ledgers for side-by-side experiment comparison.

### 9. 🌅 Market Open Focus & Opening Range Breakout (ORB) Strategy
- **Market Open Focus Mode**: Targets high-volatility market opening (09:30 - 10:15 EST). Restricts buying to high-momentum windows and performs force liquidation at 10:30 EST.
- **Opening Range Breakout (ORB)**: Precomputes opening high/low from the first 5 minutes of regular hours (09:30 - 09:35 EST) and triggers high-probability breakout buys on high volume (RVOL > 1.2), using opening range low as a hard failure stop-loss.

### 10. 🎬 Historical Replay Mode & Intraday Trade Inspector
- **Granular 1m Simulation**: Step-by-step 1m bar market replay with 50ms tick speed controls.
- **Intraday Trade Inspector**: Click any ledger trade to immediately center Lightweight Charts on the precise buy/sell timestamp.

---

## 📁 Project Structure

```text
├── backend/
│   ├── app/
│   │   ├── agent.py            # Natural Language Strategy LLM Parser & Tool Execution Engine
│   │   ├── risk_analyst.py     # AI Risk Analyst & Post-Backtest Diagnostic Engine
│   │   ├── experiment_manager.py # SQLite Experiment Tracker & History Store
│   │   ├── config.py           # Trade and risk configurations
│   │   ├── data_manager.py     # YFinance data loading, technical indicators, and regimes
│   │   ├── patterns.py         # 22 K-line patterns and W-Bottom/M-Top detection
│   │   ├── strategy.py         # Strategy routing and evaluation
│   │   ├── simulator.py        # Universal backtesting simulator
│   │   └── trading_engine.py   # Portfolio ledger, execution, and risk gates
│   ├── main.py                 # CLI Backtest interface
│   ├── main_api.py             # FastAPI REST Server
│   └── walk_forward.py         # Walk-Forward rolling optimization engine
├── frontend/                   # React Vite dashboard with TradingView charts
└── README.md
```

---

## 🛠️ Installation & Getting Started

### Prerequisites
- Python 3.8+
- Node.js 16+

### 1. Backend Setup
Navigate to the root directory and install dependencies:
```bash
pip install pandas numpy yfinance fastapi uvicorn pydantic
```

Run a CLI backtest simulation:
```bash
# Run minute-level day trading simulation for TSLA
python backend/main.py --ticker TSLA --period 5d --interval 1m

# Run daily-level swing trading simulation for TSLA
python backend/main.py --ticker TSLA --period 1y --interval 1d
```

Run Walk-Forward rolling parameter optimization:
```bash
python backend/walk_forward.py --ticker TSLA --period 1y --interval 1d
```

Start the FastAPI API server:
```bash
python backend/main_api.py
```

### 2. Frontend Setup
Navigate to the frontend folder, install dependencies, and start the development server:
```bash
cd frontend
npm install
npm run dev
```

---

## 📊 Backtest Indicators & Performance
Our universal backtest simulator calculates standard trading metrics including:
- **Net PnL & Return Percentage**
- **Max Account Equity Drawdown**
- **Win Rate & Round Trip Trade Count**
- **Transaction Commission and Slippage Friction Cost**
- **Market Regime Distributions**

---

## 📝 License & Disclaimer
This software is provided for educational and research purposes only. Algorithmic trading carries substantial risk, and past performance is not indicative of future results.
