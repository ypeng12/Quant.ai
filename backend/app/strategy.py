# backend/app/strategy.py

DEFAULT_PARAMS = {
    "stop_loss_pct": 0.006,       # 0.6% Stop-loss - High-frequency intraday
    "profit_target_pct": 0.008,   # 0.8% Profit target - Quick profit lock
    "trailing_stop_mode": "atr",
    "trailing_stop_atr_mult": 1.0,  # Tight trailing stop-loss
    "rsi_threshold_buy": 72.0,
    "strategy_mode": "dynamic"   # dynamic, consensus, ema_cross, breakout, patterns, opening_breakout
}

def calculate_confidence_score(row, prev_row, is_bullish=True, is_focus=False):
    """
    Calculate 5-factor AI confidence score (0 to 100 points):
    1. Trend Alignment (EMA 9 > 21 > 50): +25 pts
    2. Relative Volume (RVOL >= 1.1): +20 pts
    3. VWAP Support/Resistance (close vs VWAP): +20 pts
    4. RSI Healthiness (45 <= RSI <= 68): +15 pts
    5. Breakout / Cross Resonance: +20 pts
    6. Focus Ticker Overweight Bonus (is_focus=True): +15 pts
    """
    score = 0
    close = row['Close']
    vwap = row['VWAP']
    ema_9 = row['EMA_9']
    ema_21 = row['EMA_21']
    ema_50 = row.get('EMA_50', ema_21)
    rsi = row.get('RSI', 50.0)
    rvol = row.get('RVOL', 1.0)
    
    # 1. Trend Alignment
    if is_bullish:
        if ema_9 > ema_21 > ema_50:
            score += 25
        elif ema_9 > ema_21:
            score += 15
    else:
        if ema_9 < ema_21 < ema_50:
            score += 25
        elif ema_9 < ema_21:
            score += 15

    # 2. RVOL Volume Confirmation
    if rvol >= 1.4:
        score += 20
    elif rvol >= 1.1:
        score += 12

    # 3. VWAP Position
    if is_bullish and close >= vwap:
        score += 20
    elif not is_bullish and close < vwap:
        score += 20

    # 4. RSI Health Indicator
    if is_bullish and 45 <= rsi <= 68:
        score += 15
    elif not is_bullish and 32 <= rsi <= 55:
        score += 15

    # 5. Breakout / Cross Resonance
    prev_ema_9 = prev_row['EMA_9']
    prev_ema_21 = prev_row['EMA_21']
    if is_bullish and prev_ema_9 <= prev_ema_21 and ema_9 > ema_21:
        score += 20
    elif not is_bullish and prev_ema_9 >= prev_ema_21 and ema_9 < ema_21:
        score += 20

    # 6. Priority Overweight Focus Bonus
    if is_focus:
        score += 15

    return min(100, score)


def evaluate_market_state(row, prev_row, current_shares, avg_cost, ticker, highest_price=0.0, params=None, is_focus=False):
    """
    Evaluate current bar data and determine trading action.
    - BUY: Trigger long position (35% probe, 70% standard, 100% full conviction)
    - PYRAMID_BUY: Add-on position (+35%) when momentum builds
    - SHORT: Trigger short position
    - PARTIAL_SELL: Scale-out 50% take profit & lock breakeven
    - SELL: Close long position
    - COVER: Close short position
    - HOLD: Standing aside
    """
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
    
    pmh = row.get('PMH', 0.0)
    pdh = row.get('PDH', 0.0)
    
    orb_high = row.get('ORB_High', 0.0)
    orb_low = row.get('ORB_Low', 0.0)
    
    pattern_w = row.get('Pattern_W_Bottom', False)
    pattern_m = row.get('Pattern_M_Top', False)
    pattern_hammer = row.get('Pattern_Hammer', False)
    pattern_shooting = row.get('Pattern_Shooting_Star', False)
    pattern_bull_eng = row.get('Pattern_Bullish_Engulfing', False)
    pattern_bear_eng = row.get('Pattern_Bearish_Engulfing', False)
    
    regime = row.get('Regime', 'range_bound')
    donchian_high = row.get('Donchian_High', 0.0)
    donchian_low = row.get('Donchian_Low', 0.0)
    rvol = row.get('RVOL', 1.0)

    # 1. Moving average cross indicators
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

    # State 1: Flat Position (Search for BUY / SHORT opportunities)
    if current_shares == 0:
        # A. Long BUY Signals
        if is_bullish_trend:
            score = calculate_confidence_score(row, prev_row, is_bullish=True, is_focus=is_focus)
            focus_str = "🔥 [Focus-Overweight] " if is_focus else ""
            if score < 30:
                return "HOLD", f"[{ticker}] {focus_str}Confidence Score ({score}/100) below 30 threshold. Standing aside."

            if is_gold_cross:
                reason = f"EMA 9/21 Golden Cross."
            elif close >= vwap:
                reason = f"Price holding above VWAP (${vwap:.2f})."
            elif donchian_high > 0 and close >= donchian_high:
                reason = f"Donchian High breakout (${donchian_high:.2f})."
            elif is_pmh_breakout or is_pdh_breakout:
                reason = f"PMH/PDH Breakout."
            else:
                return "HOLD", "Maintaining flat stance."

            if 30 <= score < 55:
                return "BUY", f"[Probe-Light Score:{score}/100] {focus_str}{reason} Initial light probe position (35% size)."
            elif 55 <= score < 75:
                return "BUY", f"[Standard-Entry Score:{score}/100] {focus_str}{reason} Standard entry (70% size)."
            else:
                return "BUY", f"[Conviction-Full Score:{score}/100] {focus_str}{reason} High conviction entry (100% size)."

        # B. Short SELL Signals
        if is_bearish_trend:
            score = calculate_confidence_score(row, prev_row, is_bullish=False, is_focus=is_focus)
            focus_str = "🔥 [Focus-Overweight] " if is_focus else ""
            if score < 30:
                return "HOLD", f"[{ticker}] {focus_str}Short Confidence Score ({score}/100) below 30 threshold. Standing aside."

            if is_death_cross:
                reason = "EMA 9/21 Death Cross."
            elif close < vwap:
                reason = f"Price dropped below VWAP (${vwap:.2f})."
            elif donchian_low > 0 and close <= donchian_low:
                reason = f"Donchian Low breakdown (${donchian_low:.2f})."
            elif is_pml_breakdown or is_pdl_breakdown:
                reason = "PMH/PDH Breakdown."
            else:
                return "HOLD", "Maintaining flat stance."

            if 30 <= score < 55:
                return "SHORT", f"[Probe-Light Score:{score}/100] {focus_str}{reason} Initial light probe short (35% size)."
            elif 55 <= score < 75:
                return "SHORT", f"[Standard-Entry Score:{score}/100] {focus_str}{reason} Standard short (70% size)."
            else:
                return "SHORT", f"[Conviction-Full Score:{score}/100] {focus_str}{reason} High conviction short (100% size)."

    # State 2: Holding Long Position (Search for SELL / PARTIAL_SELL opportunities)
    elif current_shares > 0:
        pnl_pct = (close - avg_cost) / avg_cost
        peak_pnl_pct = (highest_price - avg_cost) / avg_cost if (highest_price > avg_cost and avg_cost > 0) else pnl_pct
        stop_loss = p.get("stop_loss_pct", 0.006)
        profit_target = p.get("profit_target_pct", 0.008)
        breakeven_trigger = p.get("breakeven_trigger_pct", 0.008)
        is_scaled_out = params.get("is_scaled_out", False) if params else False

        # Pyramiding Add-On: If confidence score builds up (Score >= 55) and trade is in profit (+0.3%+), trigger add-on
        score = calculate_confidence_score(row, prev_row, is_bullish=True, is_focus=is_focus)
        is_pyramided = params.get("is_pyramided", False) if params else False
        if score >= 55 and pnl_pct >= 0.003 and not is_pyramided and not is_scaled_out:
            return "PYRAMID_BUY", f"[Pyramid-Addon Score:{score}/100] Momentum growing & trade in profit (+{pnl_pct*100:.2f}%). Adding +35% position."

        # 1. First-Stage Scale-Out (50% Take Profit & Lock Breakeven)
        if pnl_pct >= breakeven_trigger and not is_scaled_out:
            return "PARTIAL_SELL", f"[Long-PartialTakeProfit] Reached +{pnl_pct*100:.2f}% gain. Executing 50% scale-out & locking breakeven."

        ratchet_trigger = p.get("ratchet_trigger_pct", 0.015)
        # 2. Dynamic Ratchet Profit Lock (Lock in >= 50% of peak gains once peak profit >= +1.5%)
        if peak_pnl_pct >= ratchet_trigger and avg_cost > 0:
            ratchet_locked_pnl = max(0.001, peak_pnl_pct * 0.50)  # Lock at least 50% of peak unrealized gain
            ratchet_stop_price = avg_cost * (1.0 + ratchet_locked_pnl)
            if close < ratchet_stop_price:
                return "SELL", f"[Long-RatchetLock] Price pulled back to ${close:.2f}, triggering profit-lock stop ${ratchet_stop_price:.2f} (Locked +{ratchet_locked_pnl*100:.2f}% gain)."

        # 3. Ultimate Full Take Profit
        if pnl_pct >= profit_target * 2.0:
            return "SELL", f"[Long-FullTakeProfit] Reached max profit target +{pnl_pct*100:.2f}%."

        # 4. Breakeven Stop Loss (If peak exceeded breakeven trigger, never allow negative PnL)
        if peak_pnl_pct >= breakeven_trigger and pnl_pct <= 0.001:
            return "SELL", f"[Long-BreakevenStop] Price pulled back near entry (${avg_cost:.2f}). Exiting to preserve principal."

        # 5. Fixed Stop Loss
        if pnl_pct <= -stop_loss:
            return "SELL", f"[Long-StopLoss] Loss reached -{abs(pnl_pct)*100:.2f}%."

        # 6. Trailing Stop
        stop_distance = atr * p.get("trailing_stop_atr_mult", 1.0)
        atr_stop_price = highest_price - stop_distance
        if close < atr_stop_price and highest_price > 0:
            return "SELL", f"[Long-TrailingStop] Price pulled back from peak ${highest_price:.2f} to trigger stop ${atr_stop_price:.2f}."

        # 7. Trend Reversal
        if is_death_cross or (is_bearish_trend and close < vwap):
            return "SELL", "[Long-Reversal] EMA Death Cross and below VWAP."

    # State 3: Holding Short Position (Search for COVER / PARTIAL_COVER opportunities)
    elif current_shares < 0:
        short_pnl_pct = (avg_cost - close) / avg_cost
        stop_loss = p.get("stop_loss_pct", 0.006)
        profit_target = p.get("profit_target_pct", 0.008)
        breakeven_trigger = p.get("breakeven_trigger_pct", 0.008)
        is_scaled_out = params.get("is_scaled_out", False) if params else False

        # 1. First-Stage Scale-Out (50% Take Profit)
        if short_pnl_pct >= breakeven_trigger and not is_scaled_out:
            return "PARTIAL_COVER", f"[Short-PartialTakeProfit] Reached +{short_pnl_pct*100:.2f}% gain. Scaling out 50% & locking breakeven."

        # 2. Dynamic Full Take Profit
        if short_pnl_pct >= profit_target * 2.0:
            return "COVER", f"[Short-FullTakeProfit] Reached max downside profit +{short_pnl_pct*100:.2f}%."

        # 3. Stop Loss
        if short_pnl_pct <= -stop_loss:
            return "COVER", f"[Short-StopLoss] Price rebounded +{abs(short_pnl_pct)*100:.2f}%."

        # 4. Trend Reversal
        if is_gold_cross or (is_bullish_trend and close >= vwap):
            return "COVER", "[Short-Reversal] EMA Golden Cross and reclaimed VWAP."

    return "HOLD", "Maintaining current position."
