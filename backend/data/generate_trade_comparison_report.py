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

WATCHLIST = ["SNDK", "TSLA", "MSTR", "NVDA"]

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
    target_dates = ["2026-08-26", "2026-08-12", "2026-08-11", "2026-08-10", "2026-08-07", "2026-08-06", "2026-08-05", "2026-08-04", "2026-07-31", "2026-07-30"]

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
    print("[*] Running strategy simulation for today...")
    new_trades = run_full_simulation()

    print("[*] Fetching REAL intraday K-lines (1m, 5m, 15m, 30m) for all tickers...")
    chart_data = prepare_real_kline_data()

    # Load Real Execution History from trade_history.json
    real_history_trades = []
    trade_hist_file = os.path.join(BASE_DIR, "trade_history.json")
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

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant.ai - 双模式对比与历史 K 线复盘看板</title>
    <script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        * {{ box-sizing: border-box; font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }}
        body {{ background-color: #ffffff; color: #0f1419; margin: 0; padding: 24px; }}
        
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 1px solid #e1e8ed; padding-bottom: 16px; flex-wrap: wrap; gap: 12px; }}
        .header .brand {{ font-size: 22px; font-weight: 700; color: #0f1419; letter-spacing: -0.5px; }}
        .header .sub {{ color: #536471; font-size: 13px; margin-top: 4px; }}
        
        .date-select {{ padding: 6px 14px; border-radius: 12px; border: 1px solid #cfd9de; font-weight: 600; font-size: 13px; color: #0f1419; background: #f7f9fa; cursor: pointer; outline: none; }}

        .mode-switch-bar {{ display: flex; gap: 12px; margin-bottom: 20px; background: #f0f3f5; padding: 6px; border-radius: 16px; border: 1px solid #e1e8ed; width: fit-content; }}
        .mode-btn {{ padding: 10px 20px; border-radius: 12px; border: none; font-weight: 700; font-size: 13px; cursor: pointer; transition: all 0.2s ease; display: flex; align-items: center; gap: 6px; }}
        .mode-btn.btn-real {{ background: transparent; color: #536471; }}
        .mode-btn.btn-real.active {{ background: #ffffff; color: #0f1419; box-shadow: 0 2px 6px rgba(0,0,0,0.1); border: 1px solid #cfd9de; }}
        .mode-btn.btn-ml {{ background: transparent; color: #536471; }}
        .mode-btn.btn-ml.active {{ background: #1d9bf0; color: #ffffff; box-shadow: 0 2px 6px rgba(29,155,240,0.3); }}

        .controls-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }}
        .ticker-pills {{ display: flex; gap: 8px; flex-wrap: wrap; }}
        .ticker-pill {{ padding: 8px 16px; border-radius: 20px; border: 1px solid #e1e8ed; background: #ffffff; color: #0f1419; font-weight: 600; font-size: 13px; cursor: pointer; transition: all 0.2s ease; }}
        .ticker-pill:hover {{ background: #f7f9fa; border-color: #cfd9de; }}
        .ticker-pill.active {{ background: #0f1419; color: #ffffff; border-color: #0f1419; }}
        
        .timeframe-pills {{ display: flex; background: #f7f9fa; border-radius: 20px; padding: 4px; border: 1px solid #e1e8ed; }}
        .tf-pill {{ padding: 6px 14px; border-radius: 16px; border: none; background: transparent; color: #536471; font-weight: 600; font-size: 13px; cursor: pointer; transition: all 0.2s ease; }}
        .tf-pill.active {{ background: #ffffff; color: #00c805; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        
        .rh-green {{ color: #00c805; }}
        .rh-red {{ color: #ff5000; }}
        
        .section-box {{ background: #ffffff; border: 1px solid #e1e8ed; border-radius: 12px; padding: 20px; margin-bottom: 24px; box-shadow: 0 2px 6px rgba(0,0,0,0.02); }}
        .section-box h3 {{ font-size: 16px; font-weight: 700; margin: 0 0 16px 0; color: #0f1419; }}
        
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ text-align: left; padding: 12px; color: #536471; font-weight: 600; border-bottom: 1px solid #e1e8ed; background: #f7f9fa; }}
        td {{ padding: 12px; border-bottom: 1px solid #f0f3f5; color: #0f1419; }}
        tr:hover {{ background-color: #f7f9fa; }}
        
        .badge {{ display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 700; }}
        .badge-buy {{ background: rgba(0, 200, 5, 0.12); color: #00c805; }}
        .badge-short {{ background: rgba(255, 80, 0, 0.12); color: #ff5000; }}
    </style>
</head>
<body>

    <div class="header">
        <div>
            <div class="brand">Quant.ai | 双模式对比与历史 K 线复盘</div>
            <div class="sub">对比模式：实盘成交流水 vs 新升级 ML 策略仿真回测</div>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-size:13px; font-weight:600; color:#536471;">📅 切换历史交易日：</span>
            <select class="date-select" id="datePicker" onchange="onDateChange(this.value)">
                <option value="2026-08-26" selected>2026-08-26 (今日美东)</option>
                <option value="2026-08-12">2026-08-12</option>
                <option value="2026-08-11">2026-08-11</option>
                <option value="2026-08-10">2026-08-10</option>
                <option value="2026-08-07">2026-08-07</option>
                <option value="2026-08-06">2026-08-06</option>
                <option value="2026-08-05">2026-08-05</option>
                <option value="2026-08-04">2026-08-04</option>
                <option value="2026-07-31">2026-07-31</option>
                <option value="2026-07-30">2026-07-30</option>
            </select>
        </div>
    </div>

    <!-- Dual Mode Switcher Bar -->
    <div class="mode-switch-bar">
        <button class="mode-btn btn-real active" id="btnReal" onclick="switchMode('real')">
            📜 按钮 1：盘中真实实盘成交记录 (Alpaca Real History)
        </button>
        <button class="mode-btn btn-ml" id="btnMl" onclick="switchMode('ml')">
            🚀 按钮 2：新升级 ML 策略仿真回测 (New ML Logic Simulation)
        </button>
    </div>

    <!-- Ticker & Timeframe Switchers -->
    <div class="controls-row">
        <div class="ticker-pills" id="tickerPills"></div>
        <div class="timeframe-pills" id="tfPills">
            <button class="tf-pill active" onclick="setTimeframe('1m')">1M</button>
            <button class="tf-pill" onclick="setTimeframe('5m')">5M</button>
            <button class="tf-pill" onclick="setTimeframe('15m')">15M</button>
            <button class="tf-pill" onclick="setTimeframe('30m')">30M</button>
        </div>
    </div>

    <!-- Real Plotly Candlestick Chart -->
    <div class="section-box">
        <div id="plotlyChart" style="width: 100%; height: 560px;"></div>
    </div>

    <!-- Matched Trades Table -->
    <div class="section-box">
        <h3 id="ledgerTitle">📋 买卖位置与持仓明细</h3>
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

        let currentTicker = "SNDK";
        let currentTimeframe = "1m";
        let currentMode = "ml"; // Default to ML Simulation for instant full trade markers
        let currentDate = "2026-08-26";

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
        }}

        function setTicker(tk) {{
            currentTicker = tk;
            initPills();
            renderChart();
            renderLedger();
        }}

        function setTimeframe(tf) {{
            currentTimeframe = tf;
            document.querySelectorAll(".tf-pill").forEach(btn => {{
                btn.classList.toggle("active", btn.innerText === tf.toUpperCase());
            }});
            renderChart();
        }}

        function renderChart() {{
            let tkData = (chartData[currentDate] && chartData[currentDate][currentTicker] && chartData[currentDate][currentTicker][currentTimeframe]) || (chartData[currentTicker] && chartData[currentTicker][currentTimeframe]);
            if (!tkData || !tkData.time || tkData.time.length === 0) {{
                // Fallback: search across dates if date not exact match
                for (const dKey in chartData) {{
                    if (chartData[dKey] && chartData[dKey][currentTicker] && chartData[dKey][currentTicker][currentTimeframe]) {{
                        tkData = chartData[dKey][currentTicker][currentTimeframe];
                        break;
                    }}
                }}
            }}

            if (!tkData || !tkData.time || tkData.time.length === 0) {{
                Plotly.purge("plotlyChart");
                return;
            }}

            const candleTrace = {{
                x: tkData.time,
                open: tkData.open,
                high: tkData.high,
                low: tkData.low,
                close: tkData.close,
                type: 'candlestick',
                name: currentTicker,
                increasing: {{ line: {{ color: '#00c805', width: 1.5 }}, fillcolor: '#00c805' }},
                decreasing: {{ line: {{ color: '#ff5000', width: 1.5 }}, fillcolor: '#ff5000' }}
            }};

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
                    buyX.push(enTime);
                    buyY.push(entryP);
                    buyText.push(`🛒 BUY LONG @ $${{entryP.toFixed(2)}} (${{enTime}})`);
                }} else {{
                    shortX.push(enTime);
                    shortY.push(entryP);
                    shortText.push(`📉 SHORT @ $${{entryP.toFixed(2)}} (${{enTime}})`);
                }}

                if (exitP > 0) {{
                    exitX.push(exTime);
                    exitY.push(exitP);
                    exitText.push(`🔴 EXIT @ $${{exitP.toFixed(2)}} (${{exTime}}) | 盈亏: $${{pnlVal.toFixed(2)}}`);
                }}
            }});

            const buyTrace = {{
                x: buyX, y: buyY, mode: 'markers', name: '买入/建仓',
                marker: {{ symbol: 'triangle-up', size: 14, color: '#00c805' }},
                text: buyText, hoverinfo: 'text'
            }};

            const shortTrace = {{
                x: shortX, y: shortY, mode: 'markers', name: '做空',
                marker: {{ symbol: 'triangle-down', size: 14, color: '#9333ea' }},
                text: shortText, hoverinfo: 'text'
            }};

            const exitTrace = {{
                x: exitX, y: exitY, mode: 'markers', name: '平仓出局',
                marker: {{ symbol: 'x', size: 12, color: '#ff5000' }},
                text: exitText, hoverinfo: 'text'
            }};

            const layout = {{
                paper_bgcolor: '#ffffff',
                plot_bgcolor: '#ffffff',
                margin: {{ l: 50, r: 30, t: 20, b: 40 }},
                xaxis: {{
                    rangeslider: {{ visible: false }},
                    gridcolor: '#f0f3f5',
                    linecolor: '#e1e8ed',
                    tickfont: {{ color: '#536471' }}
                }},
                yaxis: {{
                    gridcolor: '#f0f3f5',
                    linecolor: '#e1e8ed',
                    tickfont: {{ color: '#536471' }}
                }},
                legend: {{ orientation: 'h', y: 1.15, x: 0.3, font: {{ color: '#0f1419' }} }}
            }};

            Plotly.newPlot("plotlyChart", [candleTrace, buyTrace, shortTrace, exitTrace], layout, {{ responsive: true }});
        }}

        function renderLedger() {{
            const container = document.getElementById("ledgerBody");
            const title = document.getElementById("ledgerTitle");
            const modeText = currentMode === "real" ? "📜 按钮 1：盘中真实实盘成交流水" : "🚀 按钮 2：新升级 ML 策略仿真回测";
            const activeTrades = getActiveTradeList();

            title.innerText = `📋 [${{currentDate}}] ${{currentTicker}} - ${{modeText}} (${{activeTrades.length}} 笔记录)`;
            container.innerHTML = "";

            if (activeTrades.length === 0) {{
                container.innerHTML = `<tr><td colspan="12" style="text-align:center; color:#536471; padding:20px;">${{currentDate}} 该股票在该模式下暂无离场/成交记录</td></tr>`;
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
                    <td><span style="color:#536471;">${{t.reason || 'Signal Exit'}}</span></td>
                `;
                container.appendChild(tr);
            }});
        }}

        window.onload = () => {{
            initPills();
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
