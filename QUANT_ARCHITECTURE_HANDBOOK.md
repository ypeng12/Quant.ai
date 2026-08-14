# 🏛️ Quant.ai — Institutional Quantitative Architecture Handbook (8 Pillars of Quant & AI)

> **Document Version**: 2.5.0  
> **Status**: Institutional Production Specification  
> **Target Audience**: Quantitative Researchers, ML Engineers, Algorithmic Traders & Portfolio Managers  

---

## 📌 Executive Summary

`Quant.ai` is a full-stack, low-latency institutional quantitative trading platform and machine learning framework. This handbook serves as the authoritative blueprint detailing the **8 Pillars of Modern Quantitative Finance & AI**, covering mathematical formulations, system architecture, feature engineering, backtest validation, optimal execution, and risk control.

```
                                  ┌──────────────────────────────────────────────────────────┐
                                  │          Quant.ai 8 Pillars Architecture Engine          │
                                  └───────────────────────────┬──────────────────────────────┘
                                                              │
     ┌──────────────────┬──────────────────┬──────────────────┼──────────────────┬──────────────────┬──────────────────┐
     ▼                  ▼                  ▼                  ▼                  ▼                  ▼                  ▼
┌─────────┐        ┌─────────┐        ┌─────────┐        ┌─────────┐        ┌─────────┐        ┌─────────┐        ┌─────────┐
│Pillar 1 │        │Pillar 2 │        │Pillar 3 │        │Pillar 4 │        │Pillar 5 │        │Pillar 6 │        │Pillar 7 │
│  Alpha  │        │   HFT   │        │ Optimal │        │Portfolio│        │  Stat   │        │ Options │        │Alt Data │
│ Mining  │        │ Micro-  │        │ Execution│        │ & Risk  │        │ Arbitrage│       │ Derivatives│      │Multimodal│
│ (GP/IC) │        │structure│        │ (Almgren)│        │  (HRP)  │        │ (Kalman)│        │ (PINNs) │        │ (LLM)   │
└─────────┘        └─────────┘        └─────────┘        └─────────┘        └─────────┘        └─────────┘        └─────────┘
     │                  │                  │                  │                  │                  │                  │
     └──────────────────┴──────────────────┴──────────────────┼──────────────────┴──────────────────┴──────────────────┘
                                                              ▼
                                                   ┌─────────────────────┐
                                                   │      Pillar 8       │
                                                   │ Anti-Overfitting DSR│
                                                   │  & Purged/Embargo CV│
                                                   └─────────────────────┘
```

---

## 🏛️ Pillar 1: Alpha Generation & Genetic Formulaic Mining

### 1.1 Mathematical Formulation
Formulaic Alpha mining uses **Genetic Programming (GP)** to explore the non-linear space of mathematical operators over price-volume time series $X_t \in \mathbb{R}^{T \times F}$. An expression tree $f(X)$ evaluates to an alpha vector $S_t = f(X_t)$.

Fitness is evaluated using **Rank Information Coefficient (Rank IC)** and **Information Ratio of IC (IC-IR)** against $k$-step forward returns $R_{t+k}$:

$$\text{Rank IC}_t = \rho_{\text{Spearman}}\left( S_t, R_{t+k} \right) = 1 - \frac{6 \sum_{i=1}^M d_{i,t}^2}{M(M^2 - 1)}$$

$$\text{IC-IR} = \frac{\mathbb{E}[\text{Rank IC}_t]}{\sigma(\text{Rank IC}_t)} \cdot \sqrt{252}$$

### 1.2 Expression Tree Primitives
| Operator Type | Primitive Functions | Definition / Mathematical Operation |
| :--- | :--- | :--- |
| **Arithmetic** | `add`, `sub`, `mul`, `div`, `abs`, `log`, `sqrt` | Element-wise algebraic transformations |
| **Time Series** | `ts_mom(x, d)`, `ts_std(x, d)`, `ts_rank(x, d)` | Rolling window statistics over lookback period $d$ |
| **Cross-Sectional**| `cs_rank(x)`, `cs_zscore(x)` | Normalize values across universe $\mathcal{U}_t$ at time $t$ |

### 1.3 Python API Integration (`symbolic_alpha_miner.py`)
```python
from backend.app.ml.symbolic_alpha_miner import SymbolicAlphaMiner

# Initialize genetic miner
miner = SymbolicAlphaMiner(population_size=200, generations=15, tournament_size=10)

# Fit on historical feature DataFrame
best_formula = miner.fit(df_market_data, target_col="future_ret_5d")
print("Mined Alpha Formula:", best_formula.expression)
print("Rank IC:", best_formula.rank_ic, "IC-IR:", best_formula.ic_ir)
```

---

## ⚡ Pillar 2: HFT & Market Microstructure (LOB & OFI)

### 2.1 Order Flow Imbalance ($\text{OFI}$)
The Limit Order Book (LOB) at Level-1 records best bid $P_t^b$, bid volume $V_t^b$, best ask $P_t^a$, and ask volume $V_t^a$. Order Flow Imbalance ($\text{OFI}$) measures net aggressor order flow:

$$\text{OFI}_t = L_t^b - L_t^a$$

$$L_t^b = \begin{cases} V_t^b & \text{if } P_t^b > P_{t-1}^b \\ V_t^b - V_{t-1}^b & \text{if } P_t^b = P_{t-1}^b \\ 0 & \text{if } P_t^b < P_{t-1}^b \end{cases}, \quad L_t^a = \begin{cases} 0 & \text{if } P_t^a > P_{t-1}^a \\ V_t^a - V_{t-1}^a & \text{if } P_t^a = P_{t-1}^a \\ V_t^a & \text{if } P_t^a < P_{t-1}^a \end{cases}$$

Cont et al. (2014) proved that price change $\Delta P_t = P_t - P_{t-1}$ is linearly proportional to $\text{OFI}_t$:

$$\Delta P_t = \frac{1}{D_t} \cdot \text{OFI}_t + \epsilon_t$$

Where $D_t$ represents market depth (liquidity density).

---

## 🎯 Pillar 3: Algorithmic Execution & Almgren-Chriss Framework

### 3.1 Mean-Variance Liquidation Formulation
An institutional investor needs to liquidate $X_0$ shares over time $T$ divided into $N$ intervals $\tau = T/N$. The trading trajectory is $x_0, x_1, \dots, x_N = 0$, with trade sizes $v_k = x_{k-1} - x_k$.

The asset price follows a stochastic process with volatility $\sigma$, permanent market impact $\gamma$, and temporary market impact $\eta$:

$$S_k = S_{k-1} - \gamma v_k \tau + \sigma \sqrt{\tau} \xi_k$$

$$\tilde{S}_k = S_k - \eta \left( \frac{v_k}{\tau} \right)$$

Total cost $x = \sum_{k=1}^N v_k (S_0 - \tilde{S}_k)$ has expected value $E[x]$ and variance $V[x]$:

$$E[x] = \frac{1}{2} \gamma X_0^2 + \frac{\eta}{\tau} \sum_{k=1}^N v_k^2$$

$$V[x] = \sigma^2 \sum_{k=1}^N \tau x_k^2$$

### 3.2 Closed-Form Optimal Execution Schedule
Minimizing utility $U(x) = E[x] + \lambda V[x]$ (where $\lambda$ is risk aversion):

$$x_k = \frac{\sinh\left( \kappa (T - t_k) \right)}{\sinh(\kappa T)} X_0, \quad \kappa \approx \sqrt{\frac{\lambda \sigma^2}{\eta}}$$

```python
from backend.app.ml.almgren_chriss_execution import AlmgrenChrissExecutionEngine

engine = AlmgrenChrissExecutionEngine(total_shares=100000, total_time_hours=1.0, num_steps=10)
schedule = engine.compute_optimal_trajectory(risk_aversion=1e-5, volatility=0.02, eta=1e-6, gamma=2.5e-7)
print("Optimal Trading Schedule (Shares Remaining):", schedule.trajectory)
```

---

## 🛡️ Pillar 4: Portfolio Optimization & Hierarchical Risk Parity (HRP)

### 4.1 Drawbacks of Markowitz Mean-Variance Optimization
Traditional Markowitz MVO requires calculating $\Sigma^{-1}$ (inverse covariance matrix). When assets are co-linear, $\Sigma$ is ill-conditioned, resulting in extreme, unstable asset allocation weights $w$.

### 4.2 López de Prado (2016) HRP Algorithm
HRP operates in 3 steps without requiring matrix inversion:

1. **Tree Clustering**: Distance matrix $d_{i,j} = \sqrt{\frac{1}{2}(1 - \rho_{i,j})}$. Hierarchical single-linkage clustering groups correlated assets.
2. **Quasi-Diagonalization**: Reorder rows and columns of correlation matrix so similar assets sit adjacent.
3. **Recursive Bisection**: Split assets into left/right clusters $C_L, C_R$. Allocate variance-proportional weights:
   
$$\alpha_1 = 1 - \frac{V_L}{V_L + V_R}, \quad V_L = w_L^T \Sigma_L w_L$$

```python
from backend.app.ml.hierarchical_risk_parity import HierarchicalRiskParityOptimizer

hrp = HierarchicalRiskParityOptimizer()
weights = hrp.fit_predict(returns_df)
print("HRP Optimal Weights:", weights)
```

---

## 📈 Pillar 5: Statistical Arbitrage & Cointegration

### 5.1 Johansen Cointegration & Kalman State-Space Filtering
For a pair of non-stationary price series $P_t^A, P_t^B \sim I(1)$, a linear combination $S_t = P_t^A - \beta_t P_t^B - \alpha_t$ is stationary $S_t \sim I(0)$.

The dynamic hedge ratio $\beta_t$ is estimated recursively using a **Kalman Filter**:

$$\beta_t = \beta_{t-1} + w_t, \quad w_t \sim \mathcal{N}(0, W)$$

$$P_t^A = \beta_t P_t^B + \alpha_t + v_t, \quad v_t \sim \mathcal{N}(0, V)$$

The spread $S_t$ is fitted to an **Ornstein-Uhlenbeck (OU) Mean-Reverting Process**:

$$dS_t = \theta (\mu - S_t) dt + \sigma dW_t$$

Where $\theta$ represents the half-life of mean-reversion $T_{1/2} = \frac{\ln(2)}{\theta}$.

---

## 📐 Pillar 6: Derivatives Pricing & Volatility Surface Modeling

### 6.1 Heston Stochastic Volatility Partial Differential Equation (PDE)
$$\frac{\partial V}{\partial t} + \frac{1}{2} S^2 v \frac{\partial^2 V}{\partial S^2} + \rho \sigma S v \frac{\partial^2 V}{\partial S \partial v} + \frac{1}{2} \sigma^2 v \frac{\partial^2 V}{\partial v^2} + r S \frac{\partial V}{\partial S} + \kappa(\theta - v) \frac{\partial V}{\partial v} - rV = 0$$

### 6.2 Physics-Informed Neural Networks (PINNs)
PINNs approximate option pricing function $V(S, v, t; \theta_{\text{NN}})$ by incorporating PDE residual into network loss:

$$\mathcal{L}_{\text{total}} = \mathcal{L}_{\text{data}} + \lambda_{\text{PDE}} \cdot \frac{1}{N} \sum_{i=1}^N \left| \mathcal{D}_{\text{Heston}}[V(S_i, v_i, t_i)] \right|^2$$

---

## 🌐 Pillar 7: Alternative Data & Multimodal ML

### 7.1 Earnings Call Transcript Sentiment Analysis
Natural language processing over corporate earnings calls using **FinBERT / LLaMA-3**:
* Extracts executive tone vs. analyst Q&A friction scores.
* Measures management hesitation ratio and non-answer probability.

### 7.2 Satellite & Credit Card Transaction Aggregation
* Satellite optical imagery processing for parking lot density.
* Consumer transaction flow modeling for real-time revenue prediction.

---

## 🔍 Pillar 8: Anti-Overfitting Financial ML Validation

### 8.1 Deflated Sharpe Ratio (DSR)
Bailey & López de Prado (2014) DSR adjusts observed Sharpe Ratio $\hat{\text{SR}}$ for selection bias across $N$ trial attempts, skewness $\gamma_3$, and kurtosis $\gamma_4$:

$$\text{DSR} = Z\left[ \frac{(\hat{\text{SR}} - \text{SR}^*) \sqrt{V-1}}{\sqrt{1 - \gamma_3 \hat{\text{SR}} + \frac{\gamma_4 - 1}{4} \hat{\text{SR}}^2}} \right]$$

$$\text{SR}^* = \sqrt{V} \left( (1 - \gamma) Z^{-1}\left(1 - \frac{1}{N}\right) + \gamma Z^{-1}\left(1 - \frac{1}{N \cdot e}\right) \right)$$

### 8.2 Purged & Embargoed Cross-Validation
* **Purging**: Removes training samples whose evaluation window overlaps with test labels.
* **Embargoing**: Applies a 1%–5% time buffer after test sets to eliminate autoregressive feature leakage.

```python
from backend.app.ml.deflated_sharpe_auditor import DeflatedSharpeAuditor

auditor = DeflatedSharpeAuditor(num_trials=50)
audit_result = auditor.audit_strategy(returns_series)
print("Is Strategy Statistically Valid?:", audit_result["is_statistically_significant"])
print("DSR Probability:", audit_result["dsr_probability"])
```

---

## 🛠️ Verification & Test Suite Matrix

All modules are accompanied by zero-dependency synthetic verification suites:

```bash
python3 backend/app/ml/symbolic_alpha_miner.py
python3 backend/app/ml/almgren_chriss_execution.py
python3 backend/app/ml/hierarchical_risk_parity.py
python3 backend/app/ml/deflated_sharpe_auditor.py
```

---

*© 2026 Quant.ai Platform. Published under MIT License.*
