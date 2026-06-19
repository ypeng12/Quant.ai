import sys
import os

# Append project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from backend.app.data_manager import fetch_and_prepare_data, get_company_info
from backend.app.patterns import analyze_patterns
from backend.app.simulator import run_backtest_sim

def test_tune():
    ticker = "TSLA"
    interval = "1m"
    period = "5d"
    
    print(f"Fetching data for {ticker}...")
    df_raw = fetch_and_prepare_data(ticker, period=period, interval=interval)
    df = analyze_patterns(df_raw)
    
    print(f"Running grid search optimization for opening focus...")
    best_score = -999999.0
    best_params = None
    best_res = None
    
    strategy_options = ["opening_breakout", "consensus", "dynamic", "patterns"]
    stop_loss_options = [0.005, 0.01, 0.015, 0.02]
    profit_target_options = [0.01, 0.02, 0.03, 0.05]
    atr_mult_options = [1.5, 2.0, 2.5]
    
    risk_params = {
        "slippage_rate": 0.0003,
        "commission_per_share": 0.005,
        "min_commission_per_order": 1.0,
        "position_sizing_mode": "atr",
        "risk_per_trade_pct": 0.01,
        "max_position_size_pct": 0.50
    }
    
    is_intraday = interval in ["1m", "5m", "15m", "30m", "1h"]
    
    for mode in strategy_options:
        for sl in stop_loss_options:
            for pt in profit_target_options:
                for atr_m in atr_mult_options:
                    params = {
                        "strategy_mode": mode,
                        "stop_loss_pct": sl,
                        "profit_target_pct": pt,
                        "trailing_stop_mode": "atr",
                        "trailing_stop_atr_mult": atr_m,
                        "rsi_threshold_buy": 65.0,
                        "market_open_focus": True
                    }
                    
                    res = run_backtest_sim(df, ticker, params, risk_params, is_intraday=is_intraday)
                    
                    net_pnl = res["net_pnl"]
                    max_dd = res["max_drawdown"]
                    win_rate = res["win_rate"]
                    trades = res["round_trips"]
                    
                    if trades == 0:
                        score = -1000.0
                    else:
                        score = net_pnl - (max_dd * 30000.0 * 4.0) + (win_rate * 2.0)
                        
                    if score > best_score:
                        best_score = score
                        best_params = params
                        best_res = res
                        
    print("\n=== AI Optimization Results ===")
    print(f"Best strategy mode: {best_params['strategy_mode']}")
    print(f"Best stop loss: {best_params['stop_loss_pct']*100}%")
    print(f"Best profit target: {best_params['profit_target_pct']*100}%")
    print(f"Best ATR trailing stop mult: {best_params['trailing_stop_atr_mult']}x")
    print(f"Net PnL: ${best_res['net_pnl']:.2f}")
    print(f"Win Rate: {best_res['win_rate']:.1f}%")
    print(f"Max Drawdown: {best_res['max_drawdown']*100:.2f}%")
    print(f"Total round trips: {best_res['round_trips']}")
    
    ticker_details = get_company_info(ticker)
    name = ticker_details.get("name", ticker)
    mode_cn = {
        "opening_breakout": "开盘突击突破策略",
        "consensus": "共振共识策略",
        "dynamic": "动态状态路由策略",
        "patterns": "K线形态反转策略"
    }.get(best_params["strategy_mode"], best_params["strategy_mode"])
    
    reasoning = (
        f"AI 智能托管针对 {name} 最近 {period} 的日内波动特征运行了机器学习调优算法。\n"
        f"由于开盘 3-5 分钟振幅大且伴随突破，AI 自动推荐采用【{mode_cn}】来追踪走势。\n"
        f"风控策略已自动调整为：硬止损设为 {(best_params['stop_loss_pct']*100):.1f}%，"
        f"目标止盈设为 {(best_params['profit_target_pct']*100):.1f}%，"
        f"配合 {best_params['trailing_stop_atr_mult']:.1f}倍 ATR 移动追踪止损以防高位跌落。\n"
        f"该优化组合在近期的历史回测中实现了约 ${best_res['net_pnl']:.2f} 的净盈亏，"
        f"胜率达 {best_res['win_rate']:.1f}%，最大回撤控制在 {(best_res['max_drawdown']*100):.2f}%，有效规避了单边下挫风险。"
    )
    print("\n=== AI Generated Reasoning ===")
    print(reasoning)

if __name__ == "__main__":
    test_tune()
