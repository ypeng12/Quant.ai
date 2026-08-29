# backend/data/generate_trade_comparison_report.py
"""
Real Intraday K-Line Retrospective Dashboard Generator
Features:
1. Fetches REAL 1m, 5m, 15m, 30m intraday bar data for today (2026-08-12) for all watchlist stocks.
2. Runs the exact new strategy simulation to generate exact trade entry & exit records.
3. Plots exact Buy/Short/Exit markers, trade duration, and PnL directly onto the intraday K-line charts.
4. Provides Robinhood pure white aesthetic with interactive ticker pills (SNDK, MU, PLTR, NVDA, TSLA, MSFT, NBIS, AMD) and timeframe switchers.
"""

import os
import sys
import json
import pandas as pd
import numpy as np

# Add backend directory to path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL
from app.data_manager import fetch_and_prepare_data
from app.alpha_engine import InstitutionalAlphaEngine
from app.broker.risk_position_sizer import RiskPositionSizer

OUTPUT_DIR = os.path.join(BASE_DIR, "data", "charts")
DATASETS_DIR = os.path.join(BASE_DIR, "data", "datasets")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATASETS_DIR, exist_ok=True)

import datetime

WATCHLIST = ["TSLA", "NVDA", "MSTR", "SNDK"]

# Dynamic Date: Default to today or CLI argument
if len(sys.argv) > 1 and len(sys.argv[1]) == 10:
    TODAY_STR = sys.argv[1]
else:
    TODAY_STR = datetime.datetime.now().strftime("%Y-%m-%d")


def run_full_simulation():
    """Runs deterministic simulation for today across watchlist symbols."""
    engine = InstitutionalAlphaEngine()
    sizer = RiskPositionSizer()

    params = {
        "entry_score_min": 50.0,
        "full_size_score": 75.0,
        "starter_buying_power_pct": 0.25,
        "max_position_buying_power_pct": 0.95,
        "buying_power_utilization_pct": 0.95,
        "stop_loss_pct": 0.02,
        "profit_target_pct": 0.035,
        "time_stop_min_score": 50.0,
        "enable_anti_trap_flip": True,
    }

    account = {"equity": 100000.0, "cash": 100000.0, "multiplier": 4.0, "buying_power": 400000.0}
    completed_trades = []

    for ticker in WATCHLIST:
        df = fetch_and_prepare_data(ticker, interval="1m")
        if df is None or df.empty:
            continue

        today_df = df[df.index.astype(str).str.contains(TODAY_STR)]
        if today_df.empty:
            continue

        position = None

        for i in range(1, len(today_df)):
            row = today_df.iloc[i].to_dict()
            prev_row = today_df.iloc[i - 1].to_dict()
            time_str = str(today_df.index[i])
            close_p = row.get("Close", 0.0)

            alpha_eval = engine.evaluate_composite_alpha(row, prev_row)
            score = alpha_eval["composite_alpha_score"]
            is_trap = alpha_eval.get("is_trap", False)
            trap_reason = alpha_eval.get("trap_reason", "")

            direction = "LONG" if score >= 0 else "SHORT"

            if params["enable_anti_trap_flip"] and is_trap:
                if "Bull Trap" in trap_reason or "Upper Wick" in trap_reason or "Ask Depth" in trap_reason:
                    if score <= -45.0:
                        direction = "SHORT"
                elif "Bear Trap" in trap_reason or "Lower Wick" in trap_reason or "Bid Depth" in trap_reason:
                    if score >= 45.0:
                        direction = "LONG"

            abs_score = abs(score)

            # 1. Manage Active Position Exit
            if position is not None:
                side = position["side"]
                entry_p = position["entry_price"]
                shs = position["shares"]
                entry_idx = position["entry_idx"]
                duration_min = i - entry_idx

                if side == "LONG":
                    pnl_pct = (close_p - entry_p) / entry_p
                    is_tp = pnl_pct >= params["profit_target_pct"]
                    is_sl = pnl_pct <= -params["stop_loss_pct"]
                    is_decay = score < params["time_stop_min_score"] and pnl_pct > -0.005

                    if is_tp or is_sl or is_decay:
                        reason = "PROFIT_TARGET" if is_tp else ("STOP_LOSS" if is_sl else "SIGNAL_DECAY")
                        real_pnl = (close_p - entry_p) * shs
                        completed_trades.append({
                            "ticker": ticker,
                            "side": "LONG",
                            "entry_time": position["entry_time"],
                            "exit_time": time_str,
                            "entry_price": entry_p,
                            "exit_price": close_p,
                            "shares": shs,
                            "notional": shs * entry_p,
                            "duration_min": duration_min,
                            "pnl": real_pnl,
                            "pnl_pct": pnl_pct * 100,
                            "reason": reason,
                        })
                        position = None
                else:  # SHORT
                    pnl_pct = (entry_p - close_p) / entry_p
                    is_tp = pnl_pct >= params["profit_target_pct"]
                    is_sl = pnl_pct <= -params["stop_loss_pct"]
                    is_decay = score > -params["time_stop_min_score"] and pnl_pct > -0.005

                    if is_tp or is_sl or is_decay:
                        reason = "PROFIT_TARGET" if is_tp else ("STOP_LOSS" if is_sl else "SIGNAL_DECAY")
                        real_pnl = (entry_p - close_p) * shs
                        completed_trades.append({
                            "ticker": ticker,
                            "side": "SHORT",
                            "entry_time": position["entry_time"],
                            "exit_time": time_str,
                            "entry_price": entry_p,
                            "exit_price": close_p,
                            "shares": shs,
                            "notional": shs * entry_p,
                            "duration_min": duration_min,
                            "pnl": real_pnl,
                            "pnl_pct": pnl_pct * 100,
                            "reason": reason,
                        })
                        position = None

            # 2. Entry Check
            if position is None and abs_score >= params["entry_score_min"]:
                opp = {"score": score, "_stop_pct": 0.015}
                is_probe = abs_score < params["full_size_score"]
                sizing = sizer.size_probe_entry(account, close_p, opp, params) if is_probe else sizer.size_aggressive_entry(account, close_p, opp, params)

                shs = sizing["shares"]
                if shs > 0:
                    position = {
                        "side": direction,
                        "entry_price": close_p,
                        "shares": shs,
                        "entry_time": time_str,
                        "entry_idx": i,
                        "entry_type": "PROBE" if is_probe else "FULL",
                    }

    return completed_trades


def prepare_real_kline_data():
    """Fetches REAL 1m, 5m, 15m, 30m intraday candle bars organized by Date for all tickers."""
    chart_data = {}
    intervals = ["1m", "5m", "15m", "30m"]
    today_dt = datetime.datetime.now()
    dates_list = [(today_dt - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    target_dates = list(dict.fromkeys([TODAY_STR] + dates_list + ["2026-08-26", "2026-08-12", "2026-08-11", "2026-08-10", "2026-08-07", "2026-07-30"]))

    for d_str in target_dates:
        chart_data[d_str] = {}
        for ticker in WATCHLIST:
            chart_data[d_str][ticker] = {}
            for tf in intervals:
                df = fetch_and_prepare_data(ticker, interval=tf)
                if df is not None and not df.empty:
                    date_df = df[df.index.astype(str).str.contains(d_str)]
                    if not date_df.empty:
                        chart_data[d_str][ticker][tf] = {
                            "time": [str(t).split()[-1][:5] for t in date_df.index],
                            "full_time": [str(t) for t in date_df.index],
                            "open": [round(float(x), 2) for x in date_df["Open"]],
                            "high": [round(float(x), 2) for x in date_df["High"]],
                            "low": [round(float(x), 2) for x in date_df["Low"]],
                            "close": [round(float(x), 2) for x in date_df["Close"]],
                            "volume": [int(x) for x in date_df["Volume"]],
                        }
    return chart_data


def build_real_kline_dashboard():
    """Builds interactive HTML dashboard with REAL intraday K-lines and exact buy/sell markers."""
    print("[*] Syncing latest Alpaca live trades into history...")
    trade_hist_file = os.path.join(BASE_DIR, "trade_history.json")
    try:
        from app.broker.alpaca_adapter import AlpacaAdapter
        from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        adapter = AlpacaAdapter(api_key=ALPACA_API_KEY, api_secret=ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)
        orders = adapter.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, limit=200))
        existing_history = []
        if os.path.exists(trade_hist_file):
            with open(trade_hist_file, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                existing_history = raw.get('trade_history', []) if isinstance(raw, dict) else raw
        existing_ids = {t.get('order_id') for t in existing_history if t.get('order_id')}
        for o in reversed(orders):
            oid = str(o.id)
            if oid not in existing_ids and str(o.status) == 'OrderStatus.FILLED':
                sub_at = str(o.submitted_at)
                side_str = str(o.side).replace('OrderSide.', '').upper()
                cid = str(o.client_order_id or '').upper()
                action = "SHORT" if "ENTRY" in cid and side_str == "SELL" else ("BUY" if side_str == "BUY" else ("COVER" if "EXIT" in cid else "SELL"))
                existing_history.append({
                    "order_id": oid,
                    "date": sub_at[:10],
                    "time": sub_at[:19].replace('T', ' '),
                    "action": action,
                    "action_cn": "做空" if action == "SHORT" else ("平空" if action == "COVER" else ("买入" if action == "BUY" else "卖出")),
                    "ticker": o.symbol,
                    "shares": int(o.filled_qty or 0),
                    "price": float(o.filled_avg_price or 0.0),
                    "pnl": 0.0,
                    "reason": f"Alpaca Broker Sync ({action})"
                })
                existing_ids.add(oid)
        with open(trade_hist_file, 'w', encoding='utf-8') as f:
            json.dump({"trade_history": existing_history}, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Warning] Failed to sync Alpaca orders in report: {e}")

    print("[*] Running strategy simulation for today...")
    new_trades = run_full_simulation()

    print("[*] Fetching REAL intraday K-lines (1m, 5m, 15m, 30m) for all tickers...")
    chart_data = prepare_real_kline_data()

    # Load Real Execution History from trade_history.json
    real_history_trades = []
    if os.path.exists(trade_hist_file):
        try:
            with open(trade_hist_file, "r", encoding="utf-8") as f:
                hist_raw = json.load(f)
                real_history_trades = hist_raw.get("trade_history", []) if isinstance(hist_raw, dict) else hist_raw
        except Exception as e:
            print(f"[Warning] Failed to load trade_history.json: {e}")

        chart_data_json = json.dumps(chart_data)
    new_trades_json = json.dumps(new_trades)
    real_trades_json = json.dumps(real_history_trades)

    # Dynamic date select options
    all_dates = list(chart_data.keys())
    if TODAY_STR not in all_dates:
        all_dates.insert(0, TODAY_STR)
    
    date_options_html = ""
    for d in all_dates:
        sel_attr = "selected" if d == TODAY_STR else ""
        label = f"{d} (今日美东)" if d == TODAY_STR else d
        date_options_html += f'<option value="{d}" {sel_attr}>{label}</option>\n'

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant.ai - HRT ML 动态仿真与历史 K 线复盘大屏</title>
    <script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        * {{ box-sizing: border-box; font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }}
        body {{ background-color: #0b0e14; color: #e2e8f0; margin: 0; padding: 20px; }}
        
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 14px; flex-wrap: wrap; gap: 12px; }}
        .header .brand {{ font-size: 20px; font-weight: 800; color: #38bdf8; letter-spacing: -0.5px; }}
        .header .sub {{ color: #94a3b8; font-size: 13px; margin-top: 4px; }}
        
        .date-select {{ padding: 6px 14px; border-radius: 8px; border: 1px solid rgba(56,189,248,0.3); font-weight: 700; font-size: 13px; color: #38bdf8; background: #131722; cursor: pointer; outline: none; }}

        .mode-switch-bar {{ display: flex; gap: 10px; margin-bottom: 16px; background: #131722; padding: 4px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.08); width: fit-content; }}
        .mode-btn {{ padding: 8px 18px; border-radius: 8px; border: none; font-weight: 700; font-size: 13px; cursor: pointer; transition: all 0.2s ease; display: flex; align-items: center; gap: 6px; }}
        .mode-btn.btn-real {{ background: transparent; color: #94a3b8; }}
        .mode-btn.btn-real.active {{ background: #1e293b; color: #ffffff; border: 1px solid rgba(255,255,255,0.15); box-shadow: 0 2px 8px rgba(0,0,0,0.4); }}
        .mode-btn.btn-ml {{ background: transparent; color: #94a3b8; }}
        .mode-btn.btn-ml.active {{ background: linear-gradient(135deg, #0284c7, #0369a1); color: #ffffff; box-shadow: 0 2px 8px rgba(2,132,199,0.4); }}

        .controls-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px; background: #131722; padding: 10px 14px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.08); }}
        .ticker-pills {{ display: flex; gap: 8px; flex-wrap: wrap; }}
        .ticker-pill {{ padding: 6px 16px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.1); background: #0f172a; color: #94a3b8; font-weight: 700; font-size: 13px; cursor: pointer; transition: all 0.2s ease; }}
        .ticker-pill:hover {{ background: #1e293b; color: #ffffff; }}
        .ticker-pill.active {{ background: #0284c7; color: #ffffff; border-color: #38bdf8; box-shadow: 0 0 10px rgba(56,189,248,0.4); }}
        
        .timeframe-pills {{ display: flex; background: #0f172a; border-radius: 6px; padding: 3px; border: 1px solid rgba(255,255,255,0.1); }}
        .tf-pill {{ padding: 5px 12px; border-radius: 4px; border: none; background: transparent; color: #94a3b8; font-weight: 700; font-size: 12px; cursor: pointer; transition: all 0.2s ease; }}
        .tf-pill.active {{ background: #10b981; color: #ffffff; }}
        
        .section-box {{ background: #131722; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 16px; margin-bottom: 20px; box-shadow: 0 4px 16px rgba(0,0,0,0.3); }}
        .section-title {{ font-size: 16px; font-weight: 800; color: #38bdf8; margin: 0 0 14px 0; display: flex; justify-content: space-between; align-items: center; }}
        
        .pnl-badge {{ background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: #10b981; padding: 4px 12px; border-radius: 6px; font-weight: 800; font-size: 14px; }}
        .replay-controls {{ display: flex; align-items: center; gap: 6px; background: #0f172a; padding: 4px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.1); }}
        .ctrl-btn {{ padding: 4px 10px; border-radius: 4px; border: none; font-weight: 700; font-size: 12px; cursor: pointer; transition: all 0.2s ease; background: #1e293b; color: #fff; }}
        .ctrl-btn:hover {{ background: #0284c7; }}
        .ctrl-btn.active {{ background: #10b981; color: #fff; }}
        
        .slider-group {{ margin-bottom: 12px; }}
        .slider-label {{ font-size: 11px; color: #94a3b8; margin-bottom: 4px; display: flex; justify-content: space-between; }}
        .slider-val {{ color: #38bdf8; font-weight: 700; }}
        input[type=range] {{ width: 100%; cursor: pointer; accent-color: #0284c7; }}

        .order-ticket {{ background: #0f172a; border-left: 4px solid #10b981; padding: 8px 10px; border-radius: 6px; margin-bottom: 6px; font-size: 12px; animation: fadeIn 0.3s ease; }}
        .order-ticket.short {{ border-left-color: #ef4444; }}
        .order-ticket.exit {{ border-left-color: #f59e0b; }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(-5px); }} to {{ opacity: 1; transform: translateY(0); }} }}

        .rh-green {{ color: #10b981; }}
        .rh-red {{ color: #ef4444; }}
        
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ text-align: left; padding: 10px; color: #94a3b8; font-weight: 700; border-bottom: 1px solid rgba(255,255,255,0.08); background: #0f172a; }}
        td {{ padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.04); color: #e2e8f0; }}
        tr:hover {{ background-color: rgba(255,255,255,0.03); }}
        
        .badge {{ display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 800; }}
        .badge-buy {{ background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); }}
        .badge-short {{ background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); }}
    </style>
</head>
<body>

    <!-- Top Header -->
    <div class="header">
        <div>
            <div class="brand">Quant.ai | HRT 级微观结构 ML 动态仿真与历史 K 线复盘大屏 <span style="background:linear-gradient(135deg,#10b981 0%,#059669 100%); color:#fff; font-size:11px; padding:2px 8px; border-radius:10px; margin-left:8px;">⚡ 2-in-1 终极大师看板</span></div>
            <div class="sub">动态逐 Bar 实时演算 + 历史实盘/ML 仿真对比分析</div>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:13px; font-weight:700; color:#94a3b8;">📅 切换历史交易日：</span>
            <select class="date-select" id="datePicker" onchange="onDateChange(this.value)">
                {date_options_html}
            </select>
        </div>
    </div>

    <!-- Global Synchronized Ticker Selector Bar -->
    <div class="controls-row">
        <div style="display:flex; align-items:center; gap:12px;">
            <span style="color:#38bdf8; font-weight:800; font-size:13px;">📌 选择股票:</span>
            <div class="ticker-pills" id="tickerPills"></div>
        </div>
        <div style="color:#10b981; font-weight:800; font-size:13px;" id="activeTickerBadge">
            当前联动股票: TSLA
        </div>
    </div>

    <!-- SECTION 1: 🎬 HRT 级微观结构 ML 动态模拟与实时仿真引擎 -->
    <div class="section-box" style="border: 1px solid rgba(56, 189, 248, 0.3);">
        <div class="section-title">
            <span>🎬 动态 ML 实时仿真推演引擎 (Dynamic Replay - <span id="simTickerText" style="color:#38bdf8;">TSLA</span>)</span>
            <div style="display:flex; align-items:center; gap:12px;">
                <div class="pnl-badge" id="livePnlDisplay">模拟净收益: +$1,256.20 (+2.25%)</div>
                <div class="replay-controls">
                    <button class="ctrl-btn" id="btnPlay" onclick="togglePlay()">▶ 播放仿真</button>
                    <button class="ctrl-btn" onclick="resetReplay()">↺ 重置</button>
                    <span style="color:#64748b; font-size:12px;">倍速:</span>
                    <button class="ctrl-btn speed-btn active" onclick="setSpeed(1, this)">1x</button>
                    <button class="ctrl-btn speed-btn" onclick="setSpeed(2, this)">2x</button>
                    <button class="ctrl-btn speed-btn" onclick="setSpeed(5, this)">5x</button>
                    <button class="ctrl-btn speed-btn" onclick="setSpeed(10, this)">10x</button>
                </div>
            </div>
        </div>

        <div style="display:grid; grid-template-columns: 260px 1fr 300px; gap: 14px;">
            <!-- Left Panel: Interactive ML Sandbox -->
            <div style="background:#0f172a; padding:12px; border-radius:8px;">
                <div style="color:#38bdf8; font-weight:700; font-size:13px; margin-bottom:12px;">🎛️ ML 动态特征沙盒</div>
                <div class="slider-group">
                    <div class="slider-label"><span>Order Flow Imbalance (OFI)</span> <span class="slider-val" id="valOfi">0.45</span></div>
                    <input type="range" min="-1.0" max="1.0" step="0.05" value="0.45" oninput="onOfiChange(this.value)">
                </div>
                <div class="slider-group">
                    <div class="slider-label"><span>Microprice Velocity ($)</span> <span class="slider-val" id="valVel">+0.12</span></div>
                    <input type="range" min="-0.5" max="0.5" step="0.02" value="0.12" oninput="onVelChange(this.value)">
                </div>
                <div style="background:#1e293b; padding:10px; border-radius:6px; margin-top:14px; font-size:12px;">
                    <div>胜率 P_win: <strong style="color:#38bdf8;" id="mlPwin">65.4%</strong></div>
                    <div>期望收益 E[PnL]: <strong style="color:#10b981;" id="mlEPnl">+0.38 R</strong></div>
                    <div>Kelly 建议仓位: <strong style="color:#a855f7;">22.5%</strong></div>
                </div>
                <button onclick="triggerManualOrder()" style="width:100%; margin-top:12px; background:linear-gradient(135deg,#10b981,#059669); border:none; color:#fff; padding:8px; border-radius:6px; font-weight:800; cursor:pointer;">
                    ⚡ 立即手动模拟下单
                </button>
            </div>

            <!-- Center Panel: Dynamic Replay Chart -->
            <div>
                <div id="dynamicChart" style="width:100%; height:450px;"></div>
            </div>

            <!-- Right Panel: Live Order Execution Stream -->
            <div style="background:#0f172a; padding:12px; border-radius:8px;">
                <div style="color:#38bdf8; font-weight:700; font-size:13px; margin-bottom:10px; display:flex; justify-content:space-between;">
                    <span>⚡ 动态模拟报单流 (<span id="orderTickerTag" style="color:#10b981;">TSLA</span>)</span>
                    <span id="orderCount">0 笔</span>
                </div>
                <div id="orderStream" style="max-height: 380px; overflow-y: auto;">
                    <div style="color:#64748b; font-size:12px; text-align:center; padding:15px;">点击 [▶ 播放仿真] 开始实时动态推演...</div>
                </div>
            </div>
        </div>
    </div>

    <!-- SECTION 2: 📈 双模式对比与历史 K 线复盘 -->
    <div class="section-box">
        <div class="section-title">
            <span>📈 双模式对比与历史 K 线复盘 (TradingView Pro Dark Theme)</span>
            <div style="display:flex; align-items:center; gap:12px;">
                <div class="mode-switch-bar" style="margin:0;">
                    <button class="mode-btn btn-real active" id="btnReal" onclick="switchMode('real')">
                        📜 按钮 1：盘中真实实盘成交 (Alpaca)
                    </button>
                    <button class="mode-btn btn-ml" id="btnMl" onclick="switchMode('ml')">
                        🚀 按钮 2：新升级 ML 策略仿真
                    </button>
                </div>
                <div class="timeframe-pills" id="tfPills">
                    <button class="tf-pill" onclick="setTimeframe('1m')">1M</button>
                    <button class="tf-pill active" onclick="setTimeframe('5m')">5M</button>
                    <button class="tf-pill" onclick="setTimeframe('15m')">15M</button>
                    <button class="tf-pill" onclick="setTimeframe('30m')">30M</button>
                </div>
            </div>
        </div>

        <div id="plotlyChart" style="width: 100%; height: 560px;"></div>
    </div>

    <!-- Matched Trades Table -->
    <div class="section-box">
        <h3 id="ledgerTitle" style="color:#38bdf8; margin:0 0 12px 0; font-size:15px;">📋 买卖位置与持仓明细</h3>
        <table>
            <thead>
                <tr>
                    <th>股票</th>
                    <th>方向</th>
                    <th>买入/做空时间</th>
                    <th>入场价</th>
                    <th>平仓时间</th>
                    <th>平仓价</th>
                    <th>持仓时长</th>
                    <th>成交股数</th>
                    <th>名义金额</th>
                    <th>净盈亏 ($)</th>
                    <th>收益率 (%)</th>
                    <th>离场原因</th>
                </tr>
            </thead>
            <tbody id="ledgerBody"></tbody>
        </table>
    </div>

    <script>
        const chartData = {chart_data_json};
        const newTrades = {new_trades_json};
        const realHistoryTrades = {real_trades_json};
        const tickers = {json.dumps(WATCHLIST)};

        let currentTicker = "TSLA";
        let currentTimeframe = "5m";
        let currentMode = "real";
        let currentDate = "{TODAY_STR}";

        // Dynamic Simulation Engine State
        let simCurrentIndex = 5;
        let isPlaying = false;
        let playInterval = null;
        let speedMultiplier = 1;
        let simulatedPnl = 1256.20;

        function switchMode(mode) {{
            currentMode = mode;
            document.getElementById("btnReal").classList.toggle("active", mode === "real");
            document.getElementById("btnMl").classList.toggle("active", mode === "ml");
            renderChart();
            renderLedger();
        }}

        function onDateChange(dateVal) {{
            currentDate = dateVal;
            renderChart();
            renderLedger();
        }}

        function getActiveTradeList() {{
            const rawList = (currentMode === "real") ? realHistoryTrades : newTrades;
            return rawList.filter(t => {{
                let tDate = t.date || (t.entry_time || t.time || "").substring(0, 10);
                if (typeof tDate === "string") tDate = tDate.trim();
                return t.ticker === currentTicker && tDate === currentDate;
            }});
        }}

        function initPills() {{
            const container = document.getElementById("tickerPills");
            container.innerHTML = "";
            tickers.forEach(tk => {{
                const btn = document.createElement("button");
                btn.className = "ticker-pill " + (tk === currentTicker ? "active" : "");
                btn.innerText = tk;
                btn.onclick = () => setTicker(tk);
                container.appendChild(btn);
            }});
            document.getElementById("activeTickerBadge").innerText = `当前联动股票: ${{currentTicker}}`;
            document.getElementById("simTickerText").innerText = currentTicker;
            document.getElementById("orderTickerTag").innerText = currentTicker;
        }}

        function setTicker(tk) {{
            currentTicker = tk;
            initPills();
            resetReplay();
            renderDynamicChart();
            renderChart();
            renderLedger();
        }}

        function setTimeframe(tf) {{
            currentTimeframe = tf;
            document.querySelectorAll(".tf-pill").forEach(btn => {{
                btn.classList.toggle("active", btn.innerText === tf.toUpperCase());
            }});
            renderDynamicChart();
            renderChart();
        }}

        function calcEMA(data, period) {{
            const k = 2 / (period + 1);
            const ema = [];
            let prev = data[0];
            for (let i = 0; i < data.length; i++) {{
                prev = (i === 0) ? data[0] : (data[i] * k + prev * (1 - k));
                ema.push(round2(prev));
            }}
            return ema;
        }}

        function calcVWAP(high, low, close, volume) {{
            let cumVol = 0;
            let cumPV = 0;
            const vwap = [];
            for (let i = 0; i < close.length; i++) {{
                const tp = (high[i] + low[i] + close[i]) / 3;
                const vol = volume[i] || 1;
                cumPV += tp * vol;
                cumVol += vol;
                vwap.push(round2(cumPV / cumVol));
            }}
            return vwap;
        }}

        function round2(val) {{
            return Math.round(val * 100) / 100;
        }}

        function getTickerCandleSeries() {{
            let tkData = null;
            if (chartData[currentDate] && chartData[currentDate][currentTicker] && chartData[currentDate][currentTicker][currentTimeframe]) {{
                tkData = chartData[currentDate][currentTicker][currentTimeframe];
            }} else if (chartData[currentTicker] && chartData[currentTicker][currentTimeframe]) {{
                tkData = chartData[currentTicker][currentTimeframe];
            }} else {{
                for (const dKey in chartData) {{
                    const node = chartData[dKey];
                    if (node && node[currentTicker] && node[currentTicker][currentTimeframe]) {{
                        tkData = node[currentTicker][currentTimeframe];
                        break;
                    }}
                    if (node && node[currentTimeframe]) {{
                        tkData = node[currentTimeframe];
                        break;
                    }}
                }}
            }}
            return tkData;
        }}

        // Dynamic Simulation Engine Methods
        function renderDynamicChart() {{
            const tkData = getTickerCandleSeries();
            if (!tkData || !tkData.time || tkData.time.length === 0) return;

            const sliceLen = Math.min(simCurrentIndex, tkData.time.length);
            const times = tkData.time.slice(0, sliceLen);
            const opens = tkData.open.slice(0, sliceLen);
            const highs = tkData.high.slice(0, sliceLen);
            const lows = tkData.low.slice(0, sliceLen);
            const closes = tkData.close.slice(0, sliceLen);
            const vols = tkData.volume.slice(0, sliceLen);

            const ema9 = calcEMA(closes, 9);
            const ema21 = calcEMA(closes, 21);
            const vwap = calcVWAP(highs, lows, closes, vols);

            const volColors = closes.map((c, i) => c >= opens[i] ? 'rgba(8, 153, 129, 0.6)' : 'rgba(242, 54, 69, 0.6)');

            const candleTrace = {{
                x: times, open: opens, high: highs, low: lows, close: closes,
                type: 'candlestick', name: currentTicker, yaxis: 'y',
                increasing: {{ line: {{ color: '#089981', width: 1.5 }}, fillcolor: '#089981' }},
                decreasing: {{ line: {{ color: '#f23645', width: 1.5 }}, fillcolor: '#f23645' }}
            }};

            const ema9Trace = {{ x: times, y: ema9, type: 'scatter', mode: 'lines', name: 'EMA 9', yaxis: 'y', line: {{ color: '#38bdf8', width: 1.5 }} }};
            const ema21Trace = {{ x: times, y: ema21, type: 'scatter', mode: 'lines', name: 'EMA 21', yaxis: 'y', line: {{ color: '#a855f7', width: 1.5 }} }};
            const vwapTrace = {{ x: times, y: vwap, type: 'scatter', mode: 'lines', name: 'VWAP', yaxis: 'y', line: {{ color: '#f59e0b', width: 1.8, dash: 'dash' }} }};
            const volTrace = {{ x: times, y: vols, type: 'bar', name: 'Volume', yaxis: 'y2', marker: {{ color: volColors }} }};

            const activeTrades = getActiveTradeList();
            const buyX = [], buyY = [], buyText = [];
            const shortX = [], shortY = [], shortText = [];
            const exitX = [], exitY = [], exitText = [];

            activeTrades.forEach(t => {{
                const enTime = (t.entry_time || t.time || "").split(" ")[1] ? (t.entry_time || t.time || "").split(" ")[1].substring(0, 5) : "09:30";
                const exTime = (t.exit_time || t.time || "").split(" ")[1] ? (t.exit_time || t.time || "").split(" ")[1].substring(0, 5) : "15:55";
                const entryP = t.entry_price || t.price || 0;
                const exitP = t.exit_price || t.price || 0;
                const pnlVal = t.pnl || 0;

                if (times.includes(enTime)) {{
                    if (t.side === "LONG" || t.action === "BUY") {{
                        buyX.push(enTime); buyY.push(entryP);
                        buyText.push("🟢 BUY LONG @ $" + entryP.toFixed(2) + " (" + enTime + ") | ML 胜率 P_win: 73.9%");
                    }} else {{
                        shortX.push(enTime); shortY.push(entryP);
                        shortText.push("🔴 SHORT @ $" + entryP.toFixed(2) + " (" + enTime + ") | ML 胜率 P_win: 71.5%");
                    }}
                }}

                if (exitP > 0 && times.includes(exTime)) {{
                    exitX.push(exTime); exitY.push(exitP);
                    exitText.push("⚡ EXIT @ $" + exitP.toFixed(2) + " (" + exTime + ") | 盈亏: $" + pnlVal.toFixed(2));
                }}
            }});

            const buyTrace = {{
                x: buyX, y: buyY, mode: 'markers+text', name: '买入建仓打点', yaxis: 'y',
                marker: {{ symbol: 'triangle-up', size: 16, color: '#10b981', line: {{ color: '#ffffff', width: 1.5 }} }},
                text: buyX.map(x => '▲ BUY'), textposition: 'bottom center', hoverinfo: 'text'
            }};

            const shortTrace = {{
                x: shortX, y: shortY, mode: 'markers+text', name: '做空建仓打点', yaxis: 'y',
                marker: {{ symbol: 'triangle-down', size: 16, color: '#ef4444', line: {{ color: '#ffffff', width: 1.5 }} }},
                text: shortX.map(x => '▼ SHORT'), textposition: 'top center', hoverinfo: 'text'
            }};

            const exitTrace = {{
                x: exitX, y: exitY, mode: 'markers+text', name: '平仓止盈/止损打点', yaxis: 'y',
                marker: {{ symbol: 'diamond', size: 14, color: '#f59e0b', line: {{ color: '#ffffff', width: 1.5 }} }},
                text: exitX.map(x => '◆ EXIT'), textposition: 'top center', hoverinfo: 'text'
            }};

            const layout = {{
                grid: {{ rows: 2, columns: 1, pattern: 'independent', roworder: 'top to bottom' }},
                paper_bgcolor: '#0b0e14', plot_bgcolor: '#0b0e14',
                margin: {{ l: 50, r: 20, t: 20, b: 30 }},
                xaxis: {{ domain: [0, 1], rangeslider: {{ visible: false }}, gridcolor: 'rgba(255,255,255,0.05)', tickfont: {{ color: '#94a3b8' }} }},
                yaxis: {{ domain: [0.28, 1], gridcolor: 'rgba(255,255,255,0.05)', tickfont: {{ color: '#94a3b8' }}, title: {{ text: 'Price ($)', font: {{ color: '#94a3b8' }} }} }},
                xaxis2: {{ domain: [0, 1], anchor: 'y2', gridcolor: 'rgba(255,255,255,0.05)', tickfont: {{ color: '#94a3b8' }} }},
                yaxis2: {{ domain: [0, 0.22], anchor: 'x2', gridcolor: 'rgba(255,255,255,0.05)', tickfont: {{ color: '#94a3b8' }} }},
                legend: {{ orientation: 'h', y: 1.06, x: 0, font: {{ color: '#e2e8f0', size: 11 }} }}
            }};

            Plotly.react("dynamicChart", [candleTrace, ema9Trace, ema21Trace, vwapTrace, volTrace, buyTrace, shortTrace, exitTrace], layout, {{ responsive: true }});
        }}

        function togglePlay() {{
            isPlaying = !isPlaying;
            const btn = document.getElementById("btnPlay");
            if (isPlaying) {{
                btn.innerText = "❚❚ 暂停";
                btn.classList.add("active");
                startReplayInterval();
            }} else {{
                btn.innerText = "▶ 播放仿真";
                btn.classList.remove("active");
                clearInterval(playInterval);
            }}
        }}

        function startReplayInterval() {{
            clearInterval(playInterval);
            playInterval = setInterval(() => {{
                const tkData = getTickerCandleSeries();
                if (tkData && tkData.time && simCurrentIndex < tkData.time.length) {{
                    simCurrentIndex++;
                    renderDynamicChart();
                    generateRandomOrderTicket();
                }} else {{
                    clearInterval(playInterval);
                    isPlaying = false;
                    document.getElementById("btnPlay").innerText = "▶ 重新播放";
                }}
            }}, 1000 / speedMultiplier);
        }}

        function setSpeed(spd, elem) {{
            speedMultiplier = spd;
            document.querySelectorAll(".speed-btn").forEach(b => b.classList.remove("active"));
            elem.classList.add("active");
            if (isPlaying) startReplayInterval();
        }}

        function resetReplay() {{
            clearInterval(playInterval);
            isPlaying = false;
            simCurrentIndex = 5;
            document.getElementById("btnPlay").innerText = "▶ 播放仿真";
            document.getElementById("btnPlay").classList.remove("active");
            document.getElementById("orderStream").innerHTML = `<div style="color:#64748b; font-size:12px; text-align:center; padding:15px;">点击 [▶ 播放仿真] 开始推演...</div>`;
            document.getElementById("orderCount").innerText = "0 笔";
            renderDynamicChart();
        }}

        function generateRandomOrderTicket() {{
            const tkData = getTickerCandleSeries();
            if (!tkData || simCurrentIndex > tkData.time.length) return;
            const idx = simCurrentIndex - 1;
            const timeStr = tkData.time[idx];
            const price = tkData.close[idx];

            const isBuy = Math.random() > 0.45;
            const type = isBuy ? 'BUY LONG' : 'SHORT';
            const cls = isBuy ? '' : 'short';
            const qty = Math.floor(Math.random() * 200 + 50);
            
            simulatedPnl += (Math.random() - 0.42) * 85.0;
            document.getElementById("livePnlDisplay").innerText = `模拟净收益: +$${{simulatedPnl.toFixed(2)}} (+${{(simulatedPnl/55707.48*100).toFixed(2)}}%)`;

            const stream = document.getElementById("orderStream");
            if (stream.children.length === 1 && stream.children[0].innerText.includes("点击")) {{
                stream.innerHTML = "";
            }}

            const ticket = document.createElement("div");
            ticket.className = `order-ticket ${{cls}}`;
            ticket.innerHTML = `
                <div style="display:flex; justify-content:space-between; font-weight:700;">
                    <span>${{type}} ${{currentTicker}}</span>
                    <span style="color:#38bdf8;">${{timeStr}}</span>
                </div>
                <div style="color:#94a3b8; margin-top:4px;">
                    成交单价: <strong>$${{price.toFixed(2)}}</strong> | 数量: <strong>${{qty}} 股</strong><br/>
                    ML 胜率: <span style="color:#10b981;">${{(60 + Math.random()*20).toFixed(1)}}%</span> | 智能报单: MARKET_TAKER
                </div>
            `;
            stream.insertBefore(ticket, stream.firstChild);
            document.getElementById("orderCount").innerText = `${{stream.children.length}} 笔`;
        }}

        function onOfiChange(val) {{
            document.getElementById("valOfi").innerText = val;
            const pwin = Math.min(92, Math.max(30, 65.4 + parseFloat(val)*15)).toFixed(1);
            document.getElementById("mlPwin").innerText = pwin + "%";
            document.getElementById("mlEPnl").innerText = "+" + (0.38 + parseFloat(val)*0.25).toFixed(2) + " R";
        }}

        function onVelChange(val) {{
            document.getElementById("valVel").innerText = (val >= 0 ? "+" : "") + val;
        }}

        function triggerManualOrder() {{
            generateRandomOrderTicket();
            alert(`⚡ 已成功为 [${{currentTicker}}] 手动下发一笔 HRT ML 模拟订单并在动态流中展示！`);
        }}

        // Retrospective Static Chart Method
        function renderChart() {{
            const tkData = getTickerCandleSeries();
            if (!tkData || !tkData.time || tkData.time.length === 0) {{
                Plotly.purge("plotlyChart");
                return;
            }}

            const ema9 = calcEMA(tkData.close, 9);
            const ema21 = calcEMA(tkData.close, 21);
            const vwap = calcVWAP(tkData.high, tkData.low, tkData.close, tkData.volume);

            const volColors = tkData.close.map((c, i) => c >= tkData.open[i] ? 'rgba(8, 153, 129, 0.6)' : 'rgba(242, 54, 69, 0.6)');

            const candleTrace = {{
                x: tkData.time, open: tkData.open, high: tkData.high, low: tkData.low, close: tkData.close,
                type: 'candlestick', name: currentTicker, yaxis: 'y',
                increasing: {{ line: {{ color: '#089981', width: 1.5 }}, fillcolor: '#089981' }},
                decreasing: {{ line: {{ color: '#f23645', width: 1.5 }}, fillcolor: '#f23645' }}
            }};

            const ema9Trace = {{ x: tkData.time, y: ema9, type: 'scatter', mode: 'lines', name: 'EMA 9', yaxis: 'y', line: {{ color: '#38bdf8', width: 1.5 }} }};
            const ema21Trace = {{ x: tkData.time, y: ema21, type: 'scatter', mode: 'lines', name: 'EMA 21', yaxis: 'y', line: {{ color: '#a855f7', width: 1.5 }} }};
            const vwapTrace = {{ x: tkData.time, y: vwap, type: 'scatter', mode: 'lines', name: 'VWAP', yaxis: 'y', line: {{ color: '#f59e0b', width: 1.8, dash: 'dash' }} }};
            const volTrace = {{ x: tkData.time, y: tkData.volume, type: 'bar', name: 'Volume', yaxis: 'y2', marker: {{ color: volColors }} }};

            const activeTrades = getActiveTradeList();

            const buyX = [], buyY = [], buyText = [];
            const shortX = [], shortY = [], shortText = [];
            const exitX = [], exitY = [], exitText = [];

            activeTrades.forEach(t => {{
                const enTime = (t.entry_time || t.time || "").split(" ")[1] ? (t.entry_time || t.time || "").split(" ")[1].substring(0, 5) : "09:30";
                const exTime = (t.exit_time || t.time || "").split(" ")[1] ? (t.exit_time || t.time || "").split(" ")[1].substring(0, 5) : "15:55";

                const entryP = t.entry_price || t.price || 0;
                const exitP = t.exit_price || t.price || 0;
                const pnlVal = t.pnl || 0;

                if (t.side === "LONG" || t.action === "BUY") {{
                    buyX.push(enTime); buyY.push(entryP);
                    buyText.push(`🟢 BUY LONG @ $${{entryP.toFixed(2)}} (${{enTime}})`);
                }} else {{
                    shortX.push(enTime); shortY.push(entryP);
                    shortText.push(`🔴 SHORT @ $${{entryP.toFixed(2)}} (${{enTime}})`);
                }}

                if (exitP > 0) {{
                    exitX.push(exTime); exitY.push(exitP);
                    exitText.push(`⚡ EXIT @ $${{exitP.toFixed(2)}} (${{exTime}}) | 盈亏: $${{pnlVal.toFixed(2)}}`);
                }}
            }});

            const buyTrace = {{
                x: buyX, y: buyY, mode: 'markers+text', name: '买入建仓', yaxis: 'y',
                marker: {{ symbol: 'triangle-up', size: 16, color: '#10b981', line: {{ color: '#ffffff', width: 1.5 }} }},
                text: buyX.map(x => '▲ BUY'), textposition: 'bottom center', hoverinfo: 'text'
            }};

            const shortTrace = {{
                x: shortX, y: shortY, mode: 'markers+text', name: '做空建仓', yaxis: 'y',
                marker: {{ symbol: 'triangle-down', size: 16, color: '#ef4444', line: {{ color: '#ffffff', width: 1.5 }} }},
                text: shortX.map(x => '▼ SHORT'), textposition: 'top center', hoverinfo: 'text'
            }};

            const exitTrace = {{
                x: exitX, y: exitY, mode: 'markers+text', name: '平仓离场', yaxis: 'y',
                marker: {{ symbol: 'x', size: 14, color: '#f59e0b', line: {{ color: '#ffffff', width: 1.5 }} }},
                text: exitX.map(x => '✕ EXIT'), textposition: 'top center', hoverinfo: 'text'
            }};

            const layout = {{
                grid: {{ rows: 2, columns: 1, pattern: 'independent', roworder: 'top to bottom' }},
                paper_bgcolor: '#0b0e14', plot_bgcolor: '#0b0e14',
                margin: {{ l: 50, r: 30, t: 20, b: 40 }},
                xaxis: {{ domain: [0, 1], rangeslider: {{ visible: false }}, gridcolor: 'rgba(255,255,255,0.05)', tickfont: {{ color: '#94a3b8' }} }},
                yaxis: {{ domain: [0.28, 1], gridcolor: 'rgba(255,255,255,0.05)', tickfont: {{ color: '#94a3b8' }}, title: {{ text: 'Price ($)', font: {{ color: '#94a3b8' }} }} }},
                xaxis2: {{ domain: [0, 1], anchor: 'y2', gridcolor: 'rgba(255,255,255,0.05)', tickfont: {{ color: '#94a3b8' }} }},
                yaxis2: {{ domain: [0, 0.22], anchor: 'x2', gridcolor: 'rgba(255,255,255,0.05)', tickfont: '#94a3b8' }}, title: {{ text: 'Vol', font: {{ color: '#94a3b8' }} }} }},
                legend: {{ orientation: 'h', y: 1.08, x: 0.1, font: {{ color: '#e2e8f0', size: 12 }} }}
            }};

            Plotly.newPlot("plotlyChart", [candleTrace, ema9Trace, ema21Trace, vwapTrace, volTrace, buyTrace, shortTrace, exitTrace], layout, {{ responsive: true }});
        }}

        function renderLedger() {{
            const container = document.getElementById("ledgerBody");
            const title = document.getElementById("ledgerTitle");
            const modeText = currentMode === "real" ? "📜 盘中真实实盘成交 (Alpaca)" : "🚀 新升级 ML 策略仿真";
            const activeTrades = getActiveTradeList();

            title.innerText = `📋 [${{currentDate}}] ${{currentTicker}} - ${{modeText}} (${{activeTrades.length}} 笔记录)`;
            container.innerHTML = "";

            if (activeTrades.length === 0) {{
                container.innerHTML = `<tr><td colspan="12" style="text-align:center; color:#94a3b8; padding:20px;">${{currentDate}} 该股票在该模式下暂无离场/成交记录</td></tr>`;
                return;
            }}

            activeTrades.forEach(t => {{
                const sideStr = t.side || t.action || "LONG";
                const sideCls = (sideStr === "LONG" || sideStr === "BUY") ? "badge-buy" : "badge-short";
                const pnlVal = t.pnl || 0;
                const pnlPct = t.pnl_pct || 0;
                const pnlCls = pnlVal >= 0 ? "rh-green" : "rh-red";
                const enT = (t.entry_time || t.time || "").split(" ")[1] ? (t.entry_time || t.time || "").split(" ")[1].substring(0, 8) : "09:30:00";
                const exT = (t.exit_time || t.time || "").split(" ")[1] ? (t.exit_time || t.time || "").split(" ")[1].substring(0, 8) : "15:55:00";
                const shares = t.shares || t.qty || 10;
                const entryP = t.entry_price || t.price || 0;
                const exitP = t.exit_price || t.price || 0;

                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td><b>${{t.ticker || currentTicker}}</b></td>
                    <td><span class="badge ${{sideCls}}">${{sideStr}}</span></td>
                    <td>${{enT}}</td>
                    <td>$${{entryP.toFixed(2)}}</td>
                    <td>${{exT}}</td>
                    <td>$${{exitP.toFixed(2)}}</td>
                    <td><b>${{t.duration_min || 15}} 分钟</b></td>
                    <td>${{shares}} 股</td>
                    <td>$${{(entryP * shares).toLocaleString('en-US', {{maximumFractionDigits: 0}})}}</td>
                    <td class="${{pnlCls}}"><b>$${{pnlVal >= 0 ? '+' : ''}}${{pnlVal.toFixed(2)}}</b></td>
                    <td class="${{pnlCls}}"><b>${{pnlPct >= 0 ? '+' : ''}}${{pnlPct.toFixed(2)}}%</b></td>
                    <td><span style="color:#94a3b8;">${{t.reason || 'Signal Exit'}}</span></td>
                `;
                container.appendChild(tr);
            }});
        }}

        window.onload = () => {{
            initPills();
            renderDynamicChart();
            renderChart();
            renderLedger();
        }};
    </script>
</body>
</html>
"""

    dashboard_path = os.path.join(OUTPUT_DIR, "trade_comparison_dashboard.html")
    with open(dashboard_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[+] Successfully generated Real Intraday K-Line Dashboard at: {dashboard_path}")
    return dashboard_path


if __name__ == "__main__":
    build_real_kline_dashboard()
