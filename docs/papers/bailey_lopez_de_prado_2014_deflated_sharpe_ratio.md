# The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality

- **Authors**: David H. Bailey & Marcos López de Prado
- **Published**: *Journal of Portfolio Management*, Vol. 40, No. 5 (2014), pp. 94–107.
- **SSRN**: [https://ssrn.com/abstract=2460551](https://ssrn.com/abstract=2460551)
- **Local Path**: `papers/bailey_lopez_de_prado_2014_deflated_sharpe_ratio.md`

---

## 1. Executive Summary

Standard Sharpe Ratios assume that asset returns are normally distributed (zero skewness, kurtosis of 3) and that backtests evaluate a single, isolated strategy. In modern algorithmic trading, researchers test hundreds or thousands of parameter combinations ($N$ trials). 

Due to **Selection Bias under Multiple Testing**, the maximum observed Sharpe ratio grows with the number of trials even when return series are purely random noise. The Deflated Sharpe Ratio (DSR) computes the probability that an observed Sharpe ratio $\widehat{\text{SR}}$ is genuinely statistically significant after deflating for:
1. The total number of trials conducted ($N$).
2. Non-normality of returns (Skewness $\gamma_3$, Kurtosis $\gamma_4$).
3. The variance of Sharpe ratios across all trials ($\sigma_{SR}^2$).

---

## 2. Mathematical Formulation

### 2.1 The Expected Maximum Sharpe Ratio under Null Hypothesis
Given $N$ independent trials of random return series, the expected maximum Sharpe ratio $\text{SR}^*$ is approximated by:

$$\text{SR}^* = \sqrt{\sigma_{SR}^2} \left[ (1-\gamma) Z^{-1}\left(1 - \frac{1}{N}\right) + \gamma Z^{-1}\left(1 - \frac{1}{N e}\right) \right]$$

where $\gamma \approx 0.5772156649$ is the Euler-Mascheroni constant and $Z^{-1}$ is the inverse standard normal CDF.

### 2.2 The Deflated Sharpe Ratio Statistic
The DSR test statistic $Z_{\text{DSR}}$ is calculated as:

$$Z_{\text{DSR}} = \frac{(\widehat{\text{SR}} - \text{SR}^*) \sqrt{T-1}}{\sqrt{1 - \gamma_3 \widehat{\text{SR}} + \frac{\gamma_4 - 1}{4} \widehat{\text{SR}}^2}}$$

where $T$ is the number of return observations (sample length). The final DSR probability is:

$$\text{DSR} = \Phi(Z_{\text{DSR}})$$

A DSR value $\ge 0.95$ indicates that the strategy's Sharpe ratio is statistically significant at the 5% level after correcting for backtest overfitting.

---

## 3. Python Reference Implementation

```python
import numpy as np
import scipy.stats as ss

def deflated_sharpe_ratio(returns, num_trials=50, expected_sr=0.0):
    """
    Computes Deflated Sharpe Ratio (DSR) following Bailey & Lopez de Prado (2014).
    """
    returns = np.array(returns)
    t = len(returns)
    if t < 5:
        return {"dsr": 0.0, "significant": False}
        
    skew = float(ss.skew(returns))
    kurt = float(ss.kurtosis(returns, fisher=False))
    
    mean_ret = np.mean(returns)
    std_ret = np.std(returns, ddof=1)
    if std_ret == 0:
        return {"dsr": 0.0, "significant": False}
        
    sr_hat = mean_ret / std_ret * np.sqrt(252)
    
    # Euler-Mascheroni constant
    euler = 0.5772156649
    sr_star = (1 - euler) * ss.norm.ppf(1 - 1.0/num_trials) + euler * ss.norm.ppf(1 - 1.0/(num_trials * np.e))
    
    denom = np.sqrt(1 - skew * sr_hat + ((kurt - 1) / 4.0) * (sr_hat ** 2))
    if denom == 0:
        denom = 1e-6
        
    z_stat = (sr_hat - sr_star) * np.sqrt(t - 1) / denom
    dsr_pvalue = float(ss.norm.cdf(z_stat))
    
    return {
        "observed_sharpe": float(np.round(sr_hat, 4)),
        "deflated_threshold_sr_star": float(np.round(sr_star, 4)),
        "dsr_probability": float(np.round(dsr_pvalue, 4)),
        "significant": bool(dsr_pvalue >= 0.95)
    }
```
