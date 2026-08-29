# backend/data/generate_dynamic_ml_simulation_html.py
"""
Dynamic Interactive HRT ML Trading Replay & Feature Sandbox Engine Generator.
Features:
1. Animated Bar-by-Bar / Tick-by-Tick Replay with Play/Pause/Speed (1x, 2x, 5x, 10x) controls.
2. Dynamic TradingView-style dark mode candlestick chart (#0b0e14).
3. Real-time dynamic PnL & equity counter updating as trades execute.
4. Interactive HRT Feature Sandboxes (OFI slider, Microprice Velocity slider, Volatility multiplier).
5. Animated Order Execution Log popping up live order tickets.
"""

import os
import sys
import json
import datetime
import pandas as pd
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "charts")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_dynamic_simulation_html():
    # Build 5m intraday candle sequence for replay
    times = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in range(0, 60, 5) if not (h == 9 and m < 30)]
    
    np.random.seed(42)
    base_price = 345.0
    price_path = [base_price]
    for i in range(1, len(times)):
        ret = np.random.normal(0.0003, 0.0025)
        price_path.append(round(price_path[-1] * (1.0 + ret), 2))
        
    candles = []
    for i, t in enumerate(times):
        p = price_path[i]
        variation = round(np.random.uniform(0.3, 1.2), 2)
        op = round(p - np.random.uniform(-0.4, 0.4), 2)
        cl = p
        hi = max(op, cl) + variation
        lo = min(op, cl) - variation
        vol = int(np.random.uniform(5000, 35000))
        candles.append({
            "time": t, "open": op, "high": hi, "low": lo, "close": cl, "volume": vol
        })

    candles_json = json.dumps(candles)

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant.ai - 动态 HRT ML 实时仿真引擎大屏</title>
    <script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        * {{ box-sizing: border-box; font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }}
        body {{ background-color: #0b0e14; color: #e2e8f0; margin: 0; padding: 20px; }}
        
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 16px; margin-bottom: 20px; }}
        .title {{ font-size: 20px; font-weight: 800; color: #38bdf8; display: flex; align-items: center; gap: 10px; }}
        .pnl-badge {{ background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: #10b981; padding: 6px 16px; border-radius: 8px; font-weight: 800; font-size: 18px; }}
        
        .replay-controls {{ display: flex; align-items: center; gap: 8px; background: #131722; padding: 6px 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); }}
        .ctrl-btn {{ padding: 6px 14px; border-radius: 6px; border: none; font-weight: 700; font-size: 13px; cursor: pointer; transition: all 0.2s ease; background: #1e293b; color: #fff; }}
        .ctrl-btn:hover {{ background: #0284c7; }}
        .ctrl-btn.active {{ background: #10b981; color: #fff; }}
        
        .dashboard-grid {{ display: grid; grid-template-columns: 280px 1fr 320px; gap: 16px; }}
        .card {{ background: #131722; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.3); }}
        .card-title {{ font-size: 14px; font-weight: 700; color: #38bdf8; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; }}
        
        .slider-group {{ margin-bottom: 16px; }}
        .slider-label {{ font-size: 12px; color: #94a3b8; margin-bottom: 6px; display: flex; justify-content: space-between; }}
        .slider-val {{ color: #38bdf8; font-weight: 700; }}
        input[type=range] {{ width: 100%; cursor: pointer; accent-color: #0284c7; }}

        .order-ticket {{ background: #0f172a; border-left: 4px solid #10b981; padding: 10px; border-radius: 6px; margin-bottom: 8px; font-size: 12px; animation: fadeIn 0.3s ease; }}
        .order-ticket.short {{ border-left-color: #ef4444; }}
        .order-ticket.exit {{ border-left-color: #f59e0b; }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(-5px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    </style>
</head>
<body>

    <div class="header">
        <div>
            <div class="title">🎬 Quant.ai | HRT 级微观结构 ML 动态模拟与实时仿真引擎</div>
            <div style="font-size: 13px; color: #94a3b8; margin-top: 4px;">K 线逐 Bar 动态演算 · ML 信号实时打点 · 订单流秒级仿真</div>
        </div>
        <div style="display:flex; align-items:center; gap:16px;">
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

    <div class="dashboard-grid">
        <!-- Left Panel: Interactive ML Feature Sandbox -->
        <div class="card">
            <div class="card-title">🎛️ HRT ML 动态调参沙盒</div>
            
            <div class="slider-group">
                <div class="slider-label"><span>Order Flow Imbalance (OFI)</span> <span class="slider-val" id="valOfi">0.45</span></div>
                <input type="range" min="-1.0" max="1.0" step="0.05" value="0.45" oninput="onOfiChange(this.value)">
            </div>

            <div class="slider-group">
                <div class="slider-label"><span>Microprice Velocity ($)</span> <span class="slider-val" id="valVel">+0.12</span></div>
                <input type="range" min="-0.5" max="0.5" step="0.02" value="0.12" oninput="onVelChange(this.value)">
            </div>

            <div class="slider-group">
                <div class="slider-label"><span>LOB Queue Toxicity (VPIN)</span> <span class="slider-val" id="valVpin">0.18</span></div>
                <input type="range" min="0.0" max="1.0" step="0.05" value="0.18" oninput="document.getElementById('valVpin').innerText=this.value">
            </div>

            <div style="background:#0f172a; padding:12px; border-radius:8px; margin-top:20px; font-size:12px;">
                <div style="color:#94a3b8; font-weight:700;">实时 ML 推理诊断</div>
                <div style="margin-top:6px;">模型胜率 P_win: <strong style="color:#38bdf8;" id="mlPwin">65.4%</strong></div>
                <div>数学期望 E[PnL]: <strong style="color:#10b981;" id="mlEPnl">+0.38 R</strong></div>
                <div>Kelly 推荐仓位: <strong style="color:#a855f7;" id="mlKelly">22.5%</strong></div>
            </div>
            
            <button onclick="triggerManualOrder()" style="width:100%; margin-top:16px; background:linear-gradient(135deg,#10b981,#059669); border:none; color:#fff; padding:10px; border-radius:6px; font-weight:800; cursor:pointer;">
                ⚡ 立即手动模拟下单
            </button>
        </div>

        <!-- Center Panel: Dynamic Replay Candlestick Chart -->
        <div class="card" style="padding:10px;">
            <div id="dynamicChart" style="width:100%; height:580px;"></div>
        </div>

        <!-- Right Panel: Live Dynamic Order Execution Stream -->
        <div class="card">
            <div class="card-title">
                <span>⚡ 动态模拟报单流 (Live Stream)</span>
                <span style="font-size:11px; background:#0284c7; color:#fff; padding:2px 6px; borderRadius:4px;" id="orderCount">0 笔</span>
            </div>
            <div id="orderStream" style="max-height: 520px; overflow-y: auto;">
                <div style="color:#64748b; font-size:12px; text-align:center; padding:20px;">点击 [▶ 播放仿真] 开始实时动态推演...</div>
            </div>
        </div>
    </div>

    <script>
        const fullCandles = {candles_json};
        let currentIndex = 5;
        let isPlaying = false;
        let playInterval = null;
        let speedMultiplier = 1;
        let simulatedPnl = 1256.20;

        function calcEMA(data, period) {{
            const k = 2 / (period + 1);
            const ema = [];
            let prev = data[0];
            for (let i = 0; i < data.length; i++) {{
                prev = (i === 0) ? data[0] : (data[i] * k + prev * (1 - k));
                ema.push(Math.round(prev * 100) / 100);
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
                vwap.push(Math.round((cumPV / cumVol) * 100) / 100);
            }}
            return vwap;
        }}

        function renderDynamicChart() {{
            const currentCandles = fullCandles.slice(0, currentIndex);
            const times = currentCandles.map(c => c.time);
            const opens = currentCandles.map(c => c.open);
            const highs = currentCandles.map(c => c.high);
            const lows = currentCandles.map(c => c.low);
            const closes = currentCandles.map(c => c.close);
            const vols = currentCandles.map(c => c.volume);

            const ema9 = calcEMA(closes, 9);
            const ema21 = calcEMA(closes, 21);
            const vwap = calcVWAP(highs, lows, closes, vols);

            const volColors = closes.map((c, i) => c >= opens[i] ? 'rgba(8, 153, 129, 0.6)' : 'rgba(242, 54, 69, 0.6)');

            const candleTrace = {{
                x: times, open: opens, high: highs, low: lows, close: closes,
                type: 'candlestick', name: 'TSLA', yaxis: 'y',
                increasing: {{ line: {{ color: '#089981', width: 1.5 }}, fillcolor: '#089981' }},
                decreasing: {{ line: {{ color: '#f23645', width: 1.5 }}, fillcolor: '#f23645' }}
            }};

            const ema9Trace = {{ x: times, y: ema9, type: 'scatter', mode: 'lines', name: 'EMA 9', yaxis: 'y', line: {{ color: '#38bdf8', width: 1.5 }} }};
            const ema21Trace = {{ x: times, y: ema21, type: 'scatter', mode: 'lines', name: 'EMA 21', yaxis: 'y', line: {{ color: '#a855f7', width: 1.5 }} }};
            const vwapTrace = {{ x: times, y: vwap, type: 'scatter', mode: 'lines', name: 'VWAP', yaxis: 'y', line: {{ color: '#f59e0b', width: 1.8, dash: 'dash' }} }};
            const volTrace = {{ x: times, y: vols, type: 'bar', name: 'Volume', yaxis: 'y2', marker: {{ color: volColors }} }};

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

            Plotly.react("dynamicChart", [candleTrace, ema9Trace, ema21Trace, vwapTrace, volTrace], layout, {{ responsive: true }});
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
                if (currentIndex < fullCandles.length) {{
                    currentIndex++;
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
            currentIndex = 5;
            document.getElementById("btnPlay").innerText = "▶ 播放仿真";
            document.getElementById("btnPlay").classList.remove("active");
            document.getElementById("orderStream").innerHTML = "";
            renderDynamicChart();
        }}

        function generateRandomOrderTicket() {{
            const c = fullCandles[currentIndex - 1];
            if (!c) return;
            const isBuy = Math.random() > 0.45;
            const type = isBuy ? 'BUY LONG' : 'SHORT';
            const cls = isBuy ? '' : 'short';
            const price = c.close;
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
                    <span>${{type}} TSLA</span>
                    <span style="color:#38bdf8;">${{c.time}}</span>
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
            alert("⚡ 已手动下发一笔 HRT ML 模拟订单并在交易流中实时展示！");
        }}

        window.onload = () => {{
            renderDynamicChart();
        }};
    </script>
</body>
</html>
"""

    dash_path = os.path.join(OUTPUT_DIR, "dynamic_ml_simulation_replay.html")
    with open(dash_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"SUCCESS: Generated Dynamic ML Simulation HTML at {dash_path}")

if __name__ == "__main__":
    generate_dynamic_simulation_html()
