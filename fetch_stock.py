import yfinance as yf
import pandas as pd
import numpy as np

def calculate_atr(df, period=14):
    """
    计算 ATR (Average True Range) 真实波幅，用来衡量波动率。
    ATR 越高，说明波动越大，适合日内交易。
    """
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    atr = true_range.rolling(window=period).mean()
    return atr

def scan_stocks(tickers):
    """
    模拟交易员开盘前的扫描逻辑：
    1. 相对成交量 (RVol) - 今天交易量是否是过去20天平均成交量的 1.5 倍以上？
    2. 波动率 (ATR % of Price) - 股票的波动性是否够大？
    3. 跳空幅度 (Gap %) - 开盘价相比昨天收盘价跳空了多少？
    """
    print("=" * 60)
    print("   QUANT.AI - PROFESSIONAL DAY TRADER SCANNER (盘前选股器)")
    print("=" * 60)
    print("正在从 Yahoo Finance 获取数据，请稍候...\n")
    
    watchlist = []
    
    for ticker in tickers:
        try:
            # 获取最近 30 天的日线数据
            stock = yf.Ticker(ticker)
            df = stock.history(period="30d")
            
            if df.empty or len(df) < 20:
                continue
                
            # 最新一天的行情数据
            latest_day = df.iloc[-1]
            prev_day = df.iloc[-2]
            
            # 1. 计算相对成交量 (Relative Volume - RVol)
            avg_volume_20d = df['Volume'].iloc[-21:-1].mean()
            latest_volume = latest_day['Volume']
            rvol = latest_volume / avg_volume_20d if avg_volume_20d > 0 else 0
            
            # 2. 计算 ATR (以百分比形式表示，方便横向对比不同股价的股票)
            df['ATR'] = calculate_atr(df, period=14)
            latest_atr = df['ATR'].iloc[-1]
            atr_pct = (latest_atr / latest_day['Close']) * 100 if latest_day['Close'] > 0 else 0
            
            # 3. 计算跳空幅度 (Gap %)
            gap_pct = ((latest_day['Open'] - prev_day['Close']) / prev_day['Close']) * 100
            
            watchlist.append({
                'Ticker': ticker,
                'Price': round(latest_day['Close'], 2),
                'RVol': round(rvol, 2),
                'ATR_%': round(atr_pct, 2),
                'Gap_%': round(gap_pct, 2),
                'Volume_Millions': round(latest_volume / 1_000_000, 2)
            })
            
        except Exception as e:
            print(f"获取 {ticker} 数据失败: {str(e)}")
            
    # 转为 DataFrame 方便处理和展示
    results_df = pd.DataFrame(watchlist)
    
    # 过滤与排序：
    # 1. 过滤：波动率 ATR_% 必须大于 1.5%（波动太小的股我们不做日内）
    # 2. 排序：按 RVol (相对成交量) 降序排列，成交量放大的股票才是热点
    results_df = results_df.sort_values(by='RVol', ascending=False)
    
    print("【候选股票扫描结果列表】:")
    print(results_df.to_string(index=False))
    print("\n" + "-" * 60)
    
    # 选出今天最合适做 Day Trading 的股票
    # 推荐标准：RVol > 1.2 且 ATR_% > 1.5%
    recommended = results_df[(results_df['RVol'] > 1.2) & (results_df['ATR_%'] > 1.5)]
    
    print("【AI 盘前交易推荐】:")
    if not recommended.empty:
        for idx, row in recommended.iterrows():
            print(f"★ 推荐交易 {row['Ticker']}:")
            print(f"  - 理由：今日成交量放大到平时的 {row['RVol']} 倍 (RVol={row['RVol']})，波动率达 {row['ATR_%']}%。")
            print(f"  - 操作策略：根据日内K线走势进行突破或回调买入/做空，单笔最大止损控制在账户的 1%。")
    else:
        # 如果没有符合高波动和高成交量的股票，宁可观望
        top_stock = results_df.iloc[0] if not results_df.empty else None
        print("⚠ 警报：今天市场整体成交量萎缩或波动较低。")
        print("  - 建议：【观望/不交易】。频繁交易将产生巨大的佣金损耗！")
        if top_stock is not None:
            print(f"  - 若强行操作，可关注相对最活跃的 {top_stock['Ticker']} (RVol={top_stock['RVol']})。")
            
    print("=" * 60)

if __name__ == "__main__":
    # 我们扫描 TSLA(特斯拉), NVDA(英伟达), AAPL(苹果), MSFT(微软), AMD(超威半导体) 等大盘股
    popular_stocks = ["TSLA", "NVDA", "AAPL", "MSFT", "AMD"]
    scan_stocks(popular_stocks)
