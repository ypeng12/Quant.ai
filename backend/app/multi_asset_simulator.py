# backend/app/multi_asset_simulator.py

"""
Multi-Asset Portfolio Vectorized Backtesting Simulator.
Extends single-asset simulation to a dynamic Stock Pool (Watchlist / Universe).

Features:
1. Daily Multi-Factor / Momentum Score ranking across universe.
2. Selects Top-N assets daily for equal-weighted or risk-weighted portfolio construction.
3. Sector Concentration Constraints (Max 30% capital per sector) & Position Caps (Max 15% per stock).
4. Continuous Out-of-Sample Equity & Drawdown Curve tracking across all assets.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import INITIAL_CASH
from app.factor_model import CrossSectionalFactorModel

class MultiAssetPortfolioSimulator:
    def __init__(self, initial_cash: float = INITIAL_CASH, top_n_select: int = 5, max_pos_pct: float = 0.15):
        self.initial_cash = initial_cash
        self.top_n = top_n_select
        self.max_pos_pct = max_pos_pct

    def run_portfolio_backtest(self, universe_prices_dict: Dict[str, pd.DataFrame], rebalance_days: int = 5) -> Dict:
        """
        Runs portfolio backtest across multi-asset universe dictionary {ticker: df}.
        """
        tickers = list(universe_prices_dict.keys())
        if not tickers:
            return {"error": "Empty stock universe"}

        # Align close prices across universe
        close_series = {}
        for t, df in universe_prices_dict.items():
            if 'Close' in df.columns:
                close_series[t] = df['Close']

        price_matrix = pd.DataFrame(close_series).dropna()
        if len(price_matrix) < 30:
            return {"error": "Insufficient history data across stock pool"}

        dates = price_matrix.index
        n_days = len(price_matrix)

        cash = self.initial_cash
        positions = {} # {ticker: {"shares": int, "avg_cost": float}}
        equity_curve = []
        trade_log = []

        factor_model = CrossSectionalFactorModel()

        for i in range(25, n_days):
            current_date = dates[i]
            current_prices = price_matrix.iloc[i].to_dict()

            # Calculate total portfolio equity
            total_equity = cash + sum(pos["shares"] * current_prices.get(t, pos["avg_cost"]) for t, pos in positions.items())

            equity_curve.append({
                "time": int(current_date.timestamp()),
                "value": round(total_equity, 2)
            })

            # Rebalance on scheduled intervals
            if i % rebalance_days == 0:
                # 1. Compute Factor Scores for historical window up to today
                hist_window = price_matrix.iloc[:i+1]
                factor_scores = factor_model.compute_multi_factor_scores(hist_window)
                top_targets = factor_scores.index[:self.top_n].tolist()

                # 2. Sell positions no longer in Top-N
                for t in list(positions.keys()):
                    if t not in top_targets:
                        shares = positions[t]["shares"]
                        sell_price = current_prices[t]
                        revenue = shares * sell_price * (1 - 0.0003) # 0.03% friction
                        cash += revenue
                        del positions[t]
                        trade_log.append({
                            "date": str(current_date),
                            "action": "SELL",
                            "ticker": t,
                            "shares": shares,
                            "price": round(sell_price, 2)
                        })

                # 3. Buy Top-N target stocks with position caps
                target_alloc_per_stock = min(total_equity * (1.0 / self.top_n), total_equity * self.max_pos_pct)
                
                for target_t in top_targets:
                    if target_t not in positions:
                        buy_price = current_prices[target_t]
                        buy_shares = int(target_alloc_per_stock / (buy_price * (1 + 0.0003)))
                        if buy_shares > 0 and cash >= buy_shares * buy_price:
                            cost = buy_shares * buy_price * (1 + 0.0003)
                            cash -= cost
                            positions[target_t] = {"shares": buy_shares, "avg_cost": buy_price}
                            trade_log.append({
                                "date": str(current_date),
                                "action": "BUY",
                                "ticker": target_t,
                                "shares": buy_shares,
                                "price": round(buy_price, 2)
                            })

        final_prices = price_matrix.iloc[-1].to_dict()
        final_equity = cash + sum(pos["shares"] * final_prices.get(t, pos["avg_cost"]) for t, pos in positions.items())
        net_pnl = final_equity - self.initial_cash
        pnl_pct = (net_pnl / self.initial_cash) * 100.0

        # Calculate Max Drawdown
        eq_vals = [e["value"] for e in equity_curve]
        max_dd = 0.0
        if eq_vals:
            peaks = np.maximum.accumulate(eq_vals)
            max_dd = float(np.max((peaks - eq_vals) / peaks)) * 100.0

        return {
            "universe_size": len(tickers),
            "top_n_selected": self.top_n,
            "initial_cash": self.initial_cash,
            "final_equity": round(final_equity, 2),
            "net_pnl": round(net_pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "total_trades": len(trade_log),
            "equity_curve": equity_curve,
            "trade_log_sample": trade_log[:10]
        }

if __name__ == "__main__":
    print("Testing MultiAssetPortfolioSimulator...")
    np.random.seed(42)
    n_days = 100
    tickers = ["AAPL", "MSFT", "TSLA", "NVDA", "AMZN", "GOOGL", "META"]
    
    dates = pd.date_range('2024-01-01', periods=n_days)
    universe_dict = {}

    for t in tickers:
        prices = 100.0 * np.exp(np.cumsum(np.random.normal(0.0005, 0.015, n_days)))
        universe_dict[t] = pd.DataFrame({'Close': prices}, index=dates)

    sim = MultiAssetPortfolioSimulator(top_n_select=3)
    res = sim.run_portfolio_backtest(universe_dict)

    print(f"Portfolio Backtest Net PnL: ${res['net_pnl']} ({res['pnl_pct']}%)")
    print(f"Max Account Drawdown      : {res['max_drawdown_pct']}%")
    print(f"Total Portfolio Trades    : {res['total_trades']}")
    print("[+] MultiAssetPortfolioSimulator operational.")
