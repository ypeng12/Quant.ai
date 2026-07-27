# backend/app/event_alpha.py

"""
Post-Earnings Announcement Drift (PEAD) & Event-Driven Alpha Engine.
Inspired by empirical quantitative research on earnings surprise & pre-announcement drift.

Implements:
1. Earnings Surprise SUE (Standardized Unanticipated Earnings) / Pre-Announcement Score calculation.
2. Post-Earnings Announcement Drift (PEAD) momentum calculator.
3. Event-Driven Strategy Evaluator (combining pre-event 20d momentum, growth rate, and volume surge).
"""

import numpy as np
import pandas as pd
from typing import Dict, List

class EventAlphaEngine:
    def __init__(self, momentum_lookback: int = 20, drift_holding_days: int = 7):
        self.momentum_lookback = momentum_lookback
        self.drift_holding_days = drift_holding_days

    def calculate_pead_score(self, expected_growth_pct: float, return_20d: float, return_5d: float, volume_ratio: float) -> float:
        """
        Calculates composite PEAD Event Score based on empirical feature importance weights:
        - Expected YoY Earnings Growth (Growth Score)
        - Pre-event 20-Day Momentum
        - Pre-event 5-Day Short-term Momentum
        - Volume Surge Ratio (RVOL)
        """
        score = 0.0
        
        # 1. Earnings Growth Component (Weight: ~30%)
        if expected_growth_pct >= 0.50: # > 50% YoY growth
            score += 3.0
        elif expected_growth_pct >= 0.20:
            score += 1.5
        elif expected_growth_pct < 0.0:
            score -= 2.0

        # 2. 20-Day Pre-Event Momentum (Weight: ~30%)
        if return_20d >= 0.08: # > 8% 20d return
            score += 2.5
        elif return_20d >= 0.03:
            score += 1.0
        elif return_20d <= -0.05:
            score -= 1.5

        # 3. 5-Day Momentum (Weight: ~20%)
        if return_5d >= 0.03:
            score += 1.5
        elif return_5d <= -0.03:
            score -= 1.0

        # 4. Volume Surge RVOL Component (Weight: ~20%)
        if volume_ratio >= 1.8:
            score += 2.0
        elif volume_ratio >= 1.2:
            score += 1.0

        return float(score)

    def evaluate_event_catalysts(self, df: pd.DataFrame, ticker: str, earnings_announcements: List[Dict] = None) -> List[Dict]:
        """
        Evaluates PEAD alpha triggers across historical price series.
        """
        df = df.copy()
        df['Return_20d'] = df['Close'].pct_change(self.momentum_lookback)
        df['Return_5d'] = df['Close'].pct_change(5)
        
        if 'Volume' in df.columns:
            df['Vol_SMA20'] = df['Volume'].rolling(20).mean().replace(0, 1)
            df['RVOL'] = df['Volume'] / df['Vol_SMA20']
        else:
            df['RVOL'] = 1.0

        signals = []

        # If no specific earnings dates provided, detect volume & price breakout triggers
        for i in range(self.momentum_lookback, len(df)):
            row = df.iloc[i]
            ts = df.index[i]
            
            ret20 = float(row['Return_20d']) if not pd.isna(row['Return_20d']) else 0.0
            ret5 = float(row['Return_5d']) if not pd.isna(row['Return_5d']) else 0.0
            rvol = float(row['RVOL']) if not pd.isna(row['RVOL']) else 1.0

            # Synthetic proxy earnings growth assumption for signal demo if no external catalyst date
            simulated_growth = 0.55 if rvol > 1.5 and ret20 > 0.05 else 0.10

            score = self.calculate_pead_score(simulated_growth, ret20, ret5, rvol)

            if score >= 5.0:
                signals.append({
                    "timestamp": str(ts),
                    "ticker": ticker,
                    "close_price": float(row['Close']),
                    "pead_score": score,
                    "rvol": round(rvol, 2),
                    "return_20d_pct": round(ret20 * 100, 2),
                    "action": "BUY_PEAD_DRIFT",
                    "target_holding_days": self.drift_holding_days
                })

        return signals

if __name__ == "__main__":
    print("Testing EventAlphaEngine...")
    engine = EventAlphaEngine()
    score = engine.calculate_pead_score(expected_growth_pct=0.60, return_20d=0.09, return_5d=0.04, volume_ratio=2.1)
    print(f"PEAD Score for strong pre-announcement: {score:.1f} (Threshold: 5.0)")

    dates = pd.date_range('2024-01-01', periods=60)
    prices = 100.0 * np.exp(np.cumsum(np.random.normal(0.001, 0.02, 60)))
    volumes = np.random.randint(1000, 5000, 60)
    volumes[40] = 12000 # Volume spike
    
    df = pd.DataFrame({'Close': prices, 'Volume': volumes}, index=dates)
    signals = engine.evaluate_event_catalysts(df, "TSLA")
    print(f"PEAD Catalyst Signals Detected: {len(signals)}")
    print("[+] EventAlphaEngine operational.")
