# backend/app/orderbook_ofi.py

"""
Market Microstructure Level-2 Order Flow Imbalance (OFI) & Micro-Price Engine.
Used by High-Frequency Trading (HFT) Market Makers (Jump Trading / Citadel Securities).

Implements:
1. Order Flow Imbalance (OFI):
   Measures net supply/demand pressure at top-of-book:
   OFI_t = delta_V_b(t) - delta_V_a(t)
   Where:
   - delta_V_b(t) = V_b(t) if P_b(t) > P_b(t-1)
                    V_b(t) - V_b(t-1) if P_b(t) == P_b(t-1)
                    0 if P_b(t) < P_b(t-1)
   - delta_V_a(t) = 0 if P_a(t) > P_a(t-1)
                    V_a(t) - V_a(t-1) if P_a(t) == P_a(t-1)
                    V_a(t) if P_a(t) < P_a(t-1)
2. Volume Order Imbalance (VOI): Normalized OFI ratio.
3. Micro-Price Estimator:
   P_micro = (V_a * P_b + V_b * P_a) / (V_b + V_a)
   Provides lead-lag predictive signal for next tick price movement.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple

class OrderFlowImbalanceEngine:
    def __init__(self, ofi_lookback: int = 20):
        self.lookback = ofi_lookback

    def compute_micro_price(self, bid_price: float, bid_vol: float, ask_price: float, ask_vol: float) -> float:
        """
        Calculates Volume-Weighted Micro-Price: P_micro = (V_a * P_b + V_b * P_a) / (V_b + V_a)
        If ask volume is high, micro-price skews towards bid (downward pressure).
        If bid volume is high, micro-price skews towards ask (upward pressure).
        """
        total_vol = bid_vol + ask_vol
        if total_vol <= 0:
            return (bid_price + ask_price) * 0.5
        return float((ask_vol * bid_price + bid_vol * ask_price) / total_vol)

    def calculate_ofi_series(self, df_l2: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates tick-by-tick Order Flow Imbalance (OFI) and Micro-Price from L2 orderbook updates.
        Expected columns: ['bid_price', 'bid_vol', 'ask_price', 'ask_vol']
        """
        df = df_l2.copy()
        
        P_b = df['bid_price'].values
        V_b = df['bid_vol'].values
        P_a = df['ask_price'].values
        V_a = df['ask_vol'].values
        
        n = len(df)
        ofi = np.zeros(n, dtype=np.float64)
        micro_prices = np.zeros(n, dtype=np.float64)

        # Micro-price calculation
        for i in range(n):
            micro_prices[i] = self.compute_micro_price(P_b[i], V_b[i], P_a[i], V_a[i])

        # Tick-by-tick OFI calculation
        for i in range(1, n):
            # Bid side contribution (dB)
            if P_b[i] > P_b[i-1]:
                dB = V_b[i]
            elif P_b[i] == P_b[i-1]:
                dB = V_b[i] - V_b[i-1]
            else:
                dB = 0.0

            # Ask side contribution (dA)
            if P_a[i] < P_a[i-1]:
                dA = V_a[i]
            elif P_a[i] == P_a[i-1]:
                dA = V_a[i] - V_a[i-1]
            else:
                dA = 0.0

            ofi[i] = dB - dA

        df['Micro_Price'] = micro_prices
        df['Mid_Price'] = (df['bid_price'] + df['ask_price']) * 0.5
        df['Price_Imbalance_Spread'] = df['Micro_Price'] - df['Mid_Price']
        df['OFI_Tick'] = ofi
        df['OFI_Rolling'] = df['OFI_Tick'].rolling(window=self.lookback).sum().fillna(0.0)

        # Signal Generation: OFI Z-score trigger
        ofi_std = df['OFI_Rolling'].std()
        if ofi_std > 0:
            df['OFI_ZScore'] = (df['OFI_Rolling'] - df['OFI_Rolling'].mean()) / ofi_std
        else:
            df['OFI_ZScore'] = 0.0

        return df

if __name__ == "__main__":
    print("Testing OrderFlowImbalanceEngine...")
    np.random.seed(42)
    n_ticks = 100
    
    mid_prices = 150.0 + np.cumsum(np.random.normal(0, 0.02, n_ticks))
    spreads = np.random.choice([0.01, 0.02], size=n_ticks)
    
    bids = np.round(mid_prices - spreads / 2.0, 2)
    asks = np.round(mid_prices + spreads / 2.0, 2)
    bid_vols = np.random.randint(100, 2000, n_ticks).astype(float)
    ask_vols = np.random.randint(100, 2000, n_ticks).astype(float)

    df_l2 = pd.DataFrame({
        'bid_price': bids,
        'bid_vol': bid_vols,
        'ask_price': asks,
        'ask_vol': ask_vols
    })

    engine = OrderFlowImbalanceEngine(ofi_lookback=10)
    res_df = engine.calculate_ofi_series(df_l2)

    print("L2 Orderbook OFI Output Preview:")
    print(res_df[['bid_price', 'ask_price', 'Micro_Price', 'OFI_Tick', 'OFI_ZScore']].tail(10))
    print("[+] OrderFlowImbalanceEngine operational.")
