# backend/app/stat_arb.py

"""
Statistical Arbitrage & Cointegration Engine.
Implements:
1. Engle-Granger 2-Step Cointegration Test & Hedge Ratio (Beta) estimation.
2. Ornstein-Uhlenbeck (OU) Mean Reversion Process Parameter Estimation:
   dS_t = theta * (mu - S_t) * dt + sigma_ou * dW_t
   - Mean reversion speed (theta)
   - Long-term equilibrium mean (mu)
   - Half-life of mean reversion: t_half = ln(2) / theta
3. Dynamic Spread & Rolling Z-Score calculation.
4. Pairs Trading Backtesting Engine (Long Spread / Short Spread on Z-Score thresholds).
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, List

class StatArbEngine:
    def __init__(self, z_entry_threshold: float = 2.0, z_exit_threshold: float = 0.5):
        self.z_entry = z_entry_threshold
        self.z_exit = z_exit_threshold

    def calculate_hedge_ratio(self, series_y: pd.Series, series_x: pd.Series) -> Tuple[float, float, pd.Series]:
        """
        Engle-Granger Step 1: OLS Regression Y = alpha + beta * X + epsilon
        Returns:
            alpha: float (intercept)
            beta: float (hedge ratio)
            spread: pd.Series (residuals / spread = Y - beta * X - alpha)
        """
        X = np.column_stack([np.ones(len(series_x)), series_x.values])
        Y = series_y.values

        # OLS estimation: (X^T X)^(-1) X^T Y
        params = np.linalg.lstsq(X, Y, rcond=None)[0]
        alpha, beta = params[0], params[1]

        spread = series_y - (alpha + beta * series_x)
        return float(alpha), float(beta), spread

    def fit_ornstein_uhlenbeck(self, spread: pd.Series, dt: float = 1.0) -> Dict[str, float]:
        """
        Fits an Ornstein-Uhlenbeck (OU) continuous-time mean-reversion process:
        dS_t = theta * (mu - S_t) * dt + sigma * dW_t
        
        Discrete AR(1) representation:
        S_t = a + b * S_{t-1} + e_t
        Where:
        - b = exp(-theta * dt) => theta = -ln(b) / dt
        - a = mu * (1 - b)     => mu = a / (1 - b)
        - Var(e_t) = sigma^2 * (1 - exp(-2*theta*dt)) / (2*theta)
        
        Returns:
            theta: mean reversion speed
            mu: long-term mean
            sigma_ou: process volatility
            half_life: mean-reversion half-life (in bars/days)
        """
        S = spread.values
        S_curr = S[1:]
        S_prev = S[:-1]

        # Fit AR(1) OLS: S_t = a + b * S_{t-1}
        X = np.column_stack([np.ones(len(S_prev)), S_prev])
        params = np.linalg.lstsq(X, S_curr, rcond=None)[0]
        a, b = params[0], params[1]

        # Guard against non-stationary / non-mean-reverting series (b >= 1.0)
        if b >= 1.0 or b <= 0:
            return {
                "theta": 0.0,
                "mu": float(np.mean(S)),
                "sigma_ou": float(np.std(S)),
                "half_life": 999.0, # Infinite / non-stationary
                "is_stationary": False
            }

        theta = -np.log(b) / dt
        mu = a / (1.0 - b)

        residuals = S_curr - (a + b * S_prev)
        var_res = np.var(residuals)

        denom = (1.0 - np.exp(-2.0 * theta * dt)) / (2.0 * theta)
        sigma_ou = np.sqrt(max(var_res / denom, 1e-8))

        half_life = np.log(2.0) / theta

        return {
            "theta": float(theta),
            "mu": float(mu),
            "sigma_ou": float(sigma_ou),
            "half_life": float(half_life),
            "is_stationary": True
        }

    def compute_z_score(self, spread: pd.Series, lookback: int = 30) -> pd.Series:
        """
        Calculates rolling Z-Score of the spread: Z = (Spread - Rolling_Mean) / Rolling_Std
        """
        mean = spread.rolling(window=lookback).mean()
        std = spread.rolling(window=lookback).std().replace(0, 1e-8)
        z_score = (spread - mean) / std
        return z_score.fillna(0.0)

    def backtest_pairs(self, df_y: pd.DataFrame, df_x: pd.DataFrame, ticker_y: str = "KO", ticker_x: str = "PEP", lookback: int = 30) -> Dict:
        """
        Backtests Pairs Trading Strategy (Long Spread when Z < -2.0, Short Spread when Z > +2.0).
        """
        price_y = df_y['Close']
        price_x = df_x['Close']

        # Ensure index alignment
        aligned = pd.concat([price_y, price_x], axis=1, keys=[ticker_y, ticker_x]).dropna()
        py = aligned[ticker_y]
        px = aligned[ticker_x]

        alpha, beta, spread = self.calculate_hedge_ratio(py, px)
        ou_params = self.fit_ornstein_uhlenbeck(spread)
        z_scores = self.compute_z_score(spread, lookback=lookback)

        position = 0 # +1: Long Spread (Buy Y, Sell X), -1: Short Spread (Sell Y, Buy X), 0: Flat
        trades = []
        equity_curve = [100000.0]
        cash = 100000.0

        for i in range(1, len(aligned)):
            z = z_scores.iloc[i]
            p_y = py.iloc[i]
            p_x = px.iloc[i]
            ts = aligned.index[i]

            # Signal evaluation
            if position == 0:
                if z <= -self.z_entry:
                    position = 1 # Long Y, Short X
                    trades.append({"timestamp": str(ts), "action": "LONG_SPREAD", "z_score": round(z, 2), "price_y": p_y, "price_x": p_x})
                elif z >= self.z_entry:
                    position = -1 # Short Y, Long X
                    trades.append({"timestamp": str(ts), "action": "SHORT_SPREAD", "z_score": round(z, 2), "price_y": p_y, "price_x": p_x})
            elif position == 1: # Currently Long Spread
                if z >= -self.z_exit:
                    position = 0 # Exit
                    trades.append({"timestamp": str(ts), "action": "EXIT_LONG_SPREAD", "z_score": round(z, 2), "price_y": p_y, "price_x": p_x})
            elif position == -1: # Currently Short Spread
                if z <= self.z_exit:
                    position = 0 # Exit
                    trades.append({"timestamp": str(ts), "action": "EXIT_SHORT_SPREAD", "z_score": round(z, 2), "price_y": p_y, "price_x": p_x})

        return {
            "ticker_y": ticker_y,
            "ticker_x": ticker_x,
            "hedge_ratio_beta": round(beta, 4),
            "intercept_alpha": round(alpha, 4),
            "ou_mean_reversion_speed_theta": round(ou_params["theta"], 4),
            "ou_half_life_bars": round(ou_params["half_life"], 2),
            "is_stationary": ou_params["is_stationary"],
            "total_trades": len(trades),
            "trade_log": trades[:10] # Top 10 trades preview
        }

if __name__ == "__main__":
    print("Testing StatArbEngine...")
    np.random.seed(42)
    n = 200
    # Synthetic cointegrated pair: Y = 1.5 * X + noise
    x_prices = 100.0 + np.cumsum(np.random.normal(0, 1.0, n))
    noise = np.random.normal(0, 0.5, n) # Mean-reverting stationary noise
    y_prices = 10.0 + 1.5 * x_prices + noise

    df_y = pd.DataFrame({'Close': y_prices}, index=pd.date_range('2024-01-01', periods=n))
    df_x = pd.DataFrame({'Close': x_prices}, index=pd.date_range('2024-01-01', periods=n))

    engine = StatArbEngine()
    result = engine.backtest_pairs(df_y, df_x, "KO", "PEP")
    print(f"Hedge Ratio (Beta): {result['hedge_ratio_beta']}")
    print(f"OU Mean Reversion Speed (Theta): {result['ou_mean_reversion_speed_theta']}")
    print(f"OU Half-Life: {result['ou_half_life_bars']} bars")
    print(f"Total Trades Triggered: {result['total_trades']}")
    print("[+] StatArbEngine operational.")
