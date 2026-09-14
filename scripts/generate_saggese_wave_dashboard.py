#!/usr/bin/env python3
"""Render retained OHLCV-proxy wave history with explicit provenance.

This renderer does not train the retired wave model, fetch quotes, or start a
broker. Legacy classification outputs are uncalibrated research illustrations.
"""
from pathlib import Path
import argparse
import json

ROOT = Path(__file__).resolve().parents[1]


def render_dashboard(inline_store):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LOB 订单流微观结构波浪研判终端 (Microstructure Wave Alpha Terminal)</title>
    <!-- Multi-Tier Local & CDN ECharts Loader (Offline & Cross-Network Guaranteed) -->
    <script src="echarts.min.js"></script>
    <script>
        if (typeof echarts === 'undefined') {{
            document.write('<script src="/charts/echarts.min.js"><\\/script>');
        }}
    </script>
    <script>
        if (typeof echarts === 'undefined') {{
            document.write('<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"><\\/script>');
        }}
    </script>
    <script>
        if (typeof echarts === 'undefined') {{
            document.write('<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.4.3/echarts.min.js"><\\/script>');
        }}
    </script>
    <script>
        if (typeof echarts === 'undefined') {{
            document.write('<script src="https://unpkg.com/echarts@5.4.3/dist/echarts.min.js"><\\/script>');
        }}
    </script>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;800&family=Inter:wght@400;600;700;900&display=swap" media="print" onload="this.media='all'">
    <noscript>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;800&family=Inter:wght@400;600;700;900&display=swap">
    </noscript>
    <style>
        :root {{
            --bg-base: #080a11;
            --bg-card: #0f1422;
            --bg-card-hover: #161e33;
            --border-color: rgba(255, 255, 255, 0.08);
            --accent-green: #10b981;
            --accent-red: #f43f5e;
            --accent-blue: #38bdf8;
            --accent-purple: #a855f7;
            --accent-amber: #f59e0b;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", sans-serif; }}
        body {{ background-color: var(--bg-base); color: var(--text-primary); padding: 20px 24px; min-height: 100vh; }}
        
        .header {{
            display: flex; justify-content: space-between; align-items: center;
            padding-bottom: 16px; border-bottom: 1px solid var(--border-color); margin-bottom: 20px;
        }}
        .header h1 {{
            font-size: 1.45rem; font-weight: 900;
            background: linear-gradient(135deg, #38bdf8, #818cf8, #c084fc);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }}
        .header p {{ font-size: 0.82rem; color: var(--text-secondary); margin-top: 4px; }}
        .badge-bar {{ display: flex; gap: 8px; align-items: center; }}
        .badge {{
            padding: 4px 10px; border-radius: 9999px; font-size: 0.72rem; font-weight: 700;
            font-family: 'JetBrains Mono', monospace; display: flex; align-items: center; gap: 6px;
        }}
        .badge-green {{ background: rgba(16, 185, 129, 0.15); color: var(--accent-green); border: 1px solid rgba(16, 185, 129, 0.3); }}
        .badge-blue {{ background: rgba(56, 189, 248, 0.15); color: var(--accent-blue); border: 1px solid rgba(56, 189, 248, 0.3); }}

        /* Top Navigation Bar */
        .controls-panel {{
            display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;
            background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px;
            padding: 12px 18px; margin-bottom: 20px; gap: 14px;
        }}
        .control-group {{ display: flex; align-items: center; gap: 10px; }}
        .control-label {{ font-size: 0.8rem; font-weight: 700; color: var(--text-secondary); text-transform: uppercase; }}
        
        .ticker-btn {{
            background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border-color);
            color: var(--text-secondary); font-size: 0.85rem; font-weight: 700; font-family: 'JetBrains Mono', monospace;
            padding: 6px 14px; border-radius: 8px; cursor: pointer; transition: all 0.2s;
        }}
        .ticker-btn:hover {{ background: rgba(255, 255, 255, 0.1); color: #fff; }}
        .ticker-btn.active {{
            background: linear-gradient(135deg, #38bdf8, #0284c7); color: #fff;
            border-color: #38bdf8; box-shadow: 0 0 12px rgba(56, 189, 248, 0.4);
        }}

        .date-select {{
            background: #080a11; border: 1px solid rgba(255, 255, 255, 0.15); color: #fff;
            padding: 6px 12px; border-radius: 8px; font-size: 0.85rem; font-family: 'JetBrains Mono', monospace;
            cursor: pointer; outline: none;
        }}
        .nav-btn {{
            background: rgba(255, 255, 255, 0.06); border: 1px solid var(--border-color);
            color: #fff; padding: 6px 12px; border-radius: 8px; font-size: 0.8rem; cursor: pointer;
            transition: all 0.2s;
        }}
        .nav-btn:hover:not(:disabled) {{ background: rgba(255, 255, 255, 0.15); border-color: #38bdf8; }}
        .nav-btn:disabled {{ opacity: 0.35; cursor: not-allowed; }}

        /* Daily Stats Banner */
        .day-stats-bar {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px; margin-bottom: 20px;
        }}
        .stat-chip {{
            background: var(--bg-card); border: 1px solid var(--border-color);
            border-radius: 10px; padding: 10px 14px;
        }}
        .stat-chip-label {{ font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700; }}
        .stat-chip-val {{ font-size: 1.15rem; font-weight: 900; margin-top: 4px; font-family: 'JetBrains Mono', monospace; }}

        .chart-box {{
            background: var(--bg-card); border: 1px solid var(--border-color);
            border-radius: 12px; padding: 18px; margin-bottom: 18px;
        }}
        .chart-header {{
            display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;
        }}
        .chart-title {{ font-size: 0.95rem; font-weight: 800; display: flex; align-items: center; gap: 8px; }}
        .chart-container {{ width: 100%; height: 380px; }}
        .chart-small {{ height: 230px; }}

        /* Signal Table */
        .table-box {{
            background: var(--bg-card); border: 1px solid var(--border-color);
            border-radius: 12px; padding: 18px; margin-bottom: 24px;
        }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
        th {{
            text-align: left; padding: 10px 12px; color: var(--text-secondary);
            border-bottom: 1px solid var(--border-color); font-weight: 700;
        }}
        td {{
            padding: 9px 12px; border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            font-family: 'JetBrains Mono', monospace;
        }}
        tr:hover td {{ background: rgba(255, 255, 255, 0.03); }}
        .badge-dir-long {{
            background: rgba(16, 185, 129, 0.18); color: var(--accent-green);
            padding: 2px 8px; border-radius: 4px; font-weight: 800;
        }}
        .badge-dir-short {{
            background: rgba(244, 63, 94, 0.18); color: var(--accent-red);
            padding: 2px 8px; border-radius: 4px; font-weight: 800;
        }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>🌊 LOB 订单流微观结构波浪研判终端 (Wave Alpha Terminal)</h1>
            <p>经典图表与交互展示 · K 线、量价结构、多因子分数与波浪机会</p>
        </div>
        <div class="badge-bar">
            <span id="liveBadge" class="badge" style="color: #fbbf24; border: 1px solid #92400e; font-weight: 700;">经典波浪展示</span>
            <span class="badge badge-blue">波浪方向分数</span>
            <span class="badge badge-blue">Composite Alpha</span>
        </div>
    </div>

    <div class="day-stats-bar" style="display:block; line-height:1.7; color:#fbbf24;" role="status" aria-live="polite">
        <strong>数据依据：</strong><span id="dataStatus">正在读取所选交易日…</span>
        <div>本页指标由 OHLCV 推导；方向百分比为模型或规则分数。真实 L1 数据在独立研究模块中展示。</div>
    </div>

    <div id="realL1Snapshot" class="day-stats-bar" style="display:none; line-height:1.7;"></div>

    <!-- Top Navigation Controls -->
    <div class="controls-panel">
        <div class="control-group">
            <span class="control-label">标的切换:</span>
            <div id="tickerButtonGroup" style="display: flex; gap: 6px;"></div>
        </div>

        <div class="control-group">
            <span class="control-label">交易日历史复盘 (Trading Day):</span>
            <button id="prevDayBtn" class="nav-btn">◀ 前一交易日</button>
            <select id="dateSelector" class="date-select"></select>
            <button id="nextDayBtn" class="nav-btn">后一交易日 ▶</button>
        </div>
    </div>

    <!-- Daily KPI Banner -->
    <div class="day-stats-bar">
        <div class="stat-chip">
            <div class="stat-chip-label">开盘价 (Open)</div>
            <div id="statOpen" class="stat-chip-val">-</div>
        </div>
        <div class="stat-chip">
            <div class="stat-chip-label">最新价 (Close)</div>
            <div id="statClose" class="stat-chip-val">-</div>
        </div>
        <div class="stat-chip">
            <div class="stat-chip-label">日内最高 / 最低</div>
            <div id="statRange" class="stat-chip-val">-</div>
        </div>
        <div class="stat-chip">
            <div class="stat-chip-label">价格涨跌幅（不是策略盈亏）</div>
            <div id="statPnl" class="stat-chip-val">-</div>
        </div>
        <div class="stat-chip">
            <div class="stat-chip-label">波浪标记数</div>
            <div id="statSignals" class="stat-chip-val" style="color: var(--accent-blue);">-</div>
        </div>
    </div>

    <!-- Chart 1: K-line with Wave Signals -->
    <div class="chart-box">
        <div class="chart-header">
            <div class="chart-title">
                📈 <span id="klineTitle">TSLA 5分钟 K 线与历史规则标记</span>
            </div>
            <div style="font-size: 0.8rem; color: var(--text-secondary);">
                ▲ 绿色三角：Wave Long | ▼ 红色倒三角：Wave Short · 防抖去重的经典波浪标记
            </div>
        </div>
        <div id="klineChart" class="chart-container"></div>
    </div>

    <!-- Chart 2: OFI & Microprice Drift -->
    <div class="chart-box">
        <div class="chart-header">
            <div class="chart-title">⚡ OFI & Microprice Drift · 经典量价视图</div>
            <div style="font-size: 0.8rem; color: var(--text-secondary);">柱状图：OFI 量价推导值 | 紫线：Microprice Drift 估计（bps）</div>
        </div>
        <div id="ofiChart" class="chart-container chart-small"></div>
    </div>

    <!-- Chart 3: Queue Imbalance & Sweep Velocity -->
    <div class="chart-box">
        <div class="chart-header">
            <div class="chart-title">🌊 影线实体失衡与量价活跃度</div>
            <div style="font-size: 0.8rem; color: var(--text-secondary);">黄线：Queue Imbalance 形态推导（-1 到 +1）| 蓝线：Sweep Velocity 量价活跃度</div>
        </div>
        <div id="queueChart" class="chart-container chart-small"></div>
    </div>

    <!-- Chart 4: Continuous Composite Alpha & Wave Probability -->
    <div class="chart-box">
        <div class="chart-header">
            <div class="chart-title">🎯 Composite Alpha 打分与波浪方向分数</div>
            <div style="font-size: 0.8rem; color: var(--text-secondary);">绿线：上涨方向分数（%）| 区域：多因子评分（-100 到 +100）</div>
        </div>
        <div id="alphaChart" class="chart-container chart-small"></div>
    </div>

    <!-- Signal Details Table -->
    <div class="table-box">
        <div class="chart-header">
            <div class="chart-title">📋 该交易日的 Saggese 波浪机会明细</div>
            <div style="font-size: 0.78rem; color: var(--text-muted);">多空波浪标记与对应因子分数 · 展示记录</div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>时间</th>
                    <th>方向</th>
                    <th>价格</th>
                    <th>方向分数</th>
                    <th>规则幅度</th>
                    <th>OFI 代理值</th>
                    <th>偏移估计 (bps)</th>
                    <th>规则评分</th>
                    <th>数据与模型依据</th>
                </tr>
            </thead>
            <tbody id="signalsTableBody"></tbody>
        </table>
    </div>

    <script>
        const store = {json.dumps(inline_store)};
        let currentTicker = 'TSLA';
        let currentDate = '';

        // Initialize Ticker Buttons
        const tickerGroup = document.getElementById('tickerButtonGroup');
        Object.keys(store).forEach(ticker => {{
            const btn = document.createElement('button');
            btn.className = `ticker-btn ${{ticker === currentTicker ? 'active' : ''}}`;
            btn.textContent = ticker;
            btn.onclick = () => switchTicker(ticker);
            tickerGroup.appendChild(btn);
        }});

        const apiBase = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';
        const dateSelect = document.getElementById('dateSelector');
        const prevBtn = document.getElementById('prevDayBtn');
        const nextBtn = document.getElementById('nextDayBtn');
        let liveRefreshTimer = null;

        function populateDates(ticker) {{
            const allDays = store[ticker].all_available_days || store[ticker].days;
            dateSelect.innerHTML = '';

            // Add TODAY (Live 实时) as first option
            const liveOpt = document.createElement('option');
            liveOpt.value = 'today';
            liveOpt.textContent = '今日 L1 数据状态';
            dateSelect.appendChild(liveOpt);

            allDays.forEach((d, idx) => {{
                const opt = document.createElement('option');
                opt.value = d;
                const isLatest = (idx === allDays.length - 1);
                opt.textContent = isLatest ? `${{d}} (历史最新)` : d;
                dateSelect.appendChild(opt);
            }});
            currentDate = allDays[allDays.length - 1] || 'today';
            dateSelect.value = currentDate;
            updateNavButtons();
        }}

        function updateNavButtons() {{
            const days = store[currentTicker].all_available_days || store[currentTicker].days;
            if (currentDate === 'today') {{
                prevBtn.disabled = false;
                nextBtn.disabled = true;
            }} else {{
                const idx = days.indexOf(currentDate);
                prevBtn.disabled = (idx <= 0);
                nextBtn.disabled = false;
            }}
        }}

        let requestGeneration = 0;
        let pendingRequest = null;

        function setDataStatus(message) {{
            document.getElementById('dataStatus').textContent = message;
        }}

        function clearDisplayedData(message) {{
            [kChart, oChart, qChart, aChart].forEach(chart => {{ if (chart) chart.clear(); }});
            ['statOpen', 'statClose', 'statRange', 'statPnl', 'statSignals'].forEach(id => {{
                document.getElementById(id).textContent = '—';
            }});
            document.getElementById('signalsTableBody').innerHTML = '';
            document.getElementById('klineTitle').textContent = `${{currentTicker}} · ${{message}}`;
            document.getElementById('liveBadge').textContent = message;
            setDataStatus(message);
            document.getElementById('realL1Snapshot').style.display = 'none';
            document.getElementById('realL1Snapshot').textContent = '';
        }}

        function legacyDirectionValue(dayData, signal) {{
            const index = Number.isInteger(signal.index) ? signal.index : dayData.times.indexOf(signal.time);
            const p = dayData.wave_p_win_long[index];
            if (!Number.isFinite(p) || p < 0 || p > 100) return '未提供';
            return `${{(signal.direction === 'LONG' ? p : 100 - p).toFixed(1)}}%`;
        }}

        async function selectDay(d, isAutoRefresh = false) {{
            if (!d) return;
            const generation = ++requestGeneration;
            if (pendingRequest) pendingRequest.abort();
            pendingRequest = new AbortController();
            const controller = pendingRequest;
            const ticker = currentTicker;
            currentDate = d;
            dateSelect.value = d;
            updateNavButtons();
            clearTimeout(liveRefreshTimer);
            liveRefreshTimer = null;
            clearDisplayedData(d === 'today' ? '正在读取今日行情' : '正在读取历史图表');
            const isCurrent = () => generation === requestGeneration && ticker === currentTicker && d === currentDate;
            const timeout = setTimeout(() => controller.abort(), 15000);
            try {{
                if (d === 'today') {{
                    const response = await fetch(`${{apiBase}}/api/wave/live_today?ticker=${{encodeURIComponent(ticker)}}`, {{ signal: controller.signal }});
                    if (!response.ok) throw new Error('今日行情请求失败');
                    const result = await response.json();
                    if (!isCurrent()) return;
                    const today = new Intl.DateTimeFormat('en-CA', {{ timeZone: 'America/New_York' }}).format(new Date());
                    if (!result.success || !result.data || !result.is_today || result.date !== today || result.ticker !== ticker)
                        throw new Error(result.error || '今日暂无完整行情，可切换历史日期');
                    store[ticker].by_day.today = result.data;
                    renderDashboard(true, result.date, result.last_updated || '');
                }} else {{
                    let dayData = store[ticker]?.by_day?.[d];
                    if (!dayData) {{
                        const response = await fetch(`${{apiBase}}/api/wave/day_data?ticker=${{encodeURIComponent(ticker)}}&date=${{encodeURIComponent(d)}}`, {{ signal: controller.signal }});
                        if (!response.ok) throw new Error('History request failed');
                        const result = await response.json();
                        if (!isCurrent()) return;
                        if (!result.success || !result.data) throw new Error('History unavailable');
                        dayData = result.data;
                        store[ticker].by_day[d] = dayData;
                    }}
                    if (isCurrent()) renderDashboard(false, d);
                }}
            }} catch (error) {{
                if (isCurrent()) clearDisplayedData(d === 'today'
                    ? (error.message || '今日行情暂不可用，请选择历史日期')
                    : '历史数据读取失败 · 未展示其他日期的缓存');
            }} finally {{
                clearTimeout(timeout);
                if (isCurrent() && d === 'today') liveRefreshTimer = setTimeout(() => selectDay('today', true), 8000);
            }}
        }}

        prevBtn.onclick = () => {{
            const days = store[currentTicker].all_available_days || store[currentTicker].days;
            if (currentDate === 'today') {{
                selectDay(days[days.length - 1]);
            }} else {{
                const idx = days.indexOf(currentDate);
                if (idx > 0) {{
                    selectDay(days[idx - 1]);
                }}
            }}
        }};

        nextBtn.onclick = () => {{
            const days = store[currentTicker].all_available_days || store[currentTicker].days;
            if (currentDate !== 'today') {{
                const idx = days.indexOf(currentDate);
                if (idx < days.length - 1) {{
                    selectDay(days[idx + 1]);
                }} else {{
                    selectDay('today');
                }}
            }}
        }};

        dateSelect.onchange = (e) => {{
            selectDay(e.target.value);
        }};

        function switchTicker(ticker) {{
            currentTicker = ticker;
            document.querySelectorAll('.ticker-btn').forEach(b => {{
                b.classList.toggle('active', b.textContent === ticker);
            }});
            populateDates(ticker);
            selectDay(currentDate);
        }}

        // Chart instances
        let kChart = null, oChart = null, qChart = null, aChart = null;

        function renderDashboard(isLive = false, actualDate = '', lastUpdated = '') {{
            const dayData = store[currentTicker].by_day[currentDate];
            if (!dayData) return;

            const dateStr = actualDate || currentDate;
            document.getElementById('liveBadge').textContent = `${{isLive ? '当前行情' : '历史回看'}} · ${{dateStr}}`;
            document.getElementById('klineTitle').textContent = `${{currentTicker}} · ${{dateStr}} · 5分钟 K 线与波浪拐点`;
            setDataStatus(`${{isLive ? '当前已完成 K 线' : '归档快照'}} · ${{dateStr}} · OHLCV 推导指标`);

            // Update Stats Banner
            const stats = dayData.stats;
            document.getElementById('statOpen').textContent = `$${{stats.open}}`;
            document.getElementById('statClose').textContent = `$${{stats.close}}`;
            document.getElementById('statRange').textContent = `$${{stats.low}} ~ $${{stats.high}}`;
            const pnlEl = document.getElementById('statPnl');
            pnlEl.textContent = `${{stats.pnl_pct >= 0 ? '+' : ''}}${{stats.pnl_pct}}%`;
            pnlEl.style.color = stats.pnl_pct >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
            document.getElementById('statSignals').textContent = `${{stats.signal_count}} 个波浪标记`;

            // Clean, elegant markers that NEVER clump or stack
            const markPointData = dayData.signals.map(s => {{
                const isLong = s.direction === 'LONG';
                return {{
                    name: s.direction,
                    coord: [s.coord_x, s.coord_y],
                    value: `${{isLong ? 'L' : 'S'}}`,
                    symbol: 'triangle',
                    symbolRotate: isLong ? 0 : 180,
                    symbolSize: 12,
                    itemStyle: {{
                        color: isLong ? '#10b981' : '#f43f5e',
                        borderColor: '#ffffff',
                        borderWidth: 1,
                        shadowBlur: 8,
                        shadowColor: isLong ? 'rgba(16, 185, 129, 0.6)' : 'rgba(244, 63, 94, 0.6)'
                    }},
                    label: {{
                        show: true,
                        position: isLong ? 'bottom' : 'top',
                        distance: 6,
                        color: '#f8fafc',
                        fontSize: 10,
                        fontWeight: 700,
                        fontFamily: 'JetBrains Mono',
                        formatter: '{{c}}'
                    }}
                }};
            }});

            // 1. K-line Chart
            kChart.setOption({{
                backgroundColor: 'transparent',
                tooltip: {{
                    trigger: 'axis',
                    axisPointer: {{ type: 'cross' }},
                    backgroundColor: 'rgba(15, 20, 34, 0.95)',
                    borderColor: '#334155',
                    formatter: function(params) {{
                        const idx = params[0].dataIndex;
                        const k = dayData.kline[idx];
                        const t = dayData.times[idx];
                        const ofi = dayData.ofi[idx];
                        const drift = dayData.micro_drift[idx];
                        const pLong = dayData.wave_p_win_long[idx];
                        const alpha = dayData.composite_alpha[idx];
                        return `
                            <div style="font-family: JetBrains Mono; font-size: 0.8rem; line-height: 1.5;">
                                <div style="font-weight: 800; color: #38bdf8; margin-bottom: 4px;">⏰ ${{t}} (${{currentTicker}})</div>
                                <div>开: ${{k[0]}} | 高: ${{k[3]}} | 低: ${{k[2]}} | 收: ${{k[1]}}</div>
                                <div style="margin-top: 4px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 4px;">
                                    <div>波浪方向分数: <span style="color: ${{pLong >= 50 ? '#10b981' : '#f43f5e'}}; font-weight: 800;">${{pLong}}%</span></div>
                                    <div>⚡ OFI 代理值: <span style="color: ${{ofi >= 0 ? '#10b981' : '#f43f5e'}};">${{ofi >= 0 ? '+' : ''}}${{ofi}}</span></div>
                                    <div>🎯 K 线偏移估计: <span style="color: #a855f7; font-weight: 700;">${{drift >= 0 ? '+' : ''}}${{drift}} bps</span></div>
                                    <div>📊 规则评分: <span style="color: ${{alpha >= 0 ? '#38bdf8' : '#f43f5e'}};">${{alpha >= 0 ? '+' : ''}}${{alpha}}</span></div>
                                </div>
                            </div>
                        `;
                    }}
                }},
                legend: {{
                    data: ['K 线', 'EMA 9', 'EMA 21', 'VWAP'],
                    textStyle: {{ color: '#94a3b8' }},
                    right: '3%'
                }},
                grid: {{ left: '4%', right: '3%', bottom: '8%', top: '10%', containLabel: true }},
                xAxis: {{
                    type: 'category',
                    data: dayData.times,
                    axisLine: {{ lineStyle: {{ color: '#334155' }} }},
                    axisLabel: {{ color: '#64748b' }}
                }},
                yAxis: {{
                    type: 'value',
                    scale: true,
                    splitLine: {{ lineStyle: {{ color: '#1e293b' }} }},
                    axisLabel: {{ color: '#64748b' }}
                }},
                series: [
                    {{
                        name: 'K 线',
                        type: 'candlestick',
                        data: dayData.kline,
                        itemStyle: {{
                            color: '#10b981',
                            color0: '#f43f5e',
                            borderColor: '#10b981',
                            borderColor0: '#f43f5e'
                        }},
                        markPoint: {{
                            data: markPointData,
                            symbolSize: 45
                        }}
                    }},
                    {{
                        name: 'EMA 9',
                        type: 'line',
                        data: dayData.ema9,
                        smooth: true,
                        lineStyle: {{ color: '#38bdf8', width: 1.5 }},
                        showSymbol: false
                    }},
                    {{
                        name: 'EMA 21',
                        type: 'line',
                        data: dayData.ema21,
                        smooth: true,
                        lineStyle: {{ color: '#f59e0b', width: 1.5 }},
                        showSymbol: false
                    }},
                    {{
                        name: 'VWAP',
                        type: 'line',
                        data: dayData.vwap,
                        smooth: true,
                        lineStyle: {{ color: '#e2e8f0', width: 2, type: 'dashed' }},
                        showSymbol: false
                    }}
                ]
            }}, true);

            // 2. OFI Chart
            oChart.setOption({{
                backgroundColor: 'transparent',
                tooltip: {{
                    trigger: 'axis',
                    backgroundColor: 'rgba(15, 20, 34, 0.95)',
                    borderColor: '#334155',
                    formatter: function(params) {{
                        if (!params || !params.length) return '';
                        let t = params[0].name;
                        let res = `<div style="font-family: JetBrains Mono; font-size: 0.8rem; color: #f8fafc;"><div style="color:#94a3b8; margin-bottom:4px;">⏰ ${{t}}</div>`;
                        params.forEach(p => {{
                            let val = Number(p.value);
                            let sign = val > 0 ? '+' : '';
                            if (p.seriesName.includes('OFI')) {{
                                let col = val >= 0 ? '#10b981' : '#f43f5e';
                                res += `<div><span style="color:${{col}}">●</span> ${{p.seriesName}}: <b style="color:${{col}}">${{sign}}${{val.toFixed(3)}}</b></div>`;
                            }} else {{
                                res += `<div><span style="color:#a855f7">●</span> K 线偏移估计 (bps): <b style="color:#a855f7">${{sign}}${{val.toFixed(2)}} bps</b></div>`;
                            }}
                        }});
                        res += `</div>`;
                        return res;
                    }}
                }},
                legend: {{ data: ['OFI 代理值', 'K 线偏移估计 (bps)'], textStyle: {{ color: '#94a3b8' }} }},
                grid: {{ left: '4%', right: '3%', bottom: '10%', top: '15%', containLabel: true }},
                xAxis: {{ type: 'category', data: dayData.times, axisLine: {{ lineStyle: {{ color: '#334155' }} }}, axisLabel: {{ color: '#64748b' }} }},
                yAxis: [
                    {{ type: 'value', name: 'OFI', splitLine: {{ lineStyle: {{ color: '#1e293b' }} }}, axisLabel: {{ color: '#64748b' }} }},
                    {{ type: 'value', name: '偏移估计 (bps)', splitLine: {{ show: false }}, axisLabel: {{ color: '#a855f7', formatter: '{{value}} bps' }} }}
                ],
                series: [
                    {{
                        name: 'OFI 代理值',
                        type: 'bar',
                        data: dayData.ofi,
                        itemStyle: {{ color: (p) => p.value >= 0 ? '#10b981' : '#f43f5e' }}
                    }},
                    {{
                        name: 'K 线偏移估计 (bps)',
                        type: 'line',
                        yAxisIndex: 1,
                        data: dayData.micro_drift,
                        smooth: true,
                        lineStyle: {{ color: '#a855f7', width: 2 }},
                        showSymbol: false
                    }}
                ]
            }}, true);

            // 3. Queue & Sweep Chart
            qChart.setOption({{
                backgroundColor: 'transparent',
                tooltip: {{
                    trigger: 'axis',
                    backgroundColor: 'rgba(15, 20, 34, 0.95)',
                    borderColor: '#334155',
                    formatter: function(params) {{
                        if (!params || !params.length) return '';
                        let t = params[0].name;
                        let res = `<div style="font-family: JetBrains Mono; font-size: 0.8rem; color: #f8fafc;"><div style="color:#94a3b8; margin-bottom:4px;">⏰ ${{t}}</div>`;
                        params.forEach(p => {{
                            let val = Number(p.value);
                            let sign = val > 0 ? '+' : '';
                            if (p.seriesName.includes('影线实体')) {{
                                res += `<div><span style="color:#f59e0b">●</span> 影线实体失衡（代理）: <b style="color:#f59e0b">${{sign}}${{val.toFixed(3)}}</b></div>`;
                            }} else {{
                                res += `<div><span style="color:#38bdf8">●</span> 量价活跃度（代理）: <b style="color:#38bdf8">${{sign}}${{val.toFixed(3)}}</b></div>`;
                            }}
                        }});
                        res += `</div>`;
                        return res;
                    }}
                }},
                legend: {{ data: ['影线实体失衡（代理）', '量价活跃度（代理）'], textStyle: {{ color: '#94a3b8' }} }},
                grid: {{ left: '4%', right: '3%', bottom: '10%', top: '15%', containLabel: true }},
                xAxis: {{ type: 'category', data: dayData.times, axisLine: {{ lineStyle: {{ color: '#334155' }} }}, axisLabel: {{ color: '#64748b' }} }},
                yAxis: {{ type: 'value', splitLine: {{ lineStyle: {{ color: '#1e293b' }} }}, axisLabel: {{ color: '#64748b' }} }},
                series: [
                    {{
                        name: '影线实体失衡（代理）',
                        type: 'line',
                        data: dayData.queue_imb,
                        smooth: true,
                        lineStyle: {{ color: '#f59e0b', width: 2 }},
                        showSymbol: false
                    }},
                    {{
                        name: '量价活跃度（代理）',
                        type: 'line',
                        data: dayData.sweep_vel,
                        smooth: true,
                        lineStyle: {{ color: '#38bdf8', width: 2 }},
                        showSymbol: false
                    }}
                ]
            }}, true);

            // 4. Alpha & Probability Chart
            aChart.setOption({{
                backgroundColor: 'transparent',
                tooltip: {{ trigger: 'axis', backgroundColor: 'rgba(15, 20, 34, 0.95)', borderColor: '#334155' }},
                legend: {{ data: ['历史规则评分', '波浪方向分数 (%)'], textStyle: {{ color: '#94a3b8' }} }},
                grid: {{ left: '4%', right: '3%', bottom: '10%', top: '15%', containLabel: true }},
                xAxis: {{ type: 'category', data: dayData.times, axisLine: {{ lineStyle: {{ color: '#334155' }} }}, axisLabel: {{ color: '#64748b' }} }},
                yAxis: [
                    {{ type: 'value', name: '规则评分', min: -100, max: 100, splitLine: {{ lineStyle: {{ color: '#1e293b' }} }}, axisLabel: {{ color: '#64748b' }} }},
                    {{ type: 'value', name: '分类输出 %', min: 0, max: 100, splitLine: {{ show: false }}, axisLabel: {{ color: '#64748b' }} }}
                ],
                series: [
                    {{
                        name: '历史规则评分',
                        type: 'line',
                        data: dayData.composite_alpha,
                        smooth: true,
                        lineStyle: {{ color: '#38bdf8', width: 2 }},
                        areaStyle: {{
                            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                {{ offset: 0, color: 'rgba(56, 189, 248, 0.25)' }},
                                {{ offset: 1, color: 'rgba(56, 189, 248, 0.0)' }}
                            ])
                        }},
                        showSymbol: false
                    }},
                    {{
                        name: '波浪方向分数 (%)',
                        type: 'line',
                        yAxisIndex: 1,
                        data: dayData.wave_p_win_long,
                        smooth: true,
                        lineStyle: {{ color: '#10b981', width: 2.2 }},
                        showSymbol: false
                    }}
                ]
            }}, true);

            // Populate Signals Table
            const tbody = document.getElementById('signalsTableBody');
            tbody.innerHTML = '';
            if (dayData.signals.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 20px;">该时段暂无波浪标记，可切换日期或标的。</td></tr>';
            }} else {{
                dayData.signals.forEach(s => {{
                    const tr = document.createElement('tr');
                    const isLong = s.direction === 'LONG';
                    tr.innerHTML = `
                        <td style="color: #38bdf8; font-weight: 700;">${{s.time}}</td>
                        <td><span class="${{isLong ? 'badge-dir-long' : 'badge-dir-short'}}">${{s.direction}}</span></td>
                        <td>$${{s.price}}</td>
                        <td style="color: ${{isLong ? '#10b981' : '#f43f5e'}}; font-weight: 800;">${{legacyDirectionValue(dayData, s)}}</td>
                        <td>${{Number.isFinite(s.expected_ret) ? s.expected_ret.toFixed(2) + '（规则）' : '—'}}</td>
                        <td style="color: ${{s.ofi >= 0 ? '#10b981' : '#f43f5e'}};">${{s.ofi}}</td>
                        <td>${{s.micro_drift}}</td>
                        <td style="color: ${{s.alpha >= 0 ? '#38bdf8' : '#f43f5e'}};">${{s.alpha}}</td>
                        <td style="color: var(--text-secondary); font-size: 0.78rem;">经典波浪标记 · OHLCV</td>
                    `;
                    tbody.appendChild(tr);
                }});
            }}
        }}

        function startTerminal() {{
            if (typeof echarts === 'undefined') {{
                console.warn('Waiting for ECharts library to load...');
                setTimeout(startTerminal, 50);
                return;
            }}
            try {{
                if (!kChart) {{
                    kChart = echarts.init(document.getElementById('klineChart'));
                    oChart = echarts.init(document.getElementById('ofiChart'));
                    qChart = echarts.init(document.getElementById('queueChart'));
                    aChart = echarts.init(document.getElementById('alphaChart'));
                }}
                populateDates(currentTicker);
                selectDay(currentDate);
            }} catch (err) {{
                console.error('Fatal initialization error:', err);
            }}
        }}

        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', startTerminal);
        }} else {{
            startTerminal();
        }}

        window.addEventListener('resize', () => {{
            if (kChart) kChart.resize();
            if (oChart) oChart.resize();
            if (qChart) qChart.resize();
            if (aChart) aChart.resize();
        }});
    </script>
</body>
</html>
"""


def generate_multi_day_dashboard(cache=None, output=None):
    cache = Path(cache) if cache else ROOT / 'backend/data/charts/wave_history_cache.json'
    output = Path(output) if output else ROOT / 'backend/data/charts/saggese_wave_visual_dashboard.html'
    history = json.loads(cache.read_text())
    inline = {}
    for symbol, record in history.items():
        days = [day for day in record.get('all_available_days', record.get('days', [])) if day != 'today']
        recent = days[-10:]
        inline[symbol] = dict(days=recent, all_available_days=days,
                              by_day={day: record['by_day'][day] for day in recent if day in record.get('by_day', {})})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_dashboard(inline), encoding='utf-8')
    print(f'Rendered retained proxy history: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache')
    parser.add_argument('--output')
    args = parser.parse_args()
    generate_multi_day_dashboard(args.cache, args.output)
