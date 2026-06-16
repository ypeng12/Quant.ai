# backend/app/simulator.py

import pandas as pd
import numpy as np
import datetime
from app.config import INITIAL_CASH, FORCE_LIQUIDATION_TIME, SOFT_DRAWDOWN_LIMIT, HARD_DRAWDOWN_LIMIT, MAX_CONSECUTIVE_LOSSES
from app.trading_engine import Portfolio
from app.strategy import evaluate_market_state

def run_backtest_sim(df, ticker, strategy_params, risk_params, is_intraday=True):
    """
    通用回测执行引擎，支持日内 (is_intraday=True) 和日线 (is_intraday=False) 级别回测
    """
    portfolio = Portfolio(
        initial_cash=INITIAL_CASH,
        slippage_rate=risk_params.get("slippage_rate", 0.0003),
        commission_per_share=risk_params.get("commission_per_share", 0.005),
        min_commission_per_order=risk_params.get("min_commission_per_order", 1.0)
    )
    
    # 提取账户风控限制
    soft_dd = risk_params.get("soft_dd", SOFT_DRAWDOWN_LIMIT)
    hard_dd = risk_params.get("hard_dd", HARD_DRAWDOWN_LIMIT)
    max_consecutive_losses = risk_params.get("max_consecutive_losses", MAX_CONSECUTIVE_LOSSES)
    
    equity_curve = []
    
    # 我们从第2行开始，因为策略需要 prev_row 进行对比
    for i in range(1, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        timestamp = df.index[i]
        time_str = timestamp.strftime("%H:%M")
        
        close_price = float(row['Close'])
        current_prices = {ticker: close_price}
        
        shares = portfolio.get_position_shares(ticker)
        avg_cost = portfolio.get_position_avg_cost(ticker)
        
        # 1. 账户级风控指标更新 (含最高权益及回撤计算)
        equity = portfolio.get_equity(current_prices)
        portfolio.peak_equity = max(portfolio.peak_equity, equity)
        drawdown_pct = (portfolio.peak_equity - equity) / portfolio.peak_equity if portfolio.peak_equity > 0 else 0.0
        
        # 统计最近 SELL 操作的 realized_pnl
        sell_trades = [t for t in portfolio.ledger if t['action'] == 'SELL']
        consecutive_losses = 0
        for t in reversed(sell_trades):
            if t.get('realized_pnl', 0.0) < 0:
                consecutive_losses += 1
            else:
                break
        portfolio.consecutive_losses = consecutive_losses
        
        # 2. 判定硬/软熔断并更新 risk_multiplier
        if drawdown_pct >= hard_dd:
            portfolio.risk_multiplier = 0.0
        elif drawdown_pct >= soft_dd or consecutive_losses >= max_consecutive_losses:
            portfolio.risk_multiplier = 0.5
        else:
            portfolio.risk_multiplier = 1.0
            
        # 3. 更新追踪止损的最高价
        if shares > 0:
            portfolio.update_highest_price(ticker, close_price)
            
        highest_price = portfolio.get_position_highest_price(ticker)
        
        # 记录资产曲线数据
        equity_curve.append({
            "time": int(timestamp.timestamp()),
            "value": round(equity, 2)
        })
        
        # 4. 日内清仓检测 (仅限 1分钟、5分钟等日内级别)
        if is_intraday and time_str == FORCE_LIQUIDATION_TIME and shares > 0:
            portfolio.sell(timestamp, ticker, close_price, shares)
            continue
            
        # 5. 执行常规策略评估
        is_trading_window = True
        if is_intraday:
            # 日内交易时间窗口：上午 9:35 到 下午 15:54
            is_trading_window = datetime.time(9, 35) <= timestamp.time() < datetime.time(15, 54)
            
        if is_trading_window:
            action, explanation = evaluate_market_state(
                row, prev_row, shares, avg_cost, ticker, highest_price, strategy_params
            )
            
            if action == "BUY" and shares == 0:
                # 仓位计算
                if risk_params.get("position_sizing_mode", "atr") == "atr":
                    shares_to_buy = portfolio.calculate_position_size(
                        ticker, close_price, row['ATR'],
                        risk_pct=risk_params.get("risk_per_trade_pct", 0.01),
                        atr_multiplier=strategy_params.get("trailing_stop_atr_mult", 2.0),
                        max_size_pct=risk_params.get("max_position_size_pct", 0.50)
                    )
                else:
                    target_allocation = equity * risk_params.get("max_position_size_pct", 0.50)
                    shares_to_buy = int(target_allocation / close_price)
                    
                if shares_to_buy > 0:
                    portfolio.buy(timestamp, ticker, close_price, shares_to_buy)
                    
            elif action == "SELL" and shares > 0:
                portfolio.sell(timestamp, ticker, close_price, shares)
                
    # 6. 计算回测指标
    total_trades = len(portfolio.ledger)
    final_equity = portfolio.get_equity({ticker: df.iloc[-1]['Close']})
    net_pnl = final_equity - INITIAL_CASH
    pnl_pct = (net_pnl / INITIAL_CASH) * 100
    
    sell_trades = [t for t in portfolio.ledger if t['action'] == 'SELL']
    winning_trades = [t for t in sell_trades if t.get('realized_pnl', 0.0) > 0]
    win_rate = (len(winning_trades) / len(sell_trades)) * 100 if sell_trades else 0.0
    
    total_commission = sum(t['commission'] for t in portfolio.ledger)
    
    # 统计最大回撤
    eq_vals = [e["value"] for e in equity_curve]
    max_drawdown = 0.0
    if eq_vals:
        peaks = np.maximum.accumulate(eq_vals)
        drawdowns = (peaks - eq_vals) / peaks
        max_drawdown = float(np.max(drawdowns))
        
    return {
        "final_equity": round(final_equity, 2),
        "net_pnl": round(net_pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "total_trades": total_trades,
        "round_trips": len(sell_trades),
        "win_rate": round(win_rate, 2),
        "commission": round(total_commission, 2),
        "max_drawdown": round(max_drawdown, 4),
        "ledger": portfolio.ledger,
        "equity_curve": equity_curve
    }
