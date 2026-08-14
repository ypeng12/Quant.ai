DEFAULT_PARAMS = {
    # Risk & Position Sizing Baseline (daytrade.pdf)
    "risk_per_trade_pct": 0.0030,            # 0.30% account risk per trade
    "max_position_size_pct": 0.12,           # Max 12% equity allocation per ticker
    "max_total_open_risk_pct": 0.0090,       # Max 0.90% total account open risk
    "daily_loss_limit_pct": 0.012,           # Stop opening new positions if daily loss reaches 1.20%
    "daily_profit_lock_trigger_pct": 0.015, # Half risk per trade once daily profit reaches 1.50%
    "daily_profit_giveback_pct": 0.005,      # Halt new entries if daily profit gives back 0.50% from peak

    # Initial Volatility-Adaptive Stop Loss (ATR-Clipped)
    "initial_stop_mode": "atr_clipped",
    "initial_stop_atr_mult": 1.05,
    "stop_min_pct": 0.0025,                  # Min 0.25% stop
    "stop_max_pct": 0.0060,                  # Max 0.60% stop

    # R-Multiple Tiered Take Profit (1R = Initial Stop Distance)
    "tp1_r": 0.90,                           # Take Profit 1 at 0.90R
    "tp1_size_pct": 0.40,                    # Exit 40% position at TP1
    "tp2_r": 1.60,                           # Take Profit 2 at 1.60R
    "tp2_size_pct": 0.35,                    # Exit 35% position at TP2
    "runner_size_pct": 0.25,                 # Keep 25% runner

    # Stop Management
    "breakeven_trigger_r": 0.85,             # Move stop to breakeven + cost buffer at 0.85R
    "breakeven_cost_buffer_pct": 0.0006,     # Cover spread & fees
    "trail_start_r": 1.10,                   # Trailing stop starts at 1.10R
    "trailing_stop_mode": "atr",
    "trailing_stop_atr_mult": 1.10,          # 1.10 ATR trailing stop

    # Time Controls (Time Stop)
    "max_hold_minutes": 35,                  # Exit after 35 mins if stagnant
    "time_stop_minutes": 12,                 # Check progress at 12 mins
    "time_stop_min_progress_r": 0.35,        # Require >= 0.35R progress by 12 mins

    # Execution Quality & Cost Gate
    "min_reward_to_cost_ratio": 1.5,         # Minimum 1.5 reward-to-cost ratio for liquid US equities
    "max_spread_pct": 0.0006,                # Max 0.06% spread allowed
    "max_expected_slippage_pct": 0.0002,     # Max 0.02% slippage allowed for liquid tickers

    "strategy_mode": "dynamic"
}

def calculate_confidence_score(row, prev_row, is_bullish=True):
    """
    Calculate Volatility & RVOL Weighted AI Confidence Score (0 to 100 points):
    1. Trend Alignment (EMA 9 > 21 > 50): +25 pts
    2. RVOL Volume Surge (RVOL >= 1.2): +25 pts
    3. Intraday Volatility Expansion (ATR% >= 0.3%): +15 pts
    4. VWAP Position: +20 pts
    5. RSI Healthiness: +15 pts
    """
    score = 0
    close = row['Close']
    vwap = row['VWAP']
    ema_9 = row['EMA_9']
    ema_21 = row['EMA_21']
    ema_50 = row.get('EMA_50', ema_21)
    rsi = row.get('RSI', 50.0)
    rvol = row.get('RVOL', 1.0)
    atr = row.get('ATR', 0.0)
    atr_pct = (atr / close * 100.0) if close > 0 else 0.0
    
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

    # 2. RVOL Volume Surge
    if rvol >= 1.8:
        score += 25
    elif rvol >= 1.2:
        score += 15
    elif rvol >= 1.0:
        score += 8

    # 3. Intraday Volatility Expansion
    if atr_pct >= 0.6:
        score += 15
    elif atr_pct >= 0.3:
        score += 10

    # 4. VWAP Position
    if is_bullish and close >= vwap:
        score += 20
    elif not is_bullish and close < vwap:
        score += 20

    # 5. RSI Health Indicator
    if is_bullish and 45 <= rsi <= 68:
        score += 15
    elif not is_bullish and 32 <= rsi <= 55:
        score += 15

    return max(0, min(100, score))


def evaluate_market_state(row, prev_row, current_shares, avg_cost, ticker, highest_price=0.0, params=None, rank_percentile=None):
    """
    Evaluate current bar data and determine trading action using ATR-clipped stops and R-multiple targets (daytrade.pdf).
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
    atr = row['ATR']

    atr_pct = (atr / close) if close > 0 else 0.004
    stop_min_pct = p.get("stop_min_pct", 0.0025)
    stop_max_pct = p.get("stop_max_pct", 0.0060)
    initial_stop_atr_mult = p.get("initial_stop_atr_mult", 1.05)
    
    # Clip ATR stop loss between 0.25% and 0.60% (daytrade.pdf)
    stop_dist_pct = min(stop_max_pct, max(stop_min_pct, initial_stop_atr_mult * atr_pct))

    pmh = row.get('PMH', 0.0)
    pdh = row.get('PDH', 0.0)
    pml = row.get('PML', 0.0)
    pdl = row.get('PDL', 0.0)

    # Moving average cross indicators
    prev_ema_9 = prev_row['EMA_9']
    prev_ema_21 = prev_row['EMA_21']
    is_gold_cross = (prev_ema_9 <= prev_ema_21) and (ema_9 > ema_21)
    is_death_cross = (prev_ema_9 >= prev_ema_21) and (ema_9 < ema_21)
    
    is_bullish_trend = (ema_9 > ema_21)
    is_bearish_trend = (ema_9 < ema_21)

    prev_close = prev_row['Close']
    is_pmh_breakout = (prev_close <= pmh) and (close > pmh) and (pmh > 0)
    is_pdh_breakout = (prev_close <= pdh) and (close > pdh) and (pdh > 0)
    is_pml_breakdown = (prev_close >= pml) and (close < pml) and (pml > 0)
    is_pdl_breakdown = (prev_close >= pdl) and (close < pdl) and (pdl > 0)

    # Cost Gate Validation: Reward-to-Cost Ratio (daytrade.pdf)
    spread_pct = float(row.get('Spread_Pct', 0.0002))
    expected_cost_pct = spread_pct + p.get("max_expected_slippage_pct", 0.0002)
    tp1_reward_pct = stop_dist_pct * p.get("tp1_r", 0.90)
    if expected_cost_pct > 0 and (tp1_reward_pct / expected_cost_pct) < p.get("min_reward_to_cost_ratio", 1.5):
        cost_gate_pass = False
    else:
        cost_gate_pass = True

    # State 1: Flat Position (Search for BUY / SHORT opportunities)
    if current_shares == 0:
        if not cost_gate_pass:
            return "HOLD", f"[{ticker}] Reward-to-cost ratio below {p.get('min_reward_to_cost_ratio', 3.0)}x threshold. Standing aside."

        # A. Long BUY Signals
        if is_bullish_trend:
            score = calculate_confidence_score(row, prev_row, is_bullish=True)
            is_relative_top = (rank_percentile is not None and rank_percentile >= 70.0)
            min_cutoff = 25 if is_relative_top else 45

            if score < min_cutoff:
                return "HOLD", f"[{ticker}] Confidence Score ({score}/100) below {min_cutoff} cutoff."

            if is_gold_cross:
                reason = "EMA 9/21 Golden Cross."
            elif close >= vwap:
                reason = f"Price holding above VWAP (${vwap:.2f})."
            elif is_pmh_breakout or is_pdh_breakout:
                reason = "PMH/PDH Breakout."
            else:
                return "HOLD", "Maintaining flat stance."

            rank_str = f" [Watchlist Top-{100-int(rank_percentile)}%]" if rank_percentile is not None else ""

            if score >= 75 or (is_relative_top and score >= 50):
                return "BUY", f"[Conviction-Top Score:{score}/100{rank_str}] {reason} Initial Stop: {stop_dist_pct*100:.2f}% (1.0R)."
            elif score >= 55 or (is_relative_top and score >= 35):
                return "BUY", f"[Standard-Entry Score:{score}/100{rank_str}] {reason} Initial Stop: {stop_dist_pct*100:.2f}% (1.0R)."
            else:
                return "BUY", f"[Probe-Light Score:{score}/100{rank_str}] {reason} Initial Stop: {stop_dist_pct*100:.2f}% (1.0R)."

        # B. Short SELL Signals
        if is_bearish_trend:
            score = calculate_confidence_score(row, prev_row, is_bullish=False)
            is_relative_top = (rank_percentile is not None and rank_percentile >= 70.0)
            min_cutoff = 25 if is_relative_top else 45

            if score < min_cutoff:
                return "HOLD", f"[{ticker}] Short Confidence Score ({score}/100) below {min_cutoff} cutoff."

            if is_death_cross:
                reason = "EMA 9/21 Death Cross."
            elif close < vwap:
                reason = f"Price dropped below VWAP (${vwap:.2f})."
            elif is_pml_breakdown or is_pdl_breakdown:
                reason = "PMH/PDH Breakdown."
            else:
                return "HOLD", "Maintaining flat stance."

            rank_str = f" [Watchlist Top-{100-int(rank_percentile)}%]" if rank_percentile is not None else ""

            if score >= 75 or (is_relative_top and score >= 50):
                return "SHORT", f"[Conviction-Top Score:{score}/100{rank_str}] {reason} Initial Stop: {stop_dist_pct*100:.2f}% (1.0R)."
            elif score >= 55 or (is_relative_top and score >= 35):
                return "SHORT", f"[Standard-Entry Score:{score}/100{rank_str}] {reason} Initial Stop: {stop_dist_pct*100:.2f}% (1.0R)."
            else:
                return "SHORT", f"[Probe-Light Score:{score}/100{rank_str}] {reason} Initial Stop: {stop_dist_pct*100:.2f}% (1.0R)."

    # State 2: Holding Long Position (Search for SELL / PARTIAL_SELL opportunities)
    elif current_shares > 0:
        pnl_pct = (close - avg_cost) / avg_cost if avg_cost > 0 else 0.0
        pnl_r = pnl_pct / stop_dist_pct if stop_dist_pct > 0 else 0.0

        peak_price = max(highest_price, close)
        peak_pnl_pct = (peak_price - avg_cost) / avg_cost if avg_cost > 0 else pnl_pct
        peak_pnl_r = peak_pnl_pct / stop_dist_pct if stop_dist_pct > 0 else pnl_r

        tp1_r = p.get("tp1_r", 0.90)
        tp2_r = p.get("tp2_r", 1.60)
        breakeven_trigger_r = p.get("breakeven_trigger_r", 0.85)
        breakeven_cost_buffer_pct = p.get("breakeven_cost_buffer_pct", 0.0006)

        is_tp1_done = params.get("is_tp1_done", False) if params else False
        is_tp2_done = params.get("is_tp2_done", False) if params else False

        # 1. TP1 Partial Take Profit (0.90R, Exit 40% & Lock Breakeven)
        if pnl_r >= tp1_r and not is_tp1_done:
            return "PARTIAL_SELL", f"[TP1-TakeProfit 40%] Reached +{pnl_r:.2f}R (+{pnl_pct*100:.2f}% gain). Scaling out 40%."

        # 2. TP2 Partial Take Profit (1.60R, Exit 35%)
        if pnl_r >= tp2_r and not is_tp2_done:
            return "PARTIAL_SELL", f"[TP2-TakeProfit 35%] Reached +{pnl_r:.2f}R (+{pnl_pct*100:.2f}% gain). Scaling out 35%."

        # 3. Breakeven Stop Loss (Triggered after peak >= 0.85R)
        if peak_pnl_r >= breakeven_trigger_r:
            breakeven_price = avg_cost * (1.0 + breakeven_cost_buffer_pct)
            if close <= breakeven_price:
                return "SELL", f"[BreakevenStop] Price pulled back to ${close:.2f} near breakeven (${breakeven_price:.2f}). Exiting."

        # 4. Initial ATR-Clipped Stop Loss (-1.0R)
        if pnl_r <= -1.0:
            return "SELL", f"[InitialStopLoss] Loss reached -1.0R (-{abs(pnl_pct)*100:.2f}%)."

        # 5. ATR Trailing Stop (Starts after peak >= 1.10R)
        if peak_pnl_r >= p.get("trail_start_r", 1.10):
            trail_stop_dist = atr * p.get("trailing_stop_atr_mult", 1.10)
            trail_stop_price = peak_price - trail_stop_dist
            if close <= trail_stop_price:
                return "SELL", f"[ATR-TrailingStop] Price dropped from peak ${peak_price:.2f} to trigger trail stop ${trail_stop_price:.2f}."

        # 6. Trend Reversal
        if is_death_cross or (is_bearish_trend and close < vwap):
            return "SELL", "[Long-Reversal] EMA Death Cross and below VWAP."

    # State 3: Holding Short Position (Search for COVER / PARTIAL_COVER opportunities)
    elif current_shares < 0:
        short_pnl_pct = (avg_cost - close) / avg_cost if avg_cost > 0 else 0.0
        short_pnl_r = short_pnl_pct / stop_dist_pct if stop_dist_pct > 0 else 0.0

        tp1_r = p.get("tp1_r", 0.90)
        tp2_r = p.get("tp2_r", 1.60)
        breakeven_trigger_r = p.get("breakeven_trigger_r", 0.85)
        breakeven_cost_buffer_pct = p.get("breakeven_cost_buffer_pct", 0.0006)

        is_tp1_done = params.get("is_tp1_done", False) if params else False
        is_tp2_done = params.get("is_tp2_done", False) if params else False

        # 1. TP1 Partial Take Profit (0.90R, Exit 40%)
        if short_pnl_r >= tp1_r and not is_tp1_done:
            return "PARTIAL_COVER", f"[TP1-ShortCover 40%] Reached +{short_pnl_r:.2f}R (+{short_pnl_pct*100:.2f}% gain). Cover 40%."

        # 2. TP2 Partial Take Profit (1.60R, Exit 35%)
        if short_pnl_r >= tp2_r and not is_tp2_done:
            return "PARTIAL_COVER", f"[TP2-ShortCover 35%] Reached +{short_pnl_r:.2f}R (+{short_pnl_pct*100:.2f}% gain). Cover 35%."

        # 3. Breakeven Stop
        if short_pnl_r >= breakeven_trigger_r:
            breakeven_price = avg_cost * (1.0 - breakeven_cost_buffer_pct)
            if close >= breakeven_price:
                return "COVER", f"[BreakevenStop] Short price bounced back to ${close:.2f} near breakeven (${breakeven_price:.2f}). Exiting."

        # 4. Stop Loss
        if short_pnl_r <= -1.0:
            return "COVER", f"[Short-InitialStopLoss] Rebounded -1.0R (+{abs(short_pnl_pct)*100:.2f}%)."

        # 5. Trend Reversal
        if is_gold_cross or (is_bullish_trend and close >= vwap):
            return "COVER", "[Short-Reversal] EMA Golden Cross and reclaimed VWAP."

    return "HOLD", "Maintaining current position."
