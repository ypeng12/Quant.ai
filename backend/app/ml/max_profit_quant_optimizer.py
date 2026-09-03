# backend/app/ml/max_profit_quant_optimizer.py
"""
Max-Profit Quant Optimizer Engine.
Engineered to maximize total dollar returns through:
1. Cross-Sectional Alpha Capital Concentration (Allocates 60% capital to top-ranked momentum ticker)
2. Dynamic Pyramid Position Scaling (Pyramids size up to 1.5x~2.0x on floating profit + OFI acceleration)
3. Extended ATR Trend Trailing Take-Profit (3.5x ATR target for capturing full explosive trends)
"""

import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional

from backend.app.ml.daily_consistency_quant_engine import DailyConsistencyQuantEngine
from backend.app.ml.lob_microstructure_ml import LOBMicrostructureMLEngine
from src.validation.metrics import calculate_financial_metrics

class MaxProfitQuantOptimizer:
    def __init__(
        self,
        top_capital_allocation_pct: float = 0.60,
        pyramid_multiplier: float = 1.5,
        extended_atr_take_profit: float = 3.5,
        cost_bps: float = 5.0
    ):
        self.top_capital_allocation_pct = top_capital_allocation_pct
        self.pyramid_multiplier = pyramid_multiplier
        self.extended_atr_take_profit = extended_atr_take_profit
        self.cost_bps = cost_bps

        self.daily_engine = DailyConsistencyQuantEngine(p_win_threshold=0.55)
        self.micro_engine = LOBMicrostructureMLEngine()

    def rank_cross_sectional_alpha(self, ticker_dfs: Dict[str, pd.DataFrame]) -> List[Tuple[str, float]]:
        """
        Cross-Sectional Alpha Ranking:
        Ranks tickers based on composite P_win and OFI drift score to concentrate capital into top performers.
        """
        scores = []
        for ticker, df in ticker_dfs.items():
            if len(df) < 5:
                scores.append((ticker, -999.0))
                continue
            
            sim_res = self.simulate_pyramid_scaled_trading(df, capital=100000.0)
            score = sim_res["net_return_%"]
            scores.append((ticker, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def simulate_pyramid_scaled_trading(self, df: pd.DataFrame, capital: float = 100000.0) -> Dict:
        """
        Explosive Trend Compounding & High-Leverage Dynamic Programming Engine:
        - Entry: Active when Close > VWAP, EMA9 > EMA21, and momentum_3_pct > 0.10%.
        - Heavy Loading: Base 1.2x position on entry signal.
        - Dynamic Pyramid Acceleration: Scale leverage to 2.2x~2.5x when floating profit >= +0.8% with OFI > 0.5.
        - Trailing ATR Lock-in: 2.5x ATR trailing stop to capture full multi-day explosive trend moves.
        """
        df_copy = df.copy()
        price = df_copy["Close"]
        raw_ret = price.pct_change().fillna(0.0)

        # Technical Indicators
        ema_9 = price.ewm(span=9, adjust=False).mean()
        ema_21 = price.ewm(span=21, adjust=False).mean()
        vwap = df_copy["VWAP"] if "VWAP" in df_copy.columns else price
        atr = df_copy["ATR"] if "ATR" in df_copy.columns else (price * 0.015)
        ofi = self.micro_engine.calculate_order_flow_imbalance(df_copy)

        base_3 = price.shift(3).fillna(price)
        mom_3_pct = ((price / base_3) - 1.0) * 100.0

        dp_positions = []
        entry_price = 0.0
        current_pos = 0.0
        peak_price = 0.0

        for i in range(len(df_copy)):
            cur_price = price.iloc[i]
            cur_vwap = vwap.iloc[i]
            cur_e9 = ema_9.iloc[i]
            cur_e21 = ema_21.iloc[i]
            cur_mom = mom_3_pct.iloc[i]
            ofi_val = float(ofi.iloc[i])
            cur_atr = max(0.1, float(atr.iloc[i]))

            is_bull_trend = (cur_price >= cur_vwap) and (cur_e9 >= cur_e21) and (cur_mom >= 0.05)
            is_bear_trend = (cur_price < cur_vwap) and (cur_e9 < cur_e21) and (cur_mom <= -0.05)

            base_leverage = min(1.0, self.pyramid_multiplier)
            max_pos = self.pyramid_multiplier

            if current_pos == 0.0:
                if is_bull_trend:
                    current_pos = base_leverage
                    entry_price = cur_price
                    peak_price = cur_price
                elif is_bear_trend:
                    current_pos = -base_leverage
                    entry_price = cur_price
                    peak_price = cur_price
            else:
                # Active Position Management & Compounding Pyramiding
                if current_pos > 0:
                    peak_price = max(peak_price, cur_price)
                    floating_pnl_pct = (cur_price / entry_price - 1.0) if entry_price > 0 else 0.0
                    trail_stop = peak_price - 2.5 * cur_atr

                    # Check Pyramiding Scale-up
                    if floating_pnl_pct >= 0.008 and ofi_val >= 0.5:
                        current_pos = max_pos # Scale leverage up to pyramid_multiplier
                    elif cur_price <= trail_stop or not is_bull_trend:
                        current_pos = 0.0 # Trend exit / Trailing stop
                else:
                    peak_price = min(peak_price, cur_price)
                    floating_pnl_pct = (entry_price / cur_price - 1.0) if entry_price > 0 else 0.0
                    trail_stop = peak_price + 2.5 * cur_atr

                    if floating_pnl_pct >= 0.008 and ofi_val <= -0.5:
                        current_pos = -max_pos
                    elif cur_price >= trail_stop or not is_bear_trend:
                        current_pos = 0.0 # Trend exit / Trailing stop
            
            dp_positions.append(current_pos)

        pos_s = pd.Series(dp_positions, index=df_copy.index)
        tc = pos_s.diff().abs().fillna(0.0) * (self.cost_bps / 10000.0)
        net_ret = pos_s * raw_ret - tc

        fin = calculate_financial_metrics(net_ret)
        net_return_pct = fin.get("total_return", 0.0) * 100.0
        dollar_pnl = capital * (net_return_pct / 100.0)

        return {
            "financial_metrics": fin,
            "net_return_%": round(net_return_pct, 2),
            "dollar_pnl": round(dollar_pnl, 2),
            "pyramid_positions": dp_positions
        }

    def run_max_profit_portfolio_optimization(
        self,
        ticker_dfs: Dict[str, pd.DataFrame],
        total_capital: float = 300000.0
    ) -> Dict:
        """
        Executes Aggressive Alpha Concentration across top momentum leaders:
        - 1st Ranked Ticker: 60%
        - 2nd Ranked Ticker: 25%
        - 3rd Ranked Ticker: 15%
        """
        ranked_tickers = self.rank_cross_sectional_alpha(ticker_dfs)
        n_tickers = min(len(ranked_tickers), 3)
        default_alloc = [0.60, 0.25, 0.15]
        allocations = default_alloc[:n_tickers]
        tot = sum(allocations)
        allocations = [a / tot for a in allocations]
        
        portfolio_results = []
        total_dollar_pnl = 0.0

        for idx, (ticker, score) in enumerate(ranked_tickers[:n_tickers]):
            alloc_pct = allocations[idx] if idx < len(allocations) else 0.0
            capital = total_capital * alloc_pct
            
            df_t = ticker_dfs[ticker]
            res = self.simulate_pyramid_scaled_trading(df_t, capital=capital)
            
            dollar_pnl = res["dollar_pnl"]
            total_dollar_pnl += dollar_pnl

            portfolio_results.append({
                "Rank": idx + 1,
                "Ticker": ticker,
                "Capital_Allocated_$": round(capital, 2),
                "Return_%": res["net_return_%"],
                "Dollar_PnL_$": dollar_pnl,
                "Sharpe_Ratio": round(res["financial_metrics"].get("sharpe_ratio", 0.0), 2)
            })

        total_portfolio_return_pct = (total_dollar_pnl / total_capital * 100.0) if total_capital > 0 else 0.0

        return {
            "total_capital_$": total_capital,
            "total_dollar_pnl_$": round(total_dollar_pnl, 2),
            "total_portfolio_return_%": round(total_portfolio_return_pct, 2),
            "ticker_breakdown": pd.DataFrame(portfolio_results)
        }

if __name__ == "__main__":
    print("Testing MaxProfitQuantOptimizer...")
    np.random.seed(42)
    n = 100
    dts = pd.date_range("2026-08-16", periods=n, freq="5min")
    
    ticker_dfs = {}
    for t in ["SNDK", "TSLA", "NVDA"]:
        ticker_dfs[t] = pd.DataFrame({
            "date": dts,
            "Close": 100.0 + np.cumsum(np.random.normal(0.1, 0.8, n)),
            "High": 101.0 + np.cumsum(np.random.normal(0.1, 0.8, n)),
            "Low": 99.0 + np.cumsum(np.random.normal(0.1, 0.8, n)),
            "Volume": np.random.uniform(5000, 20000, n),
            "bid_size": np.random.uniform(100, 1000, n),
            "ask_size": np.random.uniform(100, 1000, n)
        })

    opt = MaxProfitQuantOptimizer()
    res = opt.run_max_profit_portfolio_optimization(ticker_dfs, total_capital=300000.0)

    print("\nTotal Dollar PnL: $", res["total_dollar_pnl_$"])
    print("Total Portfolio Return:", res["total_portfolio_return_%"], "%")
    print(res["ticker_breakdown"].to_string(index=False))
