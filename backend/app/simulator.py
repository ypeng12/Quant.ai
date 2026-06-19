# backend/app/simulator.py

import pandas as pd
import numpy as np
import datetime
from app.config import INITIAL_CASH, FORCE_LIQUIDATION_TIME, SOFT_DRAWDOWN_LIMIT, HARD_DRAWDOWN_LIMIT, MAX_CONSECUTIVE_LOSSES, FORCE_LIQUIDATION_OPEN_FOCUS
from app.trading_engine import Portfolio
from app.strategy import evaluate_market_state

def run_backtest_sim(df, ticker, strategy_params, risk_params, is_intraday=True):
    """
    通用回测执行引擎，支持日内 (is_intraday=True) 和日线 (is_intraday=False) 级别回测。
    增强输出：regime_breakdown, drawdown_curve, Sharpe, Calmar, CAGR, Profit Factor
    """
    df = df.copy()
    if is_intraday:
        # Precompute ORB (Opening Range Breakout) High/Low for each day
        # Range is defined between 9:30 and 9:35 (first 5 minutes of regular trading hours)
        df['Time'] = df.index.time
        df['Date'] = df.index.date
        
        import datetime as dt_mod
        open_mask = (df['Time'] >= dt_mod.time(9, 30)) & (df['Time'] <= dt_mod.time(9, 35))
        opening_df = df[open_mask]
        
        if not opening_df.empty:
            orb_high = opening_df.groupby('Date')['High'].max().to_dict()
            orb_low = opening_df.groupby('Date')['Low'].min().to_dict()
            df['ORB_High'] = df['Date'].map(orb_high).fillna(0.0)
            df['ORB_Low'] = df['Date'].map(orb_low).fillna(0.0)
        else:
            df['ORB_High'] = 0.0
            df['ORB_Low'] = 0.0

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
    
    # 提取开盘突击模式参数，默认是 True
    market_open_focus = strategy_params.get("market_open_focus", True)
    
    equity_curve = []
    
    # 记录每笔交易所处的 regime（用于 regime breakdown）
    trade_regime_map = {}  # buy_timestamp -> regime
    
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
        liq_time = FORCE_LIQUIDATION_OPEN_FOCUS if market_open_focus else FORCE_LIQUIDATION_TIME
        if is_intraday and time_str == liq_time and shares > 0:
            portfolio.sell(timestamp, ticker, close_price, shares)
            continue
            
        # 5. 执行常规策略评估
        is_trading_window = True
        if is_intraday:
            if market_open_focus:
                # 开盘突击：只在 9:35 - 10:15 之间开新仓
                import datetime as dt_mod
                is_trading_window = dt_mod.time(9, 35) <= timestamp.time() <= dt_mod.time(10, 15)
            else:
                # 日内交易时间窗口：上午 9:35 到 下午 15:54
                is_trading_window = datetime.time(9, 35) <= timestamp.time() < datetime.time(15, 54)
                
        # 如果我们已经持有仓位，为了检查止损止盈等，任何时间（直到强制平仓前）都是交易窗口
        if shares > 0:
            is_trading_window = True
        if is_trading_window:
            current_regime = row.get('Regime', 'range_bound')
            
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
                    # 记录买入时的 regime
                    trade_regime_map[str(timestamp)] = current_regime
                    
            elif action == "SELL" and shares > 0:
                portfolio.sell(timestamp, ticker, close_price, shares)
                
    # 6. 计算回测指标
    total_trades = len(portfolio.ledger)
    final_equity = portfolio.get_equity({ticker: df.iloc[-1]['Close']})
    net_pnl = final_equity - INITIAL_CASH
    pnl_pct = (net_pnl / INITIAL_CASH) * 100
    
    sell_trades = [t for t in portfolio.ledger if t['action'] == 'SELL']
    winning_trades = [t for t in sell_trades if t.get('realized_pnl', 0.0) > 0]
    losing_trades = [t for t in sell_trades if t.get('realized_pnl', 0.0) < 0]
    win_rate = (len(winning_trades) / len(sell_trades)) * 100 if sell_trades else 0.0
    
    total_commission = sum(t['commission'] for t in portfolio.ledger)
    
    # 统计最大回撤与 drawdown curve
    eq_vals = [e["value"] for e in equity_curve]
    max_drawdown = 0.0
    drawdown_curve = []
    if eq_vals:
        peaks = np.maximum.accumulate(eq_vals)
        drawdowns = (peaks - eq_vals) / peaks
        max_drawdown = float(np.max(drawdowns))
        for idx_ec, ec in enumerate(equity_curve):
            drawdown_curve.append({
                "time": ec["time"],
                "value": round(float(drawdowns[idx_ec]) * -100, 2)  # 负百分比
            })
    
    # 7. 高级指标计算
    # Profit Factor = 总盈利 / 总亏损
    gross_profit = sum(t.get('realized_pnl', 0.0) for t in winning_trades)
    gross_loss = abs(sum(t.get('realized_pnl', 0.0) for t in losing_trades))
    profit_factor = round(gross_profit / max(gross_loss, 1e-8), 2)
    
    # 计算回测跨度的交易日数
    if len(df) >= 2:
        start_date = df.index[0]
        end_date = df.index[-1]
        total_days = (end_date - start_date).days
        total_years = total_days / 365.25 if total_days > 0 else 1.0 / 365.25
    else:
        total_years = 1.0 / 365.25
    
    # CAGR = (Final/Initial)^(1/years) - 1
    if final_equity > 0 and INITIAL_CASH > 0 and total_years > 0:
        cagr = (final_equity / INITIAL_CASH) ** (1.0 / max(total_years, 0.01)) - 1.0
    else:
        cagr = 0.0
    
    # Sharpe Ratio (基于日/bar收益序列，假设 risk-free = 0)
    if len(eq_vals) > 1:
        returns = np.diff(eq_vals) / np.array(eq_vals[:-1])
        if np.std(returns) > 0:
            # 年化 Sharpe（按交易日数年化）
            bars_per_year = len(eq_vals) / max(total_years, 0.01)
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(bars_per_year)
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0
    
    # Calmar Ratio = CAGR / Max Drawdown
    calmar = round(cagr / max(max_drawdown, 1e-8), 2) if max_drawdown > 0.001 else 0.0
    
    # 8. Regime Breakdown — 统计不同市场状态下交易表现
    regime_breakdown = _compute_regime_breakdown(portfolio.ledger, trade_regime_map)
    
    # 9. Regime 分布统计 (每个 regime 的 bar 数量占比)
    regime_distribution = {}
    if 'Regime' in df.columns:
        regime_counts = df['Regime'].value_counts()
        total_bars = len(df)
        for regime_name, count in regime_counts.items():
            regime_distribution[regime_name] = round(count / total_bars * 100, 1)
    
    return {
        "final_equity": round(final_equity, 2),
        "net_pnl": round(net_pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "total_trades": total_trades,
        "round_trips": len(sell_trades),
        "win_rate": round(win_rate, 2),
        "commission": round(total_commission, 2),
        "max_drawdown": round(max_drawdown, 4),
        # 新增高级指标
        "sharpe": round(sharpe, 2),
        "calmar": calmar,
        "cagr": round(cagr * 100, 2),  # 百分比
        "profit_factor": profit_factor,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        # 数据序列
        "ledger": portfolio.ledger,
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        # Regime 统计
        "regime_breakdown": regime_breakdown,
        "regime_distribution": regime_distribution,
    }


def _compute_regime_breakdown(ledger, trade_regime_map):
    """
    按 regime 汇总交易表现：pnl, win_rate, trade_count
    """
    regime_stats = {}
    
    # 将 BUY/SELL 配对，并查找每对交易的 regime
    buy_trades = [t for t in ledger if t['action'] == 'BUY']
    sell_trades = [t for t in ledger if t['action'] == 'SELL']
    
    for i, sell in enumerate(sell_trades):
        # 每个 sell 与对应的 buy 配对
        if i < len(buy_trades):
            buy_ts = buy_trades[i]['timestamp']
            regime = trade_regime_map.get(buy_ts, 'unknown')
        else:
            regime = 'unknown'
        
        pnl = sell.get('realized_pnl', 0.0)
        
        if regime not in regime_stats:
            regime_stats[regime] = {
                'total_pnl': 0.0,
                'trade_count': 0,
                'wins': 0,
                'losses': 0,
                'total_commission': 0.0
            }
        
        regime_stats[regime]['total_pnl'] += pnl
        regime_stats[regime]['trade_count'] += 1
        regime_stats[regime]['total_commission'] += sell.get('commission', 0.0)
        if pnl > 0:
            regime_stats[regime]['wins'] += 1
        else:
            regime_stats[regime]['losses'] += 1
    
    # 转为前端友好格式
    result = []
    for regime, stats in regime_stats.items():
        win_rate = (stats['wins'] / stats['trade_count'] * 100) if stats['trade_count'] > 0 else 0.0
        result.append({
            "regime": regime,
            "total_pnl": round(stats['total_pnl'], 2),
            "trade_count": stats['trade_count'],
            "win_rate": round(win_rate, 1),
            "wins": stats['wins'],
            "losses": stats['losses'],
            "commission": round(stats['total_commission'], 2)
        })
    
    # 按 trade_count 降序
    result.sort(key=lambda x: x['trade_count'], reverse=True)
    return result
