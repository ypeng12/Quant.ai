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
            
        # 1. 均线多头排列
        is_bullish_trend = (ema_9 > ema_21) and (ema_21 > ema_50)
        
        # 2. 均线金叉 (EMA_9 穿过 EMA_21)
        prev_ema_9 = prev_row['EMA_9']
        prev_ema_21 = prev_row['EMA_21']
        is_gold_cross = (prev_ema_9 <= prev_ema_21) and (ema_9 > ema_21)
        
        # 3. 突破盘前/昨日最高点
        prev_close = prev_row['Close']
        is_pmh_breakout = (prev_close <= pmh) and (close > pmh) and (pmh > 0)
        is_pdh_breakout = (prev_close <= pdh) and (close > pdh) and (pdh > 0)
        
        # 4. 回调到 VWAP 支撑区 (0.2% 范围内)
        is_near_vwap_support = abs(close - vwap) / vwap <= 0.002
        
        # 5. 静态过滤 (仅在非 dynamic 和非 opening_breakout 模式下应用)
        if p["strategy_mode"] not in ["dynamic", "opening_breakout"]:
            if rsi > p["rsi_threshold_buy"]:
                return "HOLD", f"RSI 值为 {rsi:.1f}，处于超买区间 (>{p['rsi_threshold_buy']:.0f})，暂不追高。"
            if squeeze:
                return "HOLD", "市场处于挤压状态 (Squeeze On)，暂不建仓。"

        # ---------------- 不同策略模式的买入决策 ----------------
        
        # 动态状态路由策略
        if p["strategy_mode"] == "dynamic":
            if regime == "trend_up":
                # 趋势模式下：检查通道突破或金叉
                # 突破唐奇安通道上轨 且 成交量放大 (RVOL >= 1.2)
                if close >= donchian_high and rvol >= 1.2:
                    return "BUY", f"【动态路由-趋势突破】价格突破唐奇安通道上轨 {donchian_high:.2f} 刀，且 RVOL={rvol:.2f} 量能放大。"
                if is_gold_cross:
                    return "BUY", "【动态路由-趋势金叉】EMA_9 向上穿越 EMA_21 形成金叉，趋势转强。"
            elif regime == "range_bound":
                # 震荡模式下：检查均值回归或形态反弹
                # 价格跌破布林下轨且RSI超卖
                bb_lower = row.get('BB_Lower', 0.0)
                if bb_lower > 0 and close < bb_lower and rsi < 25:
                    return "BUY", f"【动态路由-均值回归】价格跌破布林下轨 {bb_lower:.2f} 刀且 RSI={rsi:.1f} 超卖，预计将反弹。"
                # 底部反转K线形态
                is_bullish_pattern = pattern_w or pattern_hammer or pattern_bull_eng or row.get('Pattern_Morning_Star', False) or row.get('Pattern_Piercing', False)
                if is_bullish_pattern:
                    return "BUY", "【动态路由-底部形态】检测到 W底/锤子线/吞没/启明星 等看涨反转形态。"
        
        # A. 均线交叉策略
        elif p["strategy_mode"] == "ema_cross":
            if is_gold_cross:
                return "BUY", f"【EMA金叉买入】EMA_9 向上穿越 EMA_21 形成金叉，多头动能显现。"
                
        # B. 突破交易策略
        elif p["strategy_mode"] == "breakout":
            if is_pmh_breakout and is_bullish_trend:
                return "BUY", f"【阻力位突破】股价突破盘前最高位 {pmh:.2f} 刀，且均线呈多头排列。"
            if is_pdh_breakout and is_bullish_trend:
                return "BUY", f"【阻力位突破】股价突破昨日最高位 {pdh:.2f} 刀，且均线呈多头排列。"
                
        # C. K线形态策略
        elif p["strategy_mode"] == "patterns":
            if pattern_w:
                return "BUY", f"【W底反转】检测到双底 (W-Bottom) 形态突破颈线，看涨信号确认。"
            if pattern_hammer and is_near_vwap_support:
                return "BUY", f"【锤子线买入】在 VWAP 支撑线附近检测到 Hammer (锤子线) 看涨反转形态。"
            if pattern_bull_eng and is_near_vwap_support:
                return "BUY", f"【吞没看涨】在 VWAP 支撑线附近检测到阳包阴 (Bullish Engulfing) 形态。"
                
        # D. 共振共识策略
        elif p["strategy_mode"] == "consensus":
            if is_gold_cross and is_near_vwap_support:
                return "BUY", "【共振回调买入】价格回调至 VWAP 支撑区并触发 9/21 EMA 金叉。"
            if (is_pmh_breakout or is_pdh_breakout) and is_bullish_trend:
                level_name = "盘前高位 (PMH)" if is_pmh_breakout else "昨日高位 (PDH)"
                return "BUY", f"【共振突破买入】股价强力突破 {level_name}，且日内 EMA 多头排列。"
            if pattern_w:
                return "BUY", "【共振形态买入】检测到 W底 (Double Bottom) 形态突破颈线。"

        # E. 开盘区间突破策略 (ORB)
        elif p["strategy_mode"] == "opening_breakout":
            if orb_high > 0 and close > orb_high and rvol >= 1.2:
                return "BUY", f"【开盘突击-突破】股价突破5分钟开盘最高位 {orb_high:.2f} 刀，且成交量放大 (RVOL={rvol:.2f})。"

    # ------------------ 状态2：已持有仓位 (寻找平仓机会) ------------------
    else:
        # 计算当前浮动盈亏
        pnl_pct = (close - avg_cost) / avg_cost
        
        # 0. 动态风控平仓 (当处于 dynamic 模式时，如状态转入 trend_down 或 high_volatility 强制出场)
        if p["strategy_mode"] == "dynamic" and regime in ["trend_down", "high_volatility"]:
            return "SELL", f"【动态路由-风控平仓】市场状态恶化转为 {regime} 风险区间，立即离场避险。"
        
        # 0.5 开盘突击突破失败止损 (跌破开盘区间低点)
        if p["strategy_mode"] == "opening_breakout" and orb_low > 0 and close < orb_low:
            return "SELL", f"【开盘突击-突破失败止损】股价跌破5分钟开盘最低位 {orb_low:.2f} 刀，平仓防守。"

        # 1. 移动追踪止损 (Trailing Stop Loss)
        if p["trailing_stop_mode"] == "atr":
            stop_distance = atr * p["trailing_stop_atr_mult"]
            atr_stop_price = highest_price - stop_distance
            if close < atr_stop_price:
                return "SELL", f"【移动追踪止损】股价从最高价 {highest_price:.2f} 回撤超 {p['trailing_stop_atr_mult']}*ATR (当前追踪止损价: {atr_stop_price:.2f}，收盘价: {close:.2f})。"
                
        elif p["trailing_stop_mode"] == "flat":
            flat_stop_price = highest_price * (1 - p["stop_loss_pct"])
            if close < flat_stop_price:
                return "SELL", f"【移动比例止损】股价从最高价 {highest_price:.2f} 回跌超 {p['stop_loss_pct']*100:.1f}% (当前止损价: {flat_stop_price:.2f}，收盘价: {close:.2f})。"
                
        else:
            if pnl_pct <= -p["stop_loss_pct"]:
                return "SELL", f"【硬性止损】价格跌破成本的 {p['stop_loss_pct']*100:.1f}%，执行止损。"

        # 2. 硬性止盈目标
        if pnl_pct >= p["profit_target_pct"]:
            return "SELL", f"【目标止盈】股价达到 {p['profit_target_pct']*100:.1f}% 目标位 (涨幅: {pnl_pct*100:.2f}%)，全额止盈。"
            
        # 3. 形态平仓
        if p["strategy_mode"] in ["patterns", "consensus", "dynamic"]:
            if pattern_m:
                return "SELL", f"【M顶平仓】检测到双顶 (M-Top) 跌破颈线，趋势转空，平仓防守。"
            if pattern_shooting:
                return "SELL", f"【射击之星平仓】高位检测到 Shooting Star (流星线)，买盘竭尽，平仓出场。"
            if pattern_bear_eng:
                return "SELL", f"【吞没平仓】检测到阴包阳 (Bearish Engulfing) 看跌形态，平仓避险。"

        # 4. 趋势破位离场 (非 dynamic 模式使用)
        if p["strategy_mode"] != "dynamic" and close < vwap:
            return "SELL", f"【趋势破位】股价跌破日内生命线 VWAP ({vwap:.2f} 刀)，平仓防守。"
            
        # 5. 动量死叉离场 (EMA 模式使用)
        if p["strategy_mode"] == "ema_cross" and ema_9 < ema_21:
            return "SELL", "【死叉平仓】快线 EMA_9 跌破慢线 EMA_21 形成死叉，多头动能耗尽。"
            
    return "HOLD", "继续持有当前仓位，或保持空仓观望。"
