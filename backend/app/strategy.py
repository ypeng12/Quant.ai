# backend/app/strategy.py

DEFAULT_PARAMS = {
    "stop_loss_pct": 0.006,       # 0.6% 止损 — 高频日内短线
    "profit_target_pct": 0.008,   # 0.8% 止盈 — 快速锁定收益
    "trailing_stop_mode": "atr",
    "trailing_stop_atr_mult": 1.0,  # 更紧的移动追踪止损
    "rsi_threshold_buy": 72.0,
    "strategy_mode": "dynamic"   # dynamic, consensus, ema_cross, breakout, patterns, opening_breakout
}

def evaluate_market_state(row, prev_row, current_shares, avg_cost, ticker, highest_price=0.0, params=None):
    """
    评估当前 K 线数据，决定交易动作。
    支持自定义参数和多种策略模式：
    - BUY: 满足触发条件，买入做多
    - SELL: 满足止盈、止损、移动追踪止损或破位，卖出平仓
    - HOLD: 无操作
    """
    # 合并默认参数
    p = DEFAULT_PARAMS.copy()
    if params:
        for k, v in params.items():
            if v is not None:
                p[k] = v

    close = row['Close']
    vwap = row['VWAP']
    ema_9 = row['EMA_9']
    ema_21 = row['EMA_21']
    ema_50 = row['EMA_50']
    rsi = row['RSI']
    squeeze = row['Squeeze_On']
    atr = row['ATR']
    
    # 提取昨日及盘前关键位
    pmh = row.get('PMH', 0.0)
    pdh = row.get('PDH', 0.0)
    
    # 提取5分钟开盘突击关键位
    orb_high = row.get('ORB_High', 0.0)
    orb_low = row.get('ORB_Low', 0.0)
    
    # 形态标记 (如果存在)
    pattern_w = row.get('Pattern_W_Bottom', False)
    pattern_m = row.get('Pattern_M_Top', False)
    pattern_hammer = row.get('Pattern_Hammer', False)
    pattern_shooting = row.get('Pattern_Shooting_Star', False)
    pattern_bull_eng = row.get('Pattern_Bullish_Engulfing', False)
    pattern_bear_eng = row.get('Pattern_Bearish_Engulfing', False)
    
    # 新指标与状态分类获取
    regime = row.get('Regime', 'range_bound')
    donchian_high = row.get('Donchian_High', 0.0)
    donchian_low = row.get('Donchian_Low', 0.0)
    rvol = row.get('RVOL', 1.0)

    # ------------------ 状态1：未持有仓位 (寻找做多/做空机会) ------------------
    # 注：已移除严格的 Regime 过滤器，允许双向高频交易信号通过
            
    # 1. 均线与死金叉计算
    prev_ema_9 = prev_row['EMA_9']
    prev_ema_21 = prev_row['EMA_21']
    is_gold_cross = (prev_ema_9 <= prev_ema_21) and (ema_9 > ema_21)
    is_death_cross = (prev_ema_9 >= prev_ema_21) and (ema_9 < ema_21)
    
    is_bullish_trend = (ema_9 > ema_21)
    is_bearish_trend = (ema_9 < ema_21)

    prev_close = prev_row['Close']
    is_pmh_breakout = (prev_close <= pmh) and (close > pmh) and (pmh > 0)
    is_pdh_breakout = (prev_close <= pdh) and (close > pdh) and (pdh > 0)

    pml = row.get('PML', 0.0)
    pdl = row.get('PDL', 0.0)
    is_pml_breakdown = (prev_close >= pml) and (close < pml) and (pml > 0)
    is_pdl_breakdown = (prev_close >= pdl) and (close < pdl) and (pdl > 0)

    # ------------------ 状态1：未持有仓位 (寻找美股多头 BUY 或 融券做空 SHORT) ------------------
    if current_shares == 0:
        # A. 向上做多信号 — 任一条件即可触发 (OR logic，高频优先)
        if is_bullish_trend:
            if is_gold_cross:
                return "BUY", "【高频多头-金叉】EMA 9/21 形成金叉，多头动能启动。"
            if close >= vwap:
                return "BUY", f"【高频多头-VWAP站上】价格站稳 VWAP ({vwap:.2f}) 上方，顺势做多。"
            if donchian_high > 0 and close >= donchian_high:
                return "BUY", f"【高频多头-通道突破】价格突破唐奇安上轨 {donchian_high:.2f}，多头动能。"
            if is_pmh_breakout or is_pdh_breakout:
                return "BUY", "【高频多头-阻力突破】股价突破盘前/昨日高位，顺势买入。"

        # B. 向下融券做空信号 — 任一条件即可触发 (OR logic，高频优先)
        if is_bearish_trend:
            if is_death_cross:
                return "SHORT", "【高频做空-死叉】EMA 9/21 形成死叉，空头动能启动，融券做空。"
            if close < vwap:
                return "SHORT", f"【高频做空-VWAP跌破】价格跌破 VWAP ({vwap:.2f}) 生命线，顺势融券做空。"
            if donchian_low > 0 and close <= donchian_low:
                return "SHORT", f"【高频做空-通道破位】价格跌破唐奇安下轨 {donchian_low:.2f}，空头破位做空。"
            if is_pml_breakdown or is_pdl_breakdown:
                return "SHORT", "【高频做空-支撑破位】股价跌破盘前/昨日关键支撑位，融券做空。"

    # ------------------ 状态2：已持有多头仓位 (寻找多单平仓 SELL 机会) ------------------
    elif current_shares > 0:
        pnl_pct = (close - avg_cost) / avg_cost
        stop_loss = p.get("stop_loss_pct", 0.006)
        profit_target = p.get("profit_target_pct", 0.008)
        
        # 1. 止盈 (优先检查)
        if pnl_pct >= profit_target:
            return "SELL", f"【多头止盈】涨幅达 +{pnl_pct*100:.2f}%，快速锁利平仓。"
        
        # 2. 硬止损
        if pnl_pct <= -stop_loss:
            return "SELL", f"【多头止损】亏损达 -{abs(pnl_pct)*100:.2f}%，止损平仓。"
        
        # 3. ATR 移动追踪止损
        stop_distance = atr * p.get("trailing_stop_atr_mult", 1.0)
        atr_stop_price = highest_price - stop_distance
        if close < atr_stop_price and highest_price > 0:
            return "SELL", f"【多头移动止损】价格自高点 {highest_price:.2f} 回撤触发追踪止损 {atr_stop_price:.2f}。"
        
        # 4. 趋势反转平仓 (死叉或跌破VWAP)
        if is_death_cross or (is_bearish_trend and close < vwap):
            return "SELL", "【多头反转平仓】均线死叉且跌破VWAP，多单止损出场。"

    # ------------------ 状态3：已持有空头仓位 (寻找空单平仓 COVER 机会) ------------------
    elif current_shares < 0:
        short_pnl_pct = (avg_cost - close) / avg_cost
        stop_loss = p.get("stop_loss_pct", 0.006)
        profit_target = p.get("profit_target_pct", 0.008)
        
        # 1. 止盈 (优先检查，顺势下跌获利)
        if short_pnl_pct >= profit_target:
            return "COVER", f"【空头止盈】下跌 {short_pnl_pct*100:.2f}% 达止盈目标，还券获利平仓。"
        
        # 2. 止损 (价格反弹)
        if short_pnl_pct <= -stop_loss:
            return "COVER", f"【空头止损】价格反弹 {abs(short_pnl_pct)*100:.2f}%，空头止损还券平仓。"
        
        # 3. 趋势反转平空 (金叉或重返VWAP)
        if is_gold_cross or (is_bullish_trend and close >= vwap):
            return "COVER", "【空头反转平仓】均线金叉且重返VWAP，空单还券平仓。"

    return "HOLD", "保持当前仓位或继续观望。"
