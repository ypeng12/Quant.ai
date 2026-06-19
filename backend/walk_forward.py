# backend/walk_forward.py

import argparse
import sys
import pandas as pd
import numpy as np
import os

# 确保 backend 目录在 sys.path 中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.data_manager import fetch_and_prepare_data
from app.patterns import analyze_patterns
from app.simulator import run_backtest_sim

def walk_forward_optimization(ticker, interval="1d", period="2y", train_size=120, test_size=40):
    """
    运行滚动优化回测 (Walk-forward rolling optimization)
    - 使用 train_size 根 K线作为训练集寻找最佳参数组合
    - 在随后的 test_size 根 K线中作为样本外测试执行该参数组合
    - 滚动前进，直到覆盖所有行情数据
    """
    print("=" * 80)
    print(f"             QUONT.AI - WALK-FORWARD OPTIMIZER (滚动参数优化引擎)")
    print(f" 标的代码: {ticker} | 周期: {interval} | 区间: {period} | 训练集大小: {train_size} | 测试集大小: {test_size}")
    print("=" * 80)
    
    # 1. 抓取与清洗指标数据
    try:
        df_raw = fetch_and_prepare_data(ticker, period=period, interval=interval)
        df = analyze_patterns(df_raw)
    except Exception as e:
        raise ValueError(f"数据加载或指标计算失败: {str(e)}")
        
    total_len = len(df)
    if total_len < (train_size + test_size):
        raise ValueError(f"错误：历史数据共 {total_len} 根 Bar，不足以支持当前 Train({train_size}) + Test({test_size}) 的滚动窗口分配！")
        
    print(f"行情数据准备就绪：共包含 {total_len} 根 K 线。")
    print("正在生成参数搜索网格...")
    
    # 2. 定义参数网格
    param_grid = []
    for mode in ["dynamic", "consensus"]:
        for atr_mult in [1.5, 2.0, 2.5]:
            for rsi_th in [60.0, 65.0, 70.0]:
                param_grid.append({
                    "strategy_mode": mode,
                    "trailing_stop_atr_mult": atr_mult,
                    "rsi_threshold_buy": rsi_th,
                    "stop_loss_pct": 0.015,
                    "profit_target_pct": 0.030
                })
                
    risk_params = {
        "slippage_rate": 0.0003,
        "commission_per_share": 0.005,
        "min_commission_per_order": 1.0,
        "position_sizing_mode": "atr",
        "risk_per_trade_pct": 0.01,
        "max_position_size_pct": 0.50
    }
    
    # 3. 滚动窗口优化循环
    start_idx = 0
    oos_results = []
    
    is_intraday = interval in ["1m", "5m", "15m", "30m", "1h"]
    
    print("\n[开始滚动优化]")
    window_count = 1
    
    while start_idx + train_size + test_size <= total_len:
        train_df = df.iloc[start_idx : start_idx + train_size]
        test_df = df.iloc[start_idx + train_size : start_idx + train_size + test_size]
        
        train_start_date = train_df.index[0].strftime("%Y-%m-%d")
        train_end_date = train_df.index[-1].strftime("%Y-%m-%d")
        test_start_date = test_df.index[0].strftime("%Y-%m-%d")
        test_end_date = test_df.index[-1].strftime("%Y-%m-%d")
        
        # 寻找训练集上的最佳参数
        best_score = -999999.0
        best_params = None
        
        for params in param_grid:
            res = run_backtest_sim(train_df, ticker, params, risk_params, is_intraday=is_intraday)
            # 目标函数：净亏损惩罚下的净利润收益 (Sharpe-like Objective)
            score = res["net_pnl"] - (res["max_drawdown"] * 30000.0 * 2.0)
            if score > best_score:
                best_score = score
                best_params = params
                
        # 使用最佳参数在测试集上回测（样本外测试）
        test_res = run_backtest_sim(test_df, ticker, best_params, risk_params, is_intraday=is_intraday)
        
        print(f" 窗口 #{window_count} | 训练集: {train_start_date} ~ {train_end_date} | 测试集: {test_start_date} ~ {test_end_date}")
        print(f"   -> 最佳参数: Mode={best_params['strategy_mode']}, ATR_Mult={best_params['trailing_stop_atr_mult']}, RSI={best_params['rsi_threshold_buy']}")
        print(f"   -> 样本外表现: 盈亏 ${test_res['net_pnl']:+,.2f} | 最大回撤 {test_res['max_drawdown']*100:.2f}% | 交易对数 {test_res['round_trips']} | 胜率 {test_res['win_rate']}%")
        
        oos_results.append({
            "window": window_count,
            "train_period": f"{train_start_date} ~ {train_end_date}",
            "test_period": f"{test_start_date} ~ {test_end_date}",
            "best_params": best_params,
            "net_pnl": test_res["net_pnl"],
            "max_drawdown": test_res["max_drawdown"],
            "round_trips": test_res["round_trips"],
            "win_rate": test_res["win_rate"],
            "commission": test_res["commission"]
        })
        
        # 前进一个测试集步长
        start_idx += test_size
        window_count += 1

    # 4. 对照组：在整个数据集上运行静态默认参数
    default_params = {
        "strategy_mode": "dynamic",
        "trailing_stop_atr_mult": 2.0,
        "rsi_threshold_buy": 65.0,
        "stop_loss_pct": 0.015,
        "profit_target_pct": 0.030
    }
    static_res = run_backtest_sim(df, ticker, default_params, risk_params, is_intraday=is_intraday)

    # 5. 汇总 Walk-forward 表现
    total_wf_pnl = sum(r["net_pnl"] for r in oos_results)
    total_wf_commission = sum(r["commission"] for r in oos_results)
    avg_wf_drawdown = float(np.mean([r["max_drawdown"] for r in oos_results])) if oos_results else 0.0
    total_wf_trades = sum(r["round_trips"] for r in oos_results)
    
    print("\n" + "=" * 80)
    print("               WALK-FORWARD PERFORMANCE VS STATIC CONTROL")
    print("=" * 80)
    print(f" 【滚动参数优化 (Walk-Forward) 样本外表现】：")
    print(f"   - 累计样本外净利润:  $ {total_wf_pnl:+,.2f}")
    print(f"   - 总交易笔数(对):   {total_wf_trades} 笔")
    print(f"   - 佣金支出总计:     $ {total_wf_commission:,.2f}")
    print(f"   - 平均滚动最大回撤:  {avg_wf_drawdown*100:.2f}%")
    print("-" * 80)
    print(f" 【静态默认参数 (Static Default) 全样本对照组表现】：")
    print(f"   - 累计净利润:       $ {static_res['net_pnl']:+,.2f} ({static_res['pnl_pct']:+.2f}%)")
    print(f"   - 总交易笔数(对):   {static_res['round_trips']} 笔")
    print(f"   - 佣金支出总计:     $ {static_res['commission']:,.2f}")
    print(f"   - 全历史最大回撤:    {static_res['max_drawdown']*100:.2f}%")
    print("=" * 80)

    return {
        "ticker": ticker,
        "interval": interval,
        "period": period or "1y",
        "train_size": train_size,
        "test_size": test_size,
        "oos_results": oos_results,
        "static_control": {
            "net_pnl": static_res["net_pnl"],
            "pnl_pct": static_res["pnl_pct"],
            "round_trips": static_res["round_trips"],
            "commission": static_res["commission"],
            "max_drawdown": static_res["max_drawdown"]
        },
        "summary": {
            "total_wf_pnl": total_wf_pnl,
            "total_wf_commission": total_wf_commission,
            "avg_wf_drawdown": avg_wf_drawdown,
            "total_wf_trades": total_wf_trades
        }
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Walk-Forward Rolling Parameter Optimizer")
    parser.add_argument("--ticker", type=str, default="TSLA", help="测试股票代码 (默认: TSLA)")
    parser.add_argument("--interval", type=str, default="1d", help="K线周期 (默认: 1d)")
    parser.add_argument("--period", type=str, default="1y", help="总历史时间段 (默认: 1y)")
    parser.add_argument("--train", type=int, default=120, help="训练集 K线根数 (默认: 120)")
    parser.add_argument("--test", type=int, default=40, help="测试集 K线根数 (默认: 40)")
    
    args = parser.parse_args()
    try:
        walk_forward_optimization(args.ticker, args.interval, args.period, args.train, args.test)
    except Exception as e:
        print(e)
        sys.exit(1)
