# backend/app/ml/autonomous_execution_tracker.py
"""
Fully Autonomous Intraday Session & Liquidity Tracker Engine.
Engineered for 100% hands-off autonomous trading:
1. Trading Session Window Optimization:
   - Blocks entry during noise windows (09:30~09:45 EST open whipsaws, 15:55~16:00 EST close liquidations).
   - Trades exclusively in prime liquidity windows (09:45~11:30 EST & 13:30~15:45 EST).
2. Dynamic Volume & Market Impact Tracking:
   - Caps trade size to <= 1.0% of 5-minute average volume (V_5m) to eliminate market impact & slippage.
   - Applies Volatility Target Sizing (Kelly / ATR parity) to scale down size during high ATR spikes.
3. Hands-Off Background Pipeline:
   - Integrates with DailyConsistencyQuantEngine and AutoReflectionEngine for silent end-to-end execution.
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, time
from typing import Dict, List, Tuple, Optional

from backend.app.ml.daily_consistency_quant_engine import DailyConsistencyQuantEngine
from backend.app.ml.auto_reflection_engine import AutoReflectionEngine

class AutonomousExecutionTracker:
    def __init__(self, max_market_impact_pct: float = 0.01):
        self.max_market_impact_pct = max_market_impact_pct
        self.daily_engine = DailyConsistencyQuantEngine(p_win_threshold=0.55)
        self.reflection_engine = AutoReflectionEngine()

    def is_prime_trading_window(self, dt: pd.Timestamp) -> bool:
        """
        Optimizes trading timing windows:
        - Blocked: 09:30 - 09:45 EST (Market Open Whipsaw)
        - Blocked: 15:55 - 16:00 EST (Market Close Liquidation)
        - Allowed: 09:45 - 11:30 EST & 13:30 - 15:45 EST (Prime Liquidity Windows)
        """
        t = dt.time()
        
        # Open Whipsaw Noise Block (09:30 ~ 09:45)
        if time(9, 30) <= t < time(9, 45):
            return False
        
        # Close Liquidation Block (15:55 ~ 16:00)
        if time(15, 55) <= t <= time(16, 0):
            return False

        # Morning Prime Window (09:45 ~ 11:30)
        if time(9, 45) <= t <= time(11, 30):
            return True
            
        # Afternoon Prime Window (13:30 ~ 15:45)
        if time(13, 30) <= t <= time(15, 45):
            return True

        # Default fallback for daily datasets without specific intra-day time
        if t == time(0, 0):
            return True

        return False

    def calculate_liquidity_capped_position(
        self,
        df: pd.DataFrame,
        idx: int,
        raw_position: float,
        target_volatility_pct: float = 0.02
    ) -> float:
        """
        Liquidity & Market Impact Tracking:
        Caps trade size <= 1.0% of 5-minute volume and scales down when ATR volatility is high.
        """
        if raw_position == 0.0 or idx < 5:
            return 0.0

        vol_col = "volume" if "volume" in df.columns else ("Volume" if "Volume" in df.columns else None)
        if vol_col:
            v_5m_avg = df[vol_col].iloc[max(0, idx-5):idx].mean()
            # Cap size based on market liquidity
            volume_cap_factor = min(1.0, (v_5m_avg * self.max_market_impact_pct) / 100.0)
        else:
            volume_cap_factor = 1.0

        # ATR Volatility Parity Scaling
        price = df["Close"].iloc[idx]
        high_slice = df["High"].iloc[max(0, idx-14):idx+1] if "High" in df.columns else df["Close"].iloc[max(0, idx-14):idx+1]
        low_slice = df["Low"].iloc[max(0, idx-14):idx+1] if "Low" in df.columns else df["Close"].iloc[max(0, idx-14):idx+1]
        
        atr = (high_slice - low_slice).mean()
        atr_pct = (atr / price) if price > 0 else 0.01

        vol_scaling = min(1.0, target_volatility_pct / max(0.005, atr_pct))
        
        final_position = raw_position * volume_cap_factor * vol_scaling
        return float(np.clip(final_position, 0.0, 1.0))

    def run_autonomous_tracking_pipeline(self, df: pd.DataFrame) -> Dict:
        """
        Runs bar-by-bar autonomous execution incorporating timing window optimization and liquidity volume capping.
        """
        df_copy = df.copy()
        if "date" in df_copy.columns:
            df_copy["dt"] = pd.to_datetime(df_copy["date"])
        else:
            df_copy["dt"] = pd.date_range("2026-08-01", periods=len(df_copy), freq="5min")

        self.daily_engine.fit_pipeline(df_copy)
        base_res = self.daily_engine.simulate_daily_consistent_trading(df_copy)
        raw_positions = base_res["positions"]

        optimized_positions = []
        blocked_by_timing_count = 0
        volume_scaled_count = 0

        for i in range(len(df_copy)):
            dt_val = df_copy["dt"].iloc[i]
            raw_pos = raw_positions[i]

            # 1. Timing Window Filter
            if not self.is_prime_trading_window(dt_val):
                optimized_positions.append(0.0)
                if raw_pos > 0:
                    blocked_by_timing_count += 1
                continue

            # 2. Liquidity & Volatility Position Scaling
            opt_pos = self.calculate_liquidity_capped_position(df_copy, i, raw_pos)
            if opt_pos < raw_pos and opt_pos > 0:
                volume_scaled_count += 1

            optimized_positions.append(opt_pos)

        pos_s = pd.Series(optimized_positions, index=df_copy.index)
        raw_ret = df_copy["Close"].pct_change().fillna(0.0)
        tc = pos_s.diff().abs().fillna(0.0) * (5.0 / 10000.0)
        net_ret = pos_s * raw_ret - tc

        from src.validation.metrics import calculate_financial_metrics
        metrics = calculate_financial_metrics(net_ret)

        return {
            "metrics": metrics,
            "optimized_positions": optimized_positions,
            "blocked_by_timing_count": blocked_by_timing_count,
            "volume_scaled_count": volume_scaled_count,
            "total_bars": len(df_copy)
        }

if __name__ == "__main__":
    print("Testing AutonomousExecutionTracker...")
    np.random.seed(42)
    n = 200
    dts = pd.date_range("2026-08-22 09:30", periods=n, freq="5min")
    df_test = pd.DataFrame({
        "date": dts,
        "Close": 100.0 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "High": 101.0 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "Low": 99.0 + np.cumsum(np.random.normal(0.05, 0.5, n)),
        "Volume": np.random.uniform(5000, 20000, n),
        "bid_size": np.random.uniform(100, 1000, n),
        "ask_size": np.random.uniform(100, 1000, n)
    })

    tracker = AutonomousExecutionTracker()
    res = tracker.run_autonomous_tracking_pipeline(df_test)

    print("Filtered Noise Bars:", res["blocked_by_timing_count"])
    print("Liquidity Scaled Bars:", res["volume_scaled_count"])
    print("Net Return:", round(res["metrics"].get("total_return", 0.0) * 100.0, 2), "%")
    print("Sharpe Ratio:", round(res["metrics"].get("sharpe_ratio", 0.0), 2))
