# The Price Impact of Order Book Events (Order Flow Imbalance - OFI)

- **Authors**: Rama Cont, Arseniy Kukanov, & Sasha Stoikov
- **Published**: *Journal of Financial Econometrics*, Vol. 12, No. 1 (2014), pp. 47–88.
- **Local Path**: `papers/cont_kukanov_stoikov_2014_order_flow_imbalance.md`

---

## 1. Executive Summary

This paper establishes the exact mathematical relationship between Limit Order Book (LOB) microstructural events and short-term price changes. 

Prior research relied primarily on volume or trade counts. Cont, Kukanov, and Stoikov show that price changes are driven by **Order Flow Imbalance (OFI)**, which tracks net supply-demand shifts across all three primary LOB events at the best bid and ask:
1. New Limit Orders (additions to depth).
2. Market Orders (trades consuming depth).
3. Order Cancellations (removals from depth).

OFI exhibits a strong, linear correlation with short-term price impact, where the slope coefficient is inversely proportional to depth at the top of the order book.

---

## 2. Mathematical Definition of OFI

Let $P_t^b, v_t^b$ be the Best Bid price and quantity at time $t$, and $P_t^a, v_t^a$ be the Best Ask price and quantity at time $t$.

### 2.1 Net Bid Flow $e_t^b$
$$e_t^b = \begin{cases} 
v_t^b & \text{if } P_t^b > P_{t-1}^b \\
v_t^b - v_{t-1}^b & \text{if } P_t^b = P_{t-1}^b \\
-v_{t-1}^b & \text{if } P_t^b < P_{t-1}^b
\end{cases}$$

### 2.2 Net Ask Flow $e_t^a$
$$e_t^a = \begin{cases} 
-v_t^a & \text{if } P_t^a > P_{t-1}^a \\
v_t^a - v_{t-1}^a & \text{if } P_t^a = P_{t-1}^a \\
v_{t-1}^a & \text{if } P_t^a < P_{t-1}^a
\end{cases}$$

### 2.3 Order Flow Imbalance (OFI)
$$\text{OFI}_t = e_t^b - e_t^a$$

### 2.4 Linear Price Impact Regression
$$\Delta P_t = \beta \cdot \text{OFI}_t + \epsilon_t$$

where $\beta = \frac{1}{D_t}$ is the inverse of market depth (price impact coefficient).

---

## 3. Python Reference Implementation

```python
import pandas as pd
import numpy as np

def calculate_ofi(df):
    """
    Computes Order Flow Imbalance (OFI) from LOB Best Bid/Ask snapshots.
    df must contain columns: ['bid_price', 'bid_qty', 'ask_price', 'ask_qty']
    """
    df = df.copy()
    
    # Prev prices & quantities
    prev_bid_p = df['bid_price'].shift(1)
    prev_bid_q = df['bid_qty'].shift(1)
    prev_ask_p = df['ask_price'].shift(1)
    prev_ask_q = df['ask_qty'].shift(1)
    
    # Net Bid Flow e_b
    e_b = np.where(df['bid_price'] > prev_bid_p, df['bid_qty'],
          np.where(df['bid_price'] == prev_bid_p, df['bid_qty'] - prev_bid_q, -prev_bid_q))
          
    # Net Ask Flow e_a
    e_a = np.where(df['ask_price'] > prev_ask_p, -df['ask_qty'],
          np.where(df['ask_price'] == prev_ask_p, df['ask_qty'] - prev_ask_q, prev_ask_q))
          
    df['e_b'] = e_b
    df['e_a'] = e_a
    df['OFI'] = df['e_b'] - df['e_a']
    
    # Normalize by Average Depth
    df['Avg_Depth'] = (df['bid_qty'] + df['ask_qty']) / 2.0
    df['Norm_OFI'] = df['OFI'] / np.maximum(df['Avg_Depth'], 1.0)
    
    return df
```
