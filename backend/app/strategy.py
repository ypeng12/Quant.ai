# backend/app/strategy.py

DEFAULT_PARAMS = {
    "stop_loss_pct": 0.01,
    "profit_target_pct": 0.015,
    "trailing_stop_mode": "atr",
    "trailing_stop_atr_mult": 2.0,
    "rsi_threshold_buy": 65.0,
    "strategy_mode": "dynamic"  # dynamic, consensus, ema_cross, breakout, patterns, opening_breakout
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

    # ------------------ 状态1：未持有仓位 (寻找买入机会) ------------------
    if current_shares == 0:
        # A. 动态状态路由过滤 (Regime Router)
        if p["strategy_mode"] == "dynamic":
            if regime == "high_volatility":
                return "HOLD", "【状态路由】市场处于极端高波动状态，执行风控收缩，保持空仓观望。"
            if regime == "trend_down":
                return "HOLD", "【状态路由】市场处于下行趋势，做多风险过大，保持空仓防守。"
        
        # 基础弱势过滤：价格必须在 VWAP 之上（除非是底背离反转模式）
        # 这里保留基本 VWAP 顺势法则，除 Patterns 模式和 Dynamic 震荡模式外，其他模式都需要 close >= vwap
        is_range_bound = (p["strategy_mode"] == "dynamic" and regime == "range_bound")
        if p["strategy_mode"] not in ["patterns", "opening_breakout"] and not is_range_bound and close < vwap:
            return "HOLD", "价格处于 VWAP 下方，属于弱势区间，不建仓。"
            
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

    # 量能与动量确认因子 (Volume & Trend Validation)
    has_volume = rvol >= 1.05 or row.get('Volume', 0) > prev_row.get('Volume', 0)

    # ------------------ 状态1：未持有仓位 (寻找美股多头 BUY 或 融券做空 SHORT) ------------------
    if current_shares == 0:
        # A. 向上做多信号 (多因子共振确认：金叉/突破 + VWAP线上 + 均线多头)
        if is_bullish_trend and close >= vwap:
            if is_gold_cross and has_volume:
                return "BUY", "【美股多头-金叉放量】EMA 9/21 触发金叉，价格站稳 VWAP 上方且量能放大。"
            if donchian_high > 0 and close >= donchian_high and has_volume:
                return "BUY", f"【美股多头-通道突破】股价向上突破唐奇安通道上轨 {donchian_high:.2f} 刀，多头动能确认。"
            if (is_pmh_breakout or is_pdh_breakout) and has_volume:
                return "BUY", "【美股多头-阻力突破】强力突破盘前/前高阻力位，顺势建仓买入。"
            if p["strategy_mode"] == "dynamic" and regime == "trend_up" and is_gold_cross:
                return "BUY", "【美股多头-趋势共振】市场处于上升趋势 Regime，结合 EMA 金叉做多。"

        # B. 向下融券做空信号 (多因子共振确认：死叉/破位 + VWAP线下 + 均线空头)
        if is_bearish_trend and close < vwap:
            if is_death_cross and has_volume:
                return "SHORT", "【美股做空-死叉破位】EMA 9/21 触发死叉，股价跌破日内 VWAP 生命线且抛压放量。"
            if donchian_low > 0 and close <= donchian_low and has_volume:
                return "SHORT", f"【美股做空-支撑破位】股价跌破唐奇安通道下轨 {donchian_low:.2f} 刀，顺势融券做空。"
            if (is_pml_breakdown or is_pdl_breakdown) and has_volume:
                return "SHORT", "【美股做空-关键位破位】跌破盘前/昨日关键支撑位，开启空头行情。"
            if p["strategy_mode"] == "dynamic" and regime == "trend_down" and is_death_cross:
                return "SHORT", "【美股做空-趋势下行】市场处于下行 Regime，顺势融券做空。"

    # ------------------ 状态2：已持有多头仓位 (寻找多单平仓 SELL 机会) ------------------
    elif current_shares > 0:
        pnl_pct = (close - avg_cost) / avg_cost
        
        # 1. 移动追踪止损与百分比止损
        stop_distance = atr * p.get("trailing_stop_atr_mult", 1.5)
        atr_stop_price = highest_price - stop_distance
        if close < atr_stop_price and highest_price > 0:
            return "SELL", f"【多头移动止损】价格自高点 {highest_price:.2f} 回撤超追踪止损位 {atr_stop_price:.2f}。"
            
        if pnl_pct <= -p.get("stop_loss_pct", 0.008):
            return "SELL", f"【多头硬止损】价格触及 -{p.get('stop_loss_pct', 0.008)*100:.1f}% 止损线。"

        # 2. 止盈离场
        if pnl_pct >= p.get("profit_target_pct", 0.012):
            return "SELL", f"【多头止盈】达到 +{p.get('profit_target_pct', 0.012)*100:.1f}% 目标位，锁定多头收益。"
            
        # 3. 死叉与破位反转平仓
        if is_death_cross or close < vwap or pattern_m or pattern_bear_eng:
            return "SELL", "【多头动量反转】均线死叉或跌破 VWAP 生命线，多单平仓。"

    # ------------------ 状态3：已持有空头仓位 (寻找空单平仓 COVER 机会) ------------------
    elif current_shares < 0:
        short_pnl_pct = (avg_cost - close) / avg_cost
        
        # 1. 空头止损 (价格向上反弹)
        if short_pnl_pct <= -p.get("stop_loss_pct", 0.008):
            return "COVER", f"【空头硬止损】价格反弹触及 -{p.get('stop_loss_pct', 0.008)*100:.1f}% 空头止损线，还券平仓。"
            
        # 2. 空头止盈 (价格下行获利)
        if short_pnl_pct >= p.get("profit_target_pct", 0.012):
            return "COVER", f"【空头止盈】达到 +{p.get('profit_target_pct', 0.012)*100:.1f}% 做空收益目标，还券获利。"
            
        # 3. 金叉与站稳 VWAP 反转平空
        if is_gold_cross or close >= vwap or pattern_w or pattern_bull_eng:
            return "COVER", "【空头动量反转】均线金叉或重新站上 VWAP，空单还券平仓。"

    return "HOLD", "保持当前仓位或继续观望。"
