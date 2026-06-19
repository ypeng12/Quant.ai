# backend/main.py

import argparse
import sys
import pandas as pd
import datetime
import os

# 确保 backend 目录在 sys.path 中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.config import INITIAL_CASH, MAX_POSITION_SIZE_PCT, WATCHLIST
from app.data_manager import fetch_and_prepare_data
from app.patterns import analyze_patterns
from app.simulator import run_backtest_sim

def run_simulation(ticker, period="5d", interval="1m", strategy_mode="dynamic", position_sizing_mode="atr"):
    """
    运行日内/日线回测模拟器：
    1. 获取历史数据（分钟级或日线级）
    2. 运行 K 线形态与数值特征引擎
    3. 调用通用回测模拟器，执行带 Regime Router 和高级风控的模拟
    4. 输出交易业绩及对账流水
    """
    print("=" * 70)
    print(f"               QUANT.AI - BACKTEST SIMULATOR (通用回测模拟器)")
    print(f" 股票代码: {ticker} | 周期: {interval} | 区间: {period} | 模式: {strategy_mode} | 仓位管理: {position_sizing_mode}")
    print("=" * 70)
    
    # 1. 抓取与计算全部技术数据
    try:
        df_raw = fetch_and_prepare_data(ticker, period=period, interval=interval)
        df = analyze_patterns(df_raw)
    except Exception as e:
        print(f"数据加载或计算失败: {str(e)}")
        sys.exit(1)
        
    print(f"数据加载成功：常规交易时段共 {len(df)} 根 K 线。")
    print("正在启动模拟引擎...\n")
    
    # 2. 准备回测配置参数
    strategy_params = {
        "strategy_mode": strategy_mode,
        "stop_loss_pct": 0.015,
        "profit_target_pct": 0.030,
        "trailing_stop_mode": "atr",
        "trailing_stop_atr_mult": 2.0,
        "rsi_threshold_buy": 65.0
    }
    
    risk_params = {
        "slippage_rate": 0.0003,
        "commission_per_share": 0.005,
        "min_commission_per_order": 1.0,
        "position_sizing_mode": position_sizing_mode,
        "risk_per_trade_pct": 0.01,
        "max_position_size_pct": MAX_POSITION_SIZE_PCT
    }
    
    is_intraday = interval in ["1m", "5m", "15m", "30m", "1h"]
    
    # 3. 运行回测模拟
    res = run_backtest_sim(df, ticker, strategy_params, risk_params, is_intraday=is_intraday)
    
    # 4. 输出回测统计报告
    print("\n" + "=" * 70)
    print("               QUANT.AI - BACKTEST REPORT (回测统计报告)")
    print("=" * 70)
    print(f" 初始资金:      $ {INITIAL_CASH:,.2f}")
    print(f" 最终资产:      $ {res['final_equity']:,.2f}")
    print(f" 累计盈亏:      $ {res['net_pnl']:+,.2f} ({res['pnl_pct']:+.2f}%)")
    print(f" 最大资产回撤:   {res['max_drawdown']*100:.2f}%")
    print(f" 总交易笔数:    {res['total_trades']} 次 (共 {res['round_trips']} 个平仓交易对)")
    print(f" 策略胜率:      {res['win_rate']:.2f}%")
    print(f" 佣金总支出:    $ {res['commission']:,.2f}")
    print("-" * 70)
    
    # 统计市场状态 (Regime) 分布
    regime_counts = df['Regime'].value_counts()
    print("【市场状态路由占比 (Market Regimes Dist)】:")
    for regime_name, count in regime_counts.items():
        pct = (count / len(df)) * 100
        print(f"  - {regime_name:<16}: {count:>5} 根 K线 ({pct:.2f}%)")
        
    print("-" * 70)
    
    # 打印交易流水账
    ledger = res["ledger"]
    if len(ledger) > 0:
        print("【交易流水明细 (Transaction Ledger)】:")
        for t in ledger:
            pnl_str = f" | 利润: {t['realized_pnl']:+,.2f}" if t['action'] == 'SELL' else ""
            print(f"  {t['timestamp']} | {t['action']} {t['ticker']} | 股数: {t['shares']} | 成交价: ${t['execution_price']:.2f} (市价: ${t['market_price']:.2f}) | 手续费: ${t['commission']:.2f}{pnl_str}")
    else:
        print("【提示】: 回测期间没有触发任何交易信号。系统防仓防守空仓！")
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quant.ai 量化交易回测模拟器")
    parser.add_argument("--ticker", type=str, default="TSLA", help="测试股票代码 (默认: TSLA)")
    parser.add_argument("--period", type=str, default="5d", help="回测区间，支持 1d, 5d, 1mo, 1y 等 (默认: 5d)")
    parser.add_argument("--interval", type=str, default="1m", help="K线周期，支持 1m, 5m, 15m, 1d 等 (默认: 1m)")
    parser.add_argument("--strategy", type=str, default="dynamic", choices=["dynamic", "consensus", "ema_cross", "breakout", "patterns"], help="策略模式 (默认: dynamic)")
    parser.add_argument("--sizing", type=str, default="atr", choices=["atr", "flat"], help="仓位算仓模式 (默认: atr)")
    
    args = parser.parse_args()
    
    # 校验股票是否在池中
    ticker = args.ticker.upper()
    if ticker not in WATCHLIST:
        print(f"[WARNING] 警告：{ticker} 不在预设监控池 {WATCHLIST} 中，将抓取数据测试。")
        
    run_simulation(ticker, period=args.period, interval=args.interval, strategy_mode=args.strategy, position_sizing_mode=args.sizing)
