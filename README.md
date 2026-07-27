---
title: Quant AI - Advanced Quant Trading Engine & Backtest Simulator
emoji: 📈
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Quant.ai - Point-in-Time Alpha Research & Execution Simulation Platform

<p align="center">
  <a href="https://huggingface.co/spaces/Ypeng12/quant-ai" target="_blank">
    <img src="https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Live%20Demo-FFD21E.svg?style=for-the-badge&logo=huggingface&logoColor=black" alt="Hugging Face Space" />
  </a>
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-v0.95%2B-009688.svg?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Pytest-Passed-green.svg?style=for-the-badge&logo=pytest&logoColor=white" alt="Pytest Passed" />
</p>

> 🚀 **Live Interactive Demo**: Try the deployed terminal live on Hugging Face Spaces 👉 **[huggingface.co/spaces/Ypeng12/quant-ai](https://huggingface.co/spaces/Ypeng12/quant-ai)**

Quant.ai is a **Point-in-Time Consistent U.S. Equity & ETF Cross-Sectional Alpha Research Platform** designed following Hudson River Trading (HRT) Algorithm Developer standards. It features zero-leak feature/label pipelines, Purged Walk-Forward Cross Validation with embargo, risk parity portfolio weighting, Implementation Shortfall friction modeling, and reproducible experiment manifests.

---

## 🎯 Core Research Question & Core Hypothesis

> **Can volatility-adjusted cross-sectional momentum signals across liquid U.S. ETFs predict short-term excess returns after transaction costs?**

### Key Methodological Pillars:
1. **Point-in-Time Data Hygiene**: Strict timestamp truncation at date $t$. Research adjusted total return prices for Alpha signals & raw OHLCV for execution simulation.
2. **Purged Walk-Forward CV + Embargo**: Eliminates label overlap leakage across rolling 3-year train / 6-month validation / 6-month out-of-sample test windows with a 5-day embargo.
3. **Advanced Risk-Adjusted Signals**:
   - **Sortino Momentum**: $\text{Return}_{20d} / \text{DownsideVol}_{20d}$
   - **Residual Momentum**: 60-day rolling OLS stripping `SPY` Beta: $R_i(\tau) = \alpha_i + \beta_i R_{\text{SPY}}(\tau) + \epsilon_i(\tau)$
   - **Robust Z-Score Normalization**: Cross-sectional Median/MAD standardization.
4. **Model Hierarchy**: Rule-based Baselines $\to$ Ridge Linear $\to$ LightGBM Regressor / Ranker $\to$ XGBoost.
5. **Implementation Shortfall (IS) Friction**: Realistic 5 bps baseline transaction cost with sensitivity checks at 2 bps, 10 bps, 15 bps.
6. **Deflated Sharpe Ratio (DSR)**: Stationary Bootstrap 95% Confidence Intervals & DSR correcting for multiple testing.

---

## 📁 Repository Structure

```text
c:\Users\pengy\OneDrive\Desktop\Quont\
├── src/
│   ├── data/
│   │   ├── manifest.py           # ExperimentManifest tracking git commit, random seed & dataset revision
│   │   ├── hf_loader.py          # Hugging Face 'thecharttruth/etf-data' parquet stream & local caching
│   │   └── point_in_time.py      # Point-in-Time universe filtering (price > $5, ADV20 > $50M, age >= 252d)
│   ├── features/
│   │   ├── momentum.py           # Risk-adjusted momentum, Sortino momentum & Robust Z-Score (Median/MAD)
│   │   └── residual_momentum.py  # 60d rolling regression stripping SPY Beta for pure Alpha residual mom
│   ├── labels/
│   │   └── excess_returns.py     # Zero-leak 1d/5d forward excess return labels starting strictly at t+1
│   ├── validation/
│   │   ├── purged_cv.py          # Purged Walk-Forward CV generator with 5d embargo
│   │   └── metrics.py            # Rank IC, IC IR, Stationary Bootstrap 95% CI, Deflated Sharpe (DSR), PSR
│   ├── models/
│   │   ├── baselines.py          # Raw Mom Baseline, Vol-Adj Mom Baseline, Ridge Regression, Logistic Classifier
│   │   └── tree_models.py        # LightGBM Regressor/Ranker & XGBoost with sklearn graceful fallbacks
│   ├── portfolio/
│   │   └── risk_parity.py        # Risk Parity Inverse Volatility weighting (max 20% cap) & Turnover calculation
│   ├── execution/
│   │   └── implementation_shortfall.py # Transaction Cost Model & Implementation Shortfall (IS) decomposition
│   ├── llm/
│   │   └── parser.py             # Typed Natural Language Hypothesis Parser -> Pydantic Schema
│   └── monitoring/
│       └── drift_monitor.py      # Population Stability Index (PSI) & KS-Test Feature Drift Audit
├── tests/
│   ├── test_no_future_leak.py    # Unit test asserting zero future leak in feature/label timestamps
│   └── test_purged_cv.py         # Unit test verifying purged walk-forward cross validation
├── run_experiment.py             # One-command executable for out-of-sample research experiments
└── Makefile                      # Command shortcuts (`make test`, `make oos`)
```

---

## ⚡ Quick Start & Reproduction

### 1. Run Unit Tests (Zero Future Leakage & Purged CV)
```bash
python -m pytest tests/ -v
```

### 2. Execute One-Command Out-of-Sample Experiment (`make oos`)
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
