# scratch/test_api.py
import sys
import os

# 将 backend 目录添加到 sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from main_api import run_backtest_api, scan_market_stocks

if __name__ == "__main__":
    print("=== 测试 /api/scan 接口 ===")
    scan_res = scan_market_stocks("TSLA,NVDA")
    print(f"扫描成功: {scan_res['success']}")
    for res in scan_res['results']:
        print(f"  代码: {res['ticker']} | 公司: {res['name']} | RVol: {res['rvol']}x | ATR%: {res['atr_pct']}% | 推荐: {res['recommended']}")

    print("\n=== 测试 /api/backtest 接口 (默认参数) ===")
    bt_res = run_backtest_api(ticker="TSLA", interval="5m")
    print(f"回测成功: {bt_res['success']}")
    if bt_res['success']:
        summary = bt_res['summary']
        print(f"  初始本金: ${summary['initial_cash']}")
        print(f"  期末总值: ${summary['final_equity']}")
        print(f"  盈亏比例: {summary['pnl_pct']}%")
        print(f"  交易笔数: {summary['total_trades']}")
        print(f"  识别到的形态数: {len(bt_res['patterns_log'])}")
        
    print("\n=== 测试 /api/backtest 接口 (自定义参数 + ATR仓位大小) ===")
    bt_custom_res = run_backtest_api(
        ticker="TSLA", 
        interval="15m", 
        strategy_mode="patterns", 
        trailing_stop_mode="atr",
        position_sizing_mode="atr",
        risk_per_trade_pct=0.015
    )
    print(f"回测成功: {bt_custom_res['success']}")
    if bt_custom_res['success']:
        summary = bt_custom_res['summary']
        print(f"  初始本金: ${summary['initial_cash']}")
        print(f"  期末总值: ${summary['final_equity']}")
        print(f"  盈亏比例: {summary['pnl_pct']}%")
        print(f"  交易笔数: {summary['total_trades']}")
        print(f"  识别到的形态数: {len(bt_custom_res['patterns_log'])}")
