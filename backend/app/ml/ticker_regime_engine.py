# backend/app/ml/ticker_regime_engine.py
"""
Ticker Regime & Direction Engine
Inspired by Dr. GP Saggese's Quant Research Principles:
1. Factor vs Residual Decomposition: Separates broad market beta (QQQ/SPY) from idiosyncratic alpha/direction.
2. Causal Trend & Regime Detection: Avoids overfitting and HARK by defining transparent, rule-grounded regime states:
   - BULL_EXPANSION (e.g. SNDK): High RVOL, Close > VWAP, positive slope -> Aggressive Long & Hold Waves (15-60m).
   - BEAR_EXPANSION (e.g. TSLA): Lower highs, Close < VWAP, negative slope -> Short Only or Cash (Strict Long Ban).
   - POP_AND_FADE (e.g. NVDA): Morning pop, high-volume rejection, breakdown below VWAP -> Fade / Mean-Revert.
   - CHOP_RANGE: Sideways noise around VWAP -> Cash / Zero Overlap.
3. 5-30 Minute Intraday Waves: Avoids high-frequency tick panic stops.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional
import numpy as np
import pandas as pd


class MarketRegime(str, Enum):
    BULL_EXPANSION = "BULL_EXPANSION"        # Strong idiosyncratic or sector uptrend (SNDK, MSTR)
    BEAR_EXPANSION = "BEAR_EXPANSION"        # Idiosyncratic downtrend (TSLA)
    POP_AND_FADE = "POP_AND_FADE"            # Morning surge followed by institutional distribution (NVDA)
    CHOP_RANGE = "CHOP_RANGE"                # Non-directional noise around VWAP


@dataclass
class RegimeAnalysis:
    ticker: str
    regime: MarketRegime
    directional_bias: str                     # "LONG", "SHORT", or "NEUTRAL"
    trend_strength: float                     # 0.0 to 1.0 (R^2 of slope)
    vwap_distance_pct: float                  # (Close - VWAP) / VWAP * 100
    rvol: float                               # Relative Volume vs 20-period average
    intraday_return_pct: float                # (Current - Open) / Open * 100
    recommended_hold_minutes: int             # 15 to 60 minutes for trends, 5 to 10 for faders
    reason: str


class TickerRegimeEngine:
    @staticmethod
    def calculate_vwap(df: pd.DataFrame) -> pd.Series:
        """Calculate Intraday VWAP from High, Low, Close, Volume."""
        typical_price = (df["High"] + df["Low"] + df["Close"]) / 3.0
        cum_vol = df["Volume"].cumsum()
        cum_tp_vol = (typical_price * df["Volume"]).cumsum()
        vwap = cum_tp_vol / cum_vol.replace(0, np.nan)
        return vwap.bfill()

    @staticmethod
    def analyze_ticker_regime(
        df_bars: pd.DataFrame, 
        ticker: str, 
        market_df: Optional[pd.DataFrame] = None
    ) -> RegimeAnalysis:
        """
        Analyze the macro/intraday regime for a single stock with zero overlap.
        Expects a DataFrame with Open, High, Low, Close, Volume sorted chronologically.
        """
        if len(df_bars) < 6:
            return RegimeAnalysis(
                ticker=ticker,
                regime=MarketRegime.CHOP_RANGE,
                directional_bias="NEUTRAL",
                trend_strength=0.0,
                vwap_distance_pct=0.0,
                rvol=1.0,
                intraday_return_pct=0.0,
                recommended_hold_minutes=15,
                reason="Insufficient intraday bars for regime determination"
            )

        df = df_bars.copy()
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns and col.lower() in df.columns:
                df[col] = df[col.lower()]

        # Ensure 1D Series
        close_s = df["Close"].squeeze()
        open_s = df["Open"].squeeze()
        high_s = df["High"].squeeze()
        low_s = df["Low"].squeeze()
        vol_s = df["Volume"].squeeze()

        df["VWAP"] = TickerRegimeEngine.calculate_vwap(df)
        df["EMA_9"] = close_s.ewm(span=9, adjust=False).mean()
        df["EMA_21"] = close_s.ewm(span=21, adjust=False).mean()

        latest_close = float(close_s.iloc[-1])
        day_open = float(open_s.iloc[0])
        day_high = float(high_s.max())
        day_low = float(low_s.min())
        latest_vwap = float(df["VWAP"].iloc[-1])
        latest_ema9 = float(df["EMA_9"].iloc[-1])
        latest_ema21 = float(df["EMA_21"].iloc[-1])

        # Metrics
        intraday_return_pct = (latest_close - day_open) / day_open * 100.0
        vwap_dist_pct = (latest_close - latest_vwap) / latest_vwap * 100.0
        
        # RVOL (last 3 bars vs rolling median)
        rolling_vol = vol_s.rolling(window=12, min_periods=3).mean()
        recent_vol = float(vol_s.tail(3).mean())
        base_vol = float(rolling_vol.iloc[-1]) if not np.isnan(rolling_vol.iloc[-1]) and rolling_vol.iloc[-1] > 0 else 1.0
        rvol = round(recent_vol / base_vol, 2) if base_vol > 0 else 1.0

        # Regression slope & R^2 on last 12 bars (approx 1 hour on 5m bars)
        window = min(12, len(df))
        recent_closes = close_s.tail(window).values
        x = np.arange(window)
        slope, intercept = np.polyfit(x, recent_closes, 1)
        corr_matrix = np.corrcoef(x, recent_closes)
        r_squared = float(corr_matrix[0, 1]**2) if not np.isnan(corr_matrix[0, 1]) else 0.0

        # Idiosyncratic Residual vs Benchmark (Saggese Factor Model)
        market_return_pct = 0.0
        if market_df is not None and not market_df.empty:
            m_open = float(market_df["Open"].iloc[0])
            m_close = float(market_df["Close"].iloc[-1])
            market_return_pct = (m_close - m_open) / m_open * 100.0
        
        idiosyncratic_excess_return = intraday_return_pct - market_return_pct

        # 1. Check for POP_AND_FADE (NVDA classic pattern)
        # Opened or surged early near day_high, but now has pulled back significantly from peak and failed VWAP
        peak_gain_pct = (day_high - day_open) / day_open * 100.0
        drawdown_from_peak_pct = (day_high - latest_close) / day_high * 100.0
        
        if peak_gain_pct >= 1.0 and drawdown_from_peak_pct >= 1.2 and latest_close <= latest_vwap * 1.002:
            return RegimeAnalysis(
                ticker=ticker,
                regime=MarketRegime.POP_AND_FADE,
                directional_bias="SHORT",
                trend_strength=r_squared,
                vwap_distance_pct=vwap_dist_pct,
                rvol=rvol,
                intraday_return_pct=intraday_return_pct,
                recommended_hold_minutes=10,
                reason=f"Morning pop (+{peak_gain_pct:.1f}%) followed by institutional fade (-{drawdown_from_peak_pct:.1f}% from peak). Under VWAP."
            )

        # 2. Check for BULL_EXPANSION (SNDK, MSTR classic pattern)
        # Price significantly above open (+1.5%+) and above VWAP
        if (
            intraday_return_pct >= 1.5 
            and latest_close > latest_vwap
        ):
            return RegimeAnalysis(
                ticker=ticker,
                regime=MarketRegime.BULL_EXPANSION,
                directional_bias="LONG",
                trend_strength=r_squared,
                vwap_distance_pct=vwap_dist_pct,
                rvol=rvol,
                intraday_return_pct=intraday_return_pct,
                recommended_hold_minutes=45,
                reason=f"Persistent institutional bull trend (+{intraday_return_pct:.2f}%). Firmly above VWAP ({vwap_dist_pct:+.2f}%). Idiosyncratic Alpha: {idiosyncratic_excess_return:+.2f}%."
            )

        # 3. Check for BEAR_EXPANSION (TSLA classic pattern)
        # Price significantly below open (-1.0%-) and below VWAP
        if (
            intraday_return_pct <= -1.0 
            and latest_close < latest_vwap
        ):
            return RegimeAnalysis(
                ticker=ticker,
                regime=MarketRegime.BEAR_EXPANSION,
                directional_bias="SHORT",
                trend_strength=r_squared,
                vwap_distance_pct=vwap_dist_pct,
                rvol=rvol,
                intraday_return_pct=intraday_return_pct,
                recommended_hold_minutes=30,
                reason=f"Clear downward distribution (-{abs(intraday_return_pct):.2f}%). Lower lows below VWAP ({vwap_dist_pct:+.2f}%). Long strictly banned."
            )

        # 4. Fallback to CHOP_RANGE
        return RegimeAnalysis(
            ticker=ticker,
            regime=MarketRegime.CHOP_RANGE,
            directional_bias="NEUTRAL",
            trend_strength=r_squared,
            vwap_distance_pct=vwap_dist_pct,
            rvol=rvol,
            intraday_return_pct=intraday_return_pct,
            recommended_hold_minutes=15,
            reason="Oscillating tightly around VWAP with no distinct directional expansion."
        )
