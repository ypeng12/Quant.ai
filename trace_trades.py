# trace_trades.py

import pandas as pd
from backend.app.data_manager import fetch_and_prepare_data

def trace_execution_details(ticker, period="5d"):
    """
    专门提取交易发生瞬间前后几分钟的原始数据和技术指标，
    向用户解释“量化公式在后台是如何具体运行的”。
    """
    print("=" * 80)
    print(f"               QUANT.AI - DATA TRACE VIEW (交易底层数据透视)")
    print("=" * 80)
    
    # 1. 抓取与计算全部技术数据
    df = fetch_and_prepare_data(ticker, period=period)
    
    # 我们要追踪的几个核心时刻
    trade_moments = [
        # 1. 2026-06-08 突破交易进入点 (10:00 前后)
        {"date": "2026-06-08", "start": "09:56", "end": "10:02", "label": "[06-08 盘前高点突破买入点]"},
        # 2. 2026-06-08 均线死退平仓点 (11:08 前后)
        {"date": "2026-06-08", "start": "11:08", "end": "11:12", "label": "[06-08 9/21均线死叉平仓点]"},
        # 3. 2026-06-09 抖动平仓点 (09:48 前后)
        {"date": "2026-06-09", "start": "09:49", "end": "09:53", "label": "[06-09 跌破VWAP瞬间（噪声伤害）]"}
    ]
    
    # 遍历要追踪的时刻
    for moment in trade_moments:
        print(f"\n[TRACE] {moment['label']} (时间范围: {moment['date']} {moment['start']} ~ {moment['end']})")
        print("-" * 80)
        
        # 过滤对应时间段的数据
        date_mask = df.index.strftime("%Y-%m-%d") == moment['date']
        time_mask = (df.index.strftime("%H:%M") >= moment['start']) & (df.index.strftime("%H:%M") <= moment['end'])
        subset = df[date_mask & time_mask].copy()
        
        if subset.empty:
            print("  没有在该时段内找到有效常规交易时段数据。")
            continue
            
        # 挑选我们要透视的核心量化参数
        columns_to_show = ['Close', 'VWAP', 'EMA_9', 'EMA_21', 'EMA_50', 'RSI', 'PMH']
        display_df = subset[columns_to_show].copy()
        
        # 打印输出表格
        print(display_df.to_string())
        
        # 解释触发原理
        if "06-08 盘前高点突破" in moment['label']:
            print("\n  [数据分析]：")
            print("  1. 注意看 09:59 到 10:00：Close 股价从 401.07 飙升至 401.72，强势突破了 PMH（盘前最高价 401.28）。")
            print("  2. 此时 EMA_9 (400.88) > EMA_21 (400.04) > EMA_50 (399.47)，三线呈多头姿态排列。")
            print("  3. 股价 Close (401.72) 在生命线 VWAP (398.70) 上方运行。符合全部买入法则，因此在 10:00 准时打入买单。")
            
        elif "06-08 9/21均线死叉" in moment['label']:
            print("\n  [数据分析]：")
            print("  1. 注意看 11:09 到 11:10 的 EMA 变化。")
            print("  2. 在 11:09：EMA_9 (403.25) 还略微大于 EMA_21 (403.23)；")
            print("  3. 到了 11:10：价格回落，EMA_9 变成了 403.20，跌破了 EMA_21 (403.22)，形成死叉。")
            print("  4. 策略迅速识别到动能衰竭，于是在 11:10 立刻以收盘价市价平仓，成功锁定利润。")
            
        elif "06-09 跌破VWAP" in moment['label']:
            print("\n  [数据分析]：")
            print("  1. 09:50：股价 Close (414.99) 回调到 VWAP (414.17) 附近支撑，且 9/21 均线发生金叉 (414.65 > 414.61)，系统触发买入。")
            print("  2. 09:51：下一分钟，股价 Close 回落至 412.03，瞬间跌破了当时的 VWAP 线 (414.17)。")
            print("  3. 策略硬性规则 close < vwap 被触发，系统在 09:51 结束时立刻以 412.03 强行止损。")
            print("  4. 实际上这只是极短线震荡，我们如果加了缓冲止损，就能避免被这一分钟的杂音洗出局。")
            
        print("=" * 80)

if __name__ == "__main__":
    trace_execution_details("TSLA", period="5d")
