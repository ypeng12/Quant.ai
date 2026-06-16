# backend/app/patterns.py

import pandas as pd
import numpy as np

def detect_candlestick_patterns(df):
    """
    检测 K 线数值特征与 22 种 K 线及形态模式：
    - Feature Columns:
      'range', 'body', 'body_ratio', 'upper_shadow', 'lower_shadow',
      'upper_ratio', 'lower_ratio', 'gap_up', 'gap_down',
      'trend_up_ctx', 'trend_down_ctx', 'rv'
    
    - Pattern Columns:
      'Pattern_Long_Bull', 'Pattern_Long_Bear', 'Pattern_Doji', 'Pattern_Hammer',
      'Pattern_Hanging_Man', 'Pattern_Inverted_Hammer', 'Pattern_Shooting_Star',
      'Pattern_Marubozu', 'Pattern_Spinning_Top', 'Pattern_Bullish_Engulfing',
      'Pattern_Bearish_Engulfing', 'Pattern_Piercing', 'Pattern_Dark_Cloud_Cover',
      'Pattern_Harami', 'Pattern_Morning_Star', 'Pattern_Evening_Star',
      'Pattern_Three_White_Soldiers', 'Pattern_Three_Black_Crows',
      'Pattern_Rising_Three_Methods', 'Pattern_Falling_Three_Methods',
      'Pattern_Gap_Breakout', 'Pattern_Exhaustion_Gap'
    """
    df = df.copy()
    
    # 避免行数太少报错
    if len(df) < 5:
        # 填充默认的列
        for col in [
            'range', 'body', 'body_ratio', 'upper_shadow', 'lower_shadow',
            'upper_ratio', 'lower_ratio', 'gap_up', 'gap_down',
            'trend_up_ctx', 'trend_down_ctx', 'rv',
            'Pattern_Long_Bull', 'Pattern_Long_Bear', 'Pattern_Doji', 'Pattern_Hammer',
            'Pattern_Hanging_Man', 'Pattern_Inverted_Hammer', 'Pattern_Shooting_Star',
            'Pattern_Marubozu', 'Pattern_Spinning_Top', 'Pattern_Bullish_Engulfing',
            'Pattern_Bearish_Engulfing', 'Pattern_Piercing', 'Pattern_Dark_Cloud_Cover',
            'Pattern_Harami', 'Pattern_Morning_Star', 'Pattern_Evening_Star',
            'Pattern_Three_White_Soldiers', 'Pattern_Three_Black_Crows',
            'Pattern_Rising_Three_Methods', 'Pattern_Falling_Three_Methods',
            'Pattern_Gap_Breakout', 'Pattern_Exhaustion_Gap'
        ]:
            df[col] = False
        return df

    o = df['Open']
    h = df['High']
    l = df['Low']
    c = df['Close']
    v = df['Volume']
    
    eps = 1e-8
    
    # 1. 计算基础数值特征
    df['range'] = h - l
    df['body'] = (c - o).abs()
    df['body_ratio'] = df['body'] / np.maximum(df['range'], eps)
    df['upper_shadow'] = h - np.maximum(o, c)
    df['lower_shadow'] = np.minimum(o, c) - l
    df['upper_ratio'] = df['upper_shadow'] / np.maximum(df['body'], eps)
    df['lower_ratio'] = df['lower_shadow'] / np.maximum(df['body'], eps)
    df['gap_up'] = l > h.shift(1)
    df['gap_down'] = h < l.shift(1)
    
    # 计算趋势上下文 (20日/分钟 EMA vs 50日/分钟 EMA)
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    
    # slope(ema20, 5) using 5-period linear regression slope
    slope_ema20 = (2 * ema20 + ema20.shift(1) - ema20.shift(3) - 2 * ema20.shift(4)) / 10.0
    
    df['trend_up_ctx'] = (ema20 > ema50) & (slope_ema20 > 0)
    df['trend_down_ctx'] = (ema20 < ema50) & (slope_ema20 < 0)
    
    # rv (Relative Volume)
    df['rv'] = v / np.maximum(v.rolling(window=20, min_periods=1).mean(), eps)

    # 快捷变量，方便编写条件
    bull = c > o
    bear = c < o
    body_ratio = df['body_ratio']
    upper_ratio = df['upper_ratio']
    lower_ratio = df['lower_ratio']
    trend_up_ctx = df['trend_up_ctx']
    trend_down_ctx = df['trend_down_ctx']
    gap_up = df['gap_up']
    gap_down = df['gap_down']
    rv = df['rv']
    
    # 2. 单K线与常规形态识别
    df['Pattern_Long_Bull'] = bull & (body_ratio >= 0.6) & (upper_ratio <= 0.3) & (lower_ratio <= 0.3)
    df['Pattern_Long_Bear'] = bear & (body_ratio >= 0.6) & (upper_ratio <= 0.3) & (lower_ratio <= 0.3)
    df['Pattern_Doji'] = body_ratio <= 0.1
    df['Pattern_Hammer'] = (lower_ratio >= 2.0) & (upper_ratio <= 0.5) & (body_ratio <= 0.35) & trend_down_ctx
    df['Pattern_Hanging_Man'] = (lower_ratio >= 2.0) & (upper_ratio <= 0.5) & (body_ratio <= 0.35) & trend_up_ctx
    df['Pattern_Inverted_Hammer'] = (upper_ratio >= 2.0) & (lower_ratio <= 0.5) & (body_ratio <= 0.35) & trend_down_ctx
    df['Pattern_Shooting_Star'] = (upper_ratio >= 2.0) & (lower_ratio <= 0.5) & (body_ratio <= 0.35) & trend_up_ctx
    df['Pattern_Marubozu'] = (body_ratio >= 0.8) & (upper_ratio <= 0.1) & (lower_ratio <= 0.1)
    df['Pattern_Spinning_Top'] = (body_ratio > 0.1) & (body_ratio < 0.35) & (upper_ratio > 0.5) & (lower_ratio > 0.5)
    
    # 3. 双K线形态识别
    prev_close = c.shift(1)
    prev_open = o.shift(1)
    
    df['Pattern_Bullish_Engulfing'] = (prev_close < prev_open) & bull & (o <= prev_close) & (c >= prev_open)
    df['Pattern_Bearish_Engulfing'] = (prev_close > prev_open) & bear & (o >= prev_close) & (c <= prev_open)
    
    prev_mid = (prev_open + prev_close) / 2
    df['Pattern_Piercing'] = (prev_close < prev_open) & bull & (o < prev_close) & (c >= prev_mid) & (c < prev_open)
    df['Pattern_Dark_Cloud_Cover'] = (prev_close > prev_open) & bear & (o > prev_close) & (c <= prev_mid) & (c > prev_open)
    
    curr_body_high = np.maximum(o, c)
    curr_body_low = np.minimum(o, c)
    prev_body_high = np.maximum(prev_open, prev_close)
    prev_body_low = np.minimum(prev_open, prev_close)
    df['Pattern_Harami'] = (curr_body_low >= prev_body_low) & (curr_body_high <= prev_body_high)
    
    # 4. 三日及多日形态识别
    # shift values for Day 1 (t-2) and Day 2 (t-1)
    b1_open, b1_close = o.shift(2), c.shift(2)
    b1_body = df['body'].shift(2)
    b1_range = df['range'].shift(2)
    b1_body_ratio = b1_body / np.maximum(b1_range, eps)
    b1_bear = b1_close < b1_open
    b1_bull = b1_close > b1_open
    
    b2_open, b2_close = o.shift(1), c.shift(1)
    b2_body = df['body'].shift(1)
    b2_range = df['range'].shift(1)
    b2_body_ratio = b2_body / np.maximum(b2_range, eps)
    
    # 启明星
    first_big_down = b1_bear & (b1_body_ratio >= 0.6)
    second_small = b2_body_ratio <= 0.25
    third_big_up = bull & (body_ratio >= 0.6)
    reclaim = c >= (b1_open + b1_close) / 2
    df['Pattern_Morning_Star'] = first_big_down & second_small & third_big_up & reclaim
    
    # 黄昏星
    first_big_up = b1_bull & (b1_body_ratio >= 0.6)
    third_big_down = bear & (body_ratio >= 0.6)
    decline = c <= (b1_open + b1_close) / 2
    df['Pattern_Evening_Star'] = first_big_up & second_small & third_big_down & decline
    
    # 红三兵
    df['Pattern_Three_White_Soldiers'] = (
        b1_bull & (b2_close > b2_open) & bull &
        (c > b2_close) & (b2_close > b1_close) &
        (b2_open >= b1_open) & (b2_open <= b1_close) &
        (o >= b2_open) & (o <= b2_close)
    )
    
    # 三只乌鸦
    df['Pattern_Three_Black_Crows'] = (
        b1_bear & (b2_close < b2_open) & bear &
        (c < b2_close) & (b2_close < b1_close) &
        (b2_open <= b1_open) & (b2_open >= b1_close) &
        (o <= b2_open) & (o >= b2_close)
    )
    
    # 上升三法 / 下降三法 (5日模式)
    c4, o4, h4, l4 = c.shift(4), o.shift(4), h.shift(4), l.shift(4)
    c3, o3, h3, l3 = c.shift(3), o.shift(3), h.shift(3), l.shift(3)
    c2, o2, h2, l2 = c.shift(2), o.shift(2), h.shift(2), l.shift(2)
    c1, o1, h1, l1 = c.shift(1), o.shift(1), h.shift(1), l.shift(1)
    
    # 上升三法
    day1_up = (c4 > o4) & ((c4 - o4) / np.maximum(h4 - l4, eps) >= 0.5)
    day234_inside_up = (
        (l3 > l4) & (h3 < h4) & (abs(c3-o3) < (c4-o4)*0.5) &
        (l2 > l4) & (h2 < h4) & (abs(c2-o2) < (c4-o4)*0.5) &
        (l1 > l4) & (h1 < h4) & (abs(c1-o1) < (c4-o4)*0.5)
    )
    day5_up = (c > o) & (c > c4) & ((c - o) / np.maximum(h - l, eps) >= 0.5)
    df['Pattern_Rising_Three_Methods'] = day1_up & day234_inside_up & day5_up
    
    # 下降三法
    day1_dn = (c4 < o4) & ((o4 - c4) / np.maximum(h4 - l4, eps) >= 0.5)
    day234_inside_dn = (
        (l3 > l4) & (h3 < h4) & (abs(c3-o3) < (o4-c4)*0.5) &
        (l2 > l4) & (h2 < h4) & (abs(c2-o2) < (o4-c4)*0.5) &
        (l1 > l4) & (h1 < h4) & (abs(c1-o1) < (o4-c4)*0.5)
    )
    day5_dn = (c < o) & (c < c4) & ((o - c) / np.maximum(h - l, eps) >= 0.5)
    df['Pattern_Falling_Three_Methods'] = day1_dn & day234_inside_dn & day5_dn
    
    # 5. 缺口与突破模式
    df['Pattern_Gap_Breakout'] = gap_up & (rv >= 1.5) & trend_up_ctx
    df['Pattern_Exhaustion_Gap'] = (gap_up & (rv >= 1.5) & bear) | (gap_down & (rv >= 1.5) & bull)

    return df

def detect_double_tops_bottoms(df, window=5, threshold=0.015):
    """
    检测 M顶 (Double Top) 与 W底 (Double Bottom)
    
    参数:
    - window: 局部最高/最低点寻找的窗口宽度
    - threshold: 两个波峰/波谷价格差异的百分比上限 (默认 1.5%)
    
    返回:
    - 'Pattern_M_Top': bool (在颈线跌破点标记为 True)
    - 'Pattern_W_Bottom': bool (在颈线突破点标记为 True)
    - 'M_Neckline': float (记录颈线价格，没有则为 NaN)
    - 'W_Neckline': float (记录颈线价格，没有则为 NaN)
    """
    df = df.copy()
    df['Pattern_M_Top'] = False
    df['Pattern_W_Bottom'] = False
    df['M_Neckline'] = np.nan
    df['W_Neckline'] = np.nan
    
    if len(df) < window * 4:
        return df
        
    close = df['Close'].values
    high = df['High'].values
    low = df['Low'].values
    
    # 1. 寻找局部波峰(Peaks)与波谷(Troughs)
    peaks = []  # 元素格式: (index, price)
    troughs = [] # 元素格式: (index, price)
    
    for i in range(window, len(df) - window):
        # 局部高点判定
        is_peak = True
        for w in range(1, window + 1):
            if high[i] < high[i-w] or high[i] < high[i+w]:
                is_peak = False
                break
        if is_peak:
            peaks.append((i, float(high[i])))
            
        # 局部低点判定
        is_trough = True
        for w in range(1, window + 1):
            if low[i] > low[i-w] or low[i] > low[i+w]:
                is_trough = False
                break
        if is_trough:
            troughs.append((i, float(low[i])))

    # 2. 识别 M 顶 (双顶)
    # 两峰 P1(t1) 与 P2(t2)，中间夹着一谷 T(t_mid)
    # 颈线为 T 的最低价。当价格跌破颈线时，确认 M 顶。
    for p_idx in range(len(peaks) - 1):
        t1, p1 = peaks[p_idx]
        t2, p2 = peaks[p_idx + 1]
        
        # 两个峰高度相差在阈值内
        if abs(p1 - p2) / max(p1, p2) <= threshold:
            # 寻找两个峰之间的最低点(谷底)
            t_mid_candidates = [t for t in troughs if t1 < t[0] < t2]
            if t_mid_candidates:
                # 颈线点取两峰之间最低的那个谷底值
                t_neck, p_neck = min(t_mid_candidates, key=lambda x: x[1])
                
                # 寻找 t2 之后，价格首次跌破 p_neck 的时刻
                # 为防止在历史中过早标出，我们检查 t2 之后的收盘价
                for i in range(t2, len(df)):
                    # 如果中间价格又向上突破了双顶最高价，则该形态失效
                    limit_high = max(p1, p2) * 1.01
                    if close[i] > limit_high:
                        break
                    # 如果跌破颈线
                    if close[i] < p_neck:
                        # 只在跌破的那一分钟标记 True
                        df.iloc[i, df.columns.get_loc('Pattern_M_Top')] = True
                        df.iloc[i, df.columns.get_loc('M_Neckline')] = p_neck
                        break

    # 3. 识别 W 底 (双底)
    # 两谷 T1(t1) 与 T2(t2)，中间夹着一峰 P(t_mid)
    # 颈线为 P 的最高价。当价格突破颈线时，确认 W 底。
    for t_idx in range(len(troughs) - 1):
        t1, tr1 = troughs[t_idx]
        t2, tr2 = troughs[t_idx + 1]
        
        # 两个谷底相差在阈值内
        if abs(tr1 - tr2) / max(tr1, tr2) <= threshold:
            # 寻找两个谷之间的最高点(峰顶)
            p_mid_candidates = [p for p in peaks if t1 < p[0] < t2]
            if p_mid_candidates:
                t_neck, p_neck = max(p_mid_candidates, key=lambda x: x[1])
                
                # 寻找 t2 之后，价格首次突破 p_neck 的时刻
                for i in range(t2, len(df)):
                    # 如果中间价格跌破了双底最低价，则形态失效
                    limit_low = min(tr1, tr2) * 0.99
                    if close[i] < limit_low:
                        break
                    # 如果突破颈线
                    if close[i] > p_neck:
                        df.iloc[i, df.columns.get_loc('Pattern_W_Bottom')] = True
                        df.iloc[i, df.columns.get_loc('W_Neckline')] = p_neck
                        break
                        
    return df

def analyze_patterns(df):
    """
    一键运行所有形态检测，合并返回
    """
    df = detect_candlestick_patterns(df)
    df = detect_double_tops_bottoms(df)
    return df

if __name__ == "__main__":
    print("Testing patterns.py...")
    # Create a dummy dataframe with OHLCV data
    dates = pd.date_range("2026-06-01", periods=10)
    data = {
        "Open": [100.0, 102.0, 101.0, 105.0, 104.0, 106.0, 107.0, 105.0, 108.0, 110.0],
        "High": [103.0, 104.0, 102.0, 106.0, 105.0, 107.0, 108.0, 106.0, 109.0, 112.0],
        "Low": [99.0, 101.0, 100.0, 104.0, 103.0, 105.0, 106.0, 104.0, 107.0, 109.0],
        "Close": [102.0, 101.5, 101.8, 104.5, 104.2, 106.8, 105.5, 104.8, 108.5, 111.0],
        "Volume": [1000, 1500, 1200, 2000, 1100, 1300, 900, 1400, 2200, 3000]
    }
    df_test = pd.DataFrame(data, index=dates)
    res = analyze_patterns(df_test)
    print("Columns in result:", res.columns.tolist())
    print("\nFirst row features:\n", res.iloc[-1])
