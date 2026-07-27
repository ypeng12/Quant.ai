# Residual Momentum

- **Authors**: David Blitz, Joop Huij, & Martin Martens
- **Published**: *Journal of Empirical Finance*, Vol. 18, No. 3 (2011), pp. 506–521.
- **Local Path**: `papers/blitz_huij_martens_2011_residual_momentum.md`

---

## 1. Executive Summary

Standard price momentum strategies (buying past 12-month winners and shorting losers) suffer from severe crash risk during market regime turning points (e.g. 2003, 2009 momentum crashes). 

Blitz, Huij, and Martens demonstrate that conventional momentum is contaminated by market Beta and sector factor exposures. By estimating residual returns relative to asset pricing models (Fama-French 3-factor or 4-factor model):

$$R_{i,t} = \alpha_i + \beta_{i,M} R_{m,t} + \beta_{i,SMB} \text{SMB}_t + \beta_{i,HML} \text{HML}_t + \epsilon_{i,t}$$

and ranking equities on their volatility-standardized residual returns:

$$\text{Residual Momentum Signal}_i = \frac{\frac{1}{11} \sum_{\tau=t-12}^{t-2} \epsilon_{i,\tau}}{\sigma(\epsilon_{i})}$$

investors achieve double the Sharpe ratio of standard momentum, zero market crash exposure, and robust out-of-sample Alpha across U.S. equities and ETFs.

---

## 2. Python Implementation

```python
import numpy as np
import pandas as pd
import statsmodels.api as sm

def calculate_residual_momentum(asset_returns, market_returns, lookback=252):
    """
    Computes Residual Momentum signal for an asset.
    """
    df = pd.DataFrame({'asset': asset_returns, 'market': market_returns}).dropna()
    if len(df) < lookback:
        return 0.0
        
    df = df.iloc[-lookback:]
    Y = df['asset']
    X = sm.add_constant(df['market'])
    
    model = sm.OLS(Y, X).fit()
    residuals = model.resid
    
    res_mean = residuals.iloc[:-20].mean() # Skip last month to avoid short reversal
    res_std = residuals.iloc[:-20].std()
    
    if res_std == 0:
        return 0.0
        
    return res_mean / res_std
```
