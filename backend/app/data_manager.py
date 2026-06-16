# backend/app/data_manager.py

import yfinance as yf
import pandas as pd
import numpy as np
import datetime

# 默认时间间隔对应的回测历史区间
INTERVAL_TO_PERIOD = {
    "1m": "5d",
    "5m": "1mo",
    "15m": "1mo",
    "30m": "1mo",
    "1h": "3mo",
    "1d": "1y"
}

# 缓存公司基本信息，避免频繁网络请求导致缓慢
COMPANY_INFO_CACHE = {}

def get_company_info(ticker):
    """
    获取公司名、板块、行业、市值和业务描述，带有缓存与默认兜底，保证极速响应。
    """
    ticker = ticker.upper()
    if ticker in COMPANY_INFO_CACHE:
        return COMPANY_INFO_CACHE[ticker]
        
    # 常用股票静态数据库，优先返回以保证零延迟
    static_db = {
        "TSLA": {
            "name": "Tesla, Inc.",
            "sector": "Consumer Cyclical (消费周期性)",
            "industry": "Auto Manufacturers (汽车制造商)",
            "market_cap": 820000000000,
            "description": "Tesla Inc. 是一家设计、开发、制造和销售电动汽车、能源生成和存储系统的美国跨国公司。它是全球最受关注的高波动率日内交易标的。"
        },
        "NVDA": {
            "name": "NVIDIA Corporation",
            "sector": "Technology (科技)",
            "industry": "Semiconductors (半导体)",
            "market_cap": 3150000000000,
            "description": "NVIDIA Corporation 是一家设计图形处理器（GPU）的半导体跨国科技公司，在人工智能芯片、数据中心和高性能计算领域处于绝对垄断地位。"
        },
        "AAPL": {
            "name": "Apple Inc.",
            "sector": "Technology (科技)",
            "industry": "Consumer Electronics (消费电子)",
            "market_cap": 3320000000000,
            "description": "Apple Inc. 是全球最具价值的电子科技公司，主营 iPhone、Mac、iPad 等消费终端设备以及各种云端订阅软件服务，现金流充裕，波动相对稳健。"
        },
        "MSFT": {
            "name": "Microsoft Corporation",
            "sector": "Technology (科技)",
            "industry": "Software—Infrastructure (基础软件)",
            "market_cap": 3250000000000,
            "description": "Microsoft Corporation 是全球软件与云服务的龙头企业。旗下拥有 Windows 系统、Azure 云平台、Office 软件，并通过 OpenAI 领跑生成式 AI 时代。"
        },
        "AMD": {
            "name": "Advanced Micro Devices, Inc.",
            "sector": "Technology (科技)",
            "industry": "Semiconductors (半导体)",
            "market_cap": 260000000000,
            "description": "Advanced Micro Devices, Inc. 是一家全球半导体公司，主营微处理器（CPU）、显卡（GPU）以及游戏主机定制芯片，与英特尔和英伟达呈竞争关系。"
        }
    }
    
    if ticker in static_db:
        COMPANY_INFO_CACHE[ticker] = static_db[ticker]
        return static_db[ticker]
        
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        name = info.get("longName", info.get("shortName", ticker))
        sector = info.get("sector", "General Sector")
        industry = info.get("industry", "General Industry")
        market_cap = info.get("marketCap", 0)
        description = info.get("longBusinessSummary", "No details available.")
        
        data = {
            "name": name,
            "sector": sector,
            "industry": industry,
            "market_cap": market_cap,
            "description": description
        }
        COMPANY_INFO_CACHE[ticker] = data
        return data
    except Exception as e:
        # 如果 yfinance 接口请求出错/被限制，使用兜底值
        fallback = {
            "name": f"{ticker} Corporation",
            "sector": "General Sector (常规板块)",
            "industry": "General Industry (常规行业)",
            "market_cap": 0,
            "description": f"未能获取到 {ticker} 的网络实时介绍，已自动生成默认档案。该标的目前可参与量化行情回测。"
        }
        COMPANY_INFO_CACHE[ticker] = fallback
        return fallback

def calculate_rsi(series, period=14):
    """
    计算 RSI (相对强弱指标)
    """
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_atr(df, period=14):
    """
    计算 ATR (真实波幅)
    """
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(window=period).mean()

def calculate_adx(df, period=14):
    """
    计算 ADX (平均趋向指数)，衡量趋势强度
    """
    df = df.copy()
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Directional Movement
    up_move = high.diff(1)
    down_move = -low.diff(1)
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    # Smoothed Wilder's MA
    tr_smooth = pd.Series(tr).ewm(alpha=1/period, adjust=False).mean()
    plus_dm_smooth = pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean()
    minus_dm_smooth = pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean()
    
    plus_di = 100 * (plus_dm_smooth / np.maximum(tr_smooth, 1e-8))
    minus_di = 100 * (minus_dm_smooth / np.maximum(tr_smooth, 1e-8))
    
    dx = 100 * (plus_di - minus_di).abs() / np.maximum(plus_di + minus_di, 1e-8)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    
    return plus_di, minus_di, adx

def get_yesterday_levels(ticker):
    """
    获取昨日的最高价(PDH)、最低价(PDL)、收盘价(PDC)
    使用日线级别数据，确保绝对准确
    """
    try:
        stock = yf.Ticker(ticker)
        df_daily = stock.history(period="5d")
        if len(df_daily) >= 2:
            yesterday = df_daily.iloc[-2]  # -1 是今天，-2 是昨天
            return {
                "PDH": float(yesterday['High']),
                "PDL": float(yesterday['Low']),
                "PDC": float(yesterday['Close'])
            }
    except Exception as e:
        print(f"获取昨日关键位置失败 ({ticker}): {str(e)}")
    
    return {"PDH": 0.0, "PDL": 0.0, "PDC": 0.0}

def fetch_and_prepare_data(ticker, period=None, interval="1m"):
    """
    获取股票行情并计算量化指标，支持多时间周期。
    """
    ticker = ticker.upper()
    if period is None:
        period = INTERVAL_TO_PERIOD.get(interval, "5d")
        
    # 抓取包含盘前盘后的 K线数据
    stock = yf.Ticker(ticker)
    
    # 只有分钟级别 (1m, 5m, 15m, 30m, 1h) 支持盘前盘后 prepost
    is_intraday = interval in ["1m", "5m", "15m", "30m", "1h"]
    
    df = stock.history(period=period, interval=interval, prepost=is_intraday)
    
    if df.empty:
        raise ValueError(f"未能获取到 {ticker} 的 {interval} 行情数据。")
        
    # 确保时间戳已转换为本地时区 (美东时间)
    if df.index.tz is None:
        df = df.tz_localize('UTC').tz_convert('US/Eastern')
    else:
        df = df.tz_convert('US/Eastern')
        
    df['Date'] = df.index.date
    
    # 计算 VWAP (日内均线按交易日独立累计，如果是日线级别，VWAP 退化为典型价)
    df['Typical_Price'] = (df['High'] + df['Low'] + df['Close']) / 3
    df['TP_Volume'] = df['Typical_Price'] * df['Volume']
    
    if is_intraday:
        df['Cum_TP_Vol'] = df.groupby('Date')['TP_Volume'].cumsum()
        df['Cum_Vol'] = df.groupby('Date')['Volume'].cumsum()
        # 避免除以 0
        df['Cum_Vol'] = df['Cum_Vol'].replace(0, 1)
        df['VWAP'] = df['Cum_TP_Vol'] / df['Cum_Vol']
    else:
        df['VWAP'] = df['Typical_Price']
        
    # 计算 9 / 21 / 50 EMA 和 RSI
    df['EMA_9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['RSI'] = calculate_rsi(df['Close'], period=14)
    df['ATR'] = calculate_atr(df, period=14)
    
    # 补充指标：ADX, MACD, Donchian, OBV, ROC, RVOL
    df['Plus_DI'], df['Minus_DI'], df['ADX'] = calculate_adx(df, period=14)
    
    # MACD
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    
    # 唐奇安通道
    df['Donchian_High'] = df['High'].rolling(window=20).max()
    df['Donchian_Low'] = df['Low'].rolling(window=20).min()
    df['Donchian_High_55'] = df['High'].rolling(window=55).max()
    df['Donchian_Low_55'] = df['Low'].rolling(window=55).min()
    
    # 能量潮指标 (OBV)
    df['OBV'] = (np.sign(df['Close'].diff()).fillna(0.0) * df['Volume']).cumsum()
    
    # 动量 ROC
    df['ROC'] = df['Close'].pct_change(periods=20) * 100
    
    # 相对成交量 RVOL
    df['RVOL'] = df['Volume'] / np.maximum(df['Volume'].rolling(window=20).mean(), 1e-8)
    
    # 计算 TTM Squeeze 挤压状态
    df['BB_Basis'] = df['Close'].rolling(window=20).mean()
    df['BB_Std'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Basis'] + (2 * df['BB_Std'])
    df['BB_Lower'] = df['BB_Basis'] - (2 * df['BB_Std'])
    
    # 肯特纳通道 (标准：基于 20 EMA 和 2.0 ATR)
    df['KC_Basis'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['KC_Upper'] = df['KC_Basis'] + (2.0 * df['ATR'])
    df['KC_Lower'] = df['KC_Basis'] - (2.0 * df['ATR'])
    
    df['Squeeze_On'] = (df['BB_Upper'] < df['KC_Upper']) & (df['BB_Lower'] > df['KC_Lower'])
    
    # 状态路由判定 (Regime Classification)
    df['ATR_Ratio'] = df['ATR'] / df['Close']
    high_vol_th = df['ATR_Ratio'].rolling(252, min_periods=20).quantile(0.90).fillna(0.05)
    
    regimes = np.array(["range_bound"] * len(df), dtype=object)
    
    is_high_vol = df['ATR_Ratio'] > high_vol_th
    is_trend_up = (df['ADX'] > 20) & (df['EMA_9'] > df['EMA_21']) & (df['EMA_21'] > df['EMA_50'])
    is_trend_down = (df['ADX'] > 20) & (df['EMA_9'] < df['EMA_21']) & (df['EMA_21'] < df['EMA_50'])
    
    # 优先级别：高波动 -> 下跌趋势 -> 上涨趋势 -> 震荡
    regimes[is_trend_down] = "trend_down"
    regimes[is_trend_up] = "trend_up"
    regimes[is_high_vol] = "high_volatility"
    
    df['Regime'] = regimes
    
    # 盘前与昨日关键位
    if is_intraday:
        df['Time'] = df.index.time
        market_open = datetime.time(9, 30)
        market_close = datetime.time(16, 0)
        
        df['Is_Regular_Hours'] = df['Time'].apply(lambda t: market_open <= t <= market_close)
        df['Is_Pre_Market'] = df['Time'].apply(lambda t: datetime.time(4, 0) <= t < market_open)
        
        # 每日计算 PMH / PML 盘前最值
        pm_data = df[df['Is_Pre_Market']]
        if not pm_data.empty:
            pmh_dict = pm_data.groupby('Date')['High'].max().to_dict()
            pml_dict = pm_data.groupby('Date')['Low'].min().to_dict()
            df['PMH'] = df['Date'].map(pmh_dict).fillna(0.0)
            df['PML'] = df['Date'].map(pml_dict).fillna(0.0)
        else:
            df['PMH'] = 0.0
            df['PML'] = 0.0
            
        regular_hours_df = df[df['Is_Regular_Hours']].copy()
    else:
        # 日线级别数据全部视为常规时段
        regular_hours_df = df.copy()
        regular_hours_df['Is_Regular_Hours'] = True
        regular_hours_df['Is_Pre_Market'] = False
        regular_hours_df['PMH'] = 0.0
        regular_hours_df['PML'] = 0.0
        
    # 获取昨日关键位
    yesterday_levels = get_yesterday_levels(ticker)
    regular_hours_df['PDH'] = yesterday_levels['PDH']
    regular_hours_df['PDL'] = yesterday_levels['PDL']
    regular_hours_df['PDC'] = yesterday_levels['PDC']
    
    # 清除临时列
    regular_hours_df.drop(columns=['Typical_Price', 'TP_Volume', 'Cum_TP_Vol', 'Cum_Vol'], inplace=True, errors='ignore')
    
    # 填充缺失值，避免初期的 NaN 导致崩溃
    regular_hours_df.ffill(inplace=True)
    regular_hours_df.bfill(inplace=True)
    
    return regular_hours_df

if __name__ == "__main__":
    print("测试多周期获取数据...")
    for iv in ["5m", "1d"]:
        data = fetch_and_prepare_data("AAPL", interval=iv)
        print(f"周期 {iv}: 获取到 {len(data)} 行数据")
        info = get_company_info("AAPL")
        print(f"公司名: {info['name']}, 行业: {info['industry']}")
