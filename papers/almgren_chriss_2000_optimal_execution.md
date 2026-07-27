# Optimal Execution of Portfolio Transactions (Almgren-Chriss Model)

- **Authors**: Robert Almgren & Neil Chriss
- **Published**: *Journal of Risk*, Vol. 3, No. 2 (2000/2001), pp. 5–39.
- **Local Path**: `papers/almgren_chriss_2000_optimal_execution.md`

---

## 1. Executive Summary

Executing a large block order in equity markets faces a fundamental trade-off:
- **Trading Too Fast**: Consumes order book liquidity, causing severe **Temporary Market Impact** costs.
- **Trading Too Slow**: Leaves the unexecuted shares exposed to market volatility risk (**Implementation Shortfall Risk**).

The Almgren-Chriss framework solves this optimal control problem by formulating a Mean-Variance utility function over total execution costs and deriving the analytical optimal trading schedule $x_j$ (number of shares remaining at time $t_j$).

---

## 2. Mathematical Model & Solution

### 2.1 Temporary & Permanent Market Impact Functions
- **Permanent Impact**: $g(v) = \gamma v$ (linearly shifts equilibrium price $P_t$).
- **Temporary Impact**: $h(v) = \eta v$ (price premium paid per share traded at rate $v = \frac{X_j - X_{j+1}}{\tau}$).

### 2.2 Mean-Variance Objective Function
$$\min_{x_0, x_1, \dots, x_N} E[x] + \lambda V[x]$$

where $E[x]$ is the expected cost, $V[x]$ is the variance of execution cost, and $\lambda$ is trader risk aversion.

### 2.3 Optimal Execution Trajectory
The analytical solution for remaining shares $x_j$ at step $j$ is given by:

$$x_j = \frac{\sinh(\kappa (T - t_j))}{\sinh(\kappa T)} X_0$$

where $\kappa$ is the risk-urgency parameter:

$$\kappa \approx \sqrt{\frac{\lambda \sigma^2}{\eta}}$$

---

## 3. Python Implementation

```python
import numpy as np

def almgren_chriss_trajectory(total_shares, num_steps, risk_aversion=1e-5, volatility=0.02, eta=1e-6):
    """
    Computes Almgren-Chriss optimal liquidation schedule.
    """
    x = np.zeros(num_steps + 1)
    x[0] = total_shares
    
    # Calculate urgency parameter kappa
    kappa = np.sqrt((risk_aversion * (volatility ** 2)) / eta)
    T = float(num_steps)
    
    for j in range(1, num_steps + 1):
        t_j = float(j)
        x[j] = total_shares * (np.sinh(kappa * (T - t_j)) / np.sinh(kappa * T))
        
    trades = np.diff(x) * -1 # Shares to sell per step
    return {
        "trajectory": x,
        "step_trades": trades,
        "kappa": kappa
    }
```
