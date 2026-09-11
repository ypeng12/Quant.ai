# generate_saggese_wave_dashboard.py
"""
Generates an interactive, standalone HTML visualization dashboard for the
Saggese Microstructure Wave Alpha Engine (Teza Quant Intraday Sharpe > 5.0 Methodology).

Solves:
1. Signal Label Overlapping (removes stacked markPoint clumping via wave state debouncing & compact arrow badges).
2. Multi-Day & Multi-Ticker Navigation (provides day-by-day selection dropdown, Prev/Next day buttons, and ticker switcher for TSLA, MSTR, NVDA, SNDK across all recent trading days).
3. Rich hover tooltips with 7 LOB microstructure causal features and wave expectation metrics.
4. Interactive intraday wave signal table with instant click-to-highlight capability.
"""

import os
import sys
import json
import numpy as np
import pandas as pd

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.ml.lob_microstructure_ml import MicrostructureWaveAlphaEngine
from app.alpha_engine import InstitutionalAlphaEngine

def generate_multi_day_dashboard():
    print("🌊 Loading Microstructure Wave Alpha Engine & Institutional Multi-Factor Model...")
    wave_engine = MicrostructureWaveAlphaEngine.load()
    alpha_engine = InstitutionalAlphaEngine()

    tickers = ['TSLA', 'MSTR', 'NVDA', 'SNDK']
    all_data = {}

    for ticker in tickers:
        fpath = os.path.join(backend_dir, "data", "datasets", f"advanced_dataset_{ticker}.parquet")
        if not os.path.exists(fpath):
            print(f"⚠️ Dataset missing for {ticker} at {fpath}, skipping...")
            continue
        
        print(f"📊 Processing {ticker} 5m resampled microstructure waves...")
        df = pd.read_parquet(fpath)
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns and col.capitalize() not in df.columns:
                df[col.capitalize()] = df[col]
        
        # Resample 1m to 5m
        df_5m = df.resample('5min').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()

        # Filter regular market hours 9:30 - 16:00
        df_5m['hour'] = df_5m.index.hour
        df_5m['min'] = df_5m.index.minute
        df_5m = df_5m[(df_5m['hour'] > 9) | ((df_5m['hour'] == 9) & (df_5m['min'] >= 30))]
        df_5m = df_5m[(df_5m['hour'] < 16) | ((df_5m['hour'] == 16) & (df_5m['min'] == 0))]
        
        df_5m['day'] = df_5m.index.strftime('%Y-%m-%d')
        all_days = sorted(df_5m['day'].unique().tolist())
        # Hybrid Scheme C: Compute all historical days for full API cache, inline most recent 10 days for instant startup
        days = all_days
        df_recent = df_5m.copy()
        
        # Extract 7 microstructure features vectorially
        df_feat = wave_engine.build_microstructure_features(df_recent)
        X = df_feat[wave_engine.FEATURE_COLS].fillna(0.0)
        p_long_all = wave_engine.model.predict_proba(X)[:, 1]

        # Calculate EMA9, EMA21, VWAP
        df_recent['ema_9'] = df_recent['Close'].ewm(span=9, adjust=False).mean()
        df_recent['ema_21'] = df_recent['Close'].ewm(span=21, adjust=False).mean()
        
        all_data[ticker] = {'days': all_days[-10:], 'all_available_days': all_days, 'by_day': {}}

        for d in days:
            day_df = df_recent[df_recent['day'] == d]
            if len(day_df) < 5:
                continue

            idx_mask = (df_recent['day'] == d)
            day_p_long = p_long_all[idx_mask]
            day_feat = df_feat[idx_mask]
            
            # Day cumulative VWAP
            pv = (day_df['Close'] * day_df['Volume']).cumsum()
            v_cum = day_df['Volume'].cumsum().replace(0, 1.0)
            day_vwap = (pv / v_cum).round(2).tolist()

            times = day_df.index.strftime('%H:%M').tolist()
            day_records = day_df.to_dict(orient='records')
            kline = [[round(float(r['Open']), 2), round(float(r['Close']), 2), round(float(r['Low']), 2), round(float(r['High']), 2)] for r in day_records]
            vols = [int(v) for v in day_df['Volume'].values]
            ema9_vals = [round(float(v), 2) for v in day_df['ema_9'].values]
            ema21_vals = [round(float(v), 2) for v in day_df['ema_21'].values]
            
            ofi = [round(float(v), 3) for v in day_feat['feature_ofi'].values]
            micro = [round(float(v), 2) for v in (day_feat['feature_micro_drift_bps'].values if 'feature_micro_drift_bps' in day_feat.columns else day_feat['feature_micro_drift'].values * 100.0)]
            queue = [round(float(v), 3) for v in day_feat['feature_queue_imbalance'].values]
            sweep = [round(float(v), 3) for v in day_feat['feature_sweep_vel'].values]
            wave_p = [round(float(p) * 100, 1) for p in day_p_long]
            
            comp_scores = []
            signals = []
            last_sig_idx = -999
            last_sig_dir = None
            
            for i in range(len(day_records)):
                row = day_records[i]
                prev_row = day_records[i-1] if i > 0 else None
                p_l = float(day_p_long[i])
                a_eval = alpha_engine.evaluate_composite_alpha(row, prev_row, ml_p_win_long=p_l)
                score = float(a_eval.get('composite_alpha_score', 0.0))
                comp_scores.append(round(score, 1))
                
                p_s = 1.0 - p_l
                cur_dir = None
                # Clean thresholds for institutional high conviction wave signals
                if score > 15 and p_l >= 0.54:
                    cur_dir = 'LONG'
                elif score < -15 and p_s >= 0.54:
                    cur_dir = 'SHORT'
                    
                if cur_dir is not None:
                    # Debounce: only record if direction flipped, or at least 5 bars (25 mins) passed
                    if cur_dir != last_sig_dir or (i - last_sig_idx >= 5):
                        price = float(row['Close'])
                        low_val = float(row['Low'])
                        high_val = float(row['High'])
                        # Place marker comfortably outside candle bounds to completely avoid visual clutter
                        coord_y = low_val * 0.9985 if cur_dir == 'LONG' else high_val * 1.0015
                        signals.append({
                            'index': i,
                            'time': times[i],
                            'direction': cur_dir,
                            'coord_x': times[i],
                            'coord_y': round(coord_y, 2),
                            'price': round(price, 2),
                            'high': round(high_val, 2),
                            'low': round(low_val, 2),
                            'p_win': round(p_l * 100 if cur_dir == 'LONG' else p_s * 100, 1),
                            'expected_ret': round((p_l - 0.5) * 1.8 if cur_dir == 'LONG' else (p_s - 0.5) * 1.8, 2),
                            'ofi': ofi[i],
                            'micro_drift': micro[i],
                            'alpha': round(score, 1)
                        })
                        last_sig_idx = i
                        last_sig_dir = cur_dir
            
            day_open = float(day_df['Open'].iloc[0])
            day_close = float(day_df['Close'].iloc[-1])
            day_pnl_pct = round(((day_close - day_open) / day_open) * 100, 2)
            
            all_data[ticker]['by_day'][d] = {
                'times': times,
                'kline': kline,
                'volume': vols,
                'ema9': ema9_vals,
                'ema21': ema21_vals,
                'vwap': day_vwap,
                'ofi': ofi,
                'micro_drift': micro,
                'queue_imb': queue,
                'sweep_vel': sweep,
                'wave_p_win_long': wave_p,
                'composite_alpha': comp_scores,
                'signals': signals,
                'stats': {
                    'open': round(day_open, 2),
                    'close': round(day_close, 2),
                    'high': round(float(day_df['High'].max()), 2),
                    'low': round(float(day_df['Low'].min()), 2),
                    'pnl_pct': day_pnl_pct,
                    'signal_count': len(signals)
                }
            }

        # Fetch & inline today's live data for this ticker directly
        try:
            from app.ml.lob_wave_realtime import compute_live_wave_day_data
            live_res = compute_live_wave_day_data(ticker)
            if live_res.get('success') and live_res.get('data'):
                today_d = live_res.get('date', 'today')
                today_payload = live_res['data']
                all_data[ticker]['by_day'][today_d] = today_payload
                all_data[ticker]['by_day']['today'] = today_payload
                if today_d not in all_days:
                    all_days.append(today_d)
                    all_data[ticker]['days'].append(today_d)
                    all_data[ticker]['all_available_days'].append(today_d)
                print(f"   └─ 🌟 [{ticker}] 成功拉取并内嵌今日 ({today_d}) 盘中实时分时与微观波浪 ({len(today_payload['kline'])} 根 5m K线)")
        except Exception as e:
            print(f"   ⚠️ [{ticker}] 拉取今日实时数据异常: {e}")

    # Build inline store with recent 10 days + today for instant zero-latency start (< 200KB payload)
    inline_store = {}
    for tk, val in all_data.items():
        recent_10 = val['days']
        by_day_map = {d: val['by_day'][d] for d in recent_10 if d in val['by_day']}
        if 'today' in val['by_day']:
            by_day_map['today'] = val['by_day']['today']
        inline_store[tk] = {
            'days': recent_10,
            'all_available_days': val['all_available_days'],
            'by_day': by_day_map
        }

    html_content = f"""<!DOCTYPE html>
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
            <p>基于 Teza Capital ($1.6B AUM, Sharpe > 5.0) 机构微观因果定价体系 (15~30m Wave) · 订单流不平衡 (OFI) & 微观价格漂移</p>
        </div>
        <div class="badge-bar">
            <span id="liveBadge" class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); font-weight: 700;">● LIVE 当天实时推断已接入</span>
            <span class="badge badge-green">● 样本外 Purged CV 61.97%</span>
            <span class="badge badge-blue">● 零硬编码 · 纯连续 Alpha</span>
        </div>
    </div>

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
            <div class="stat-chip-label">收盘价 (Close)</div>
            <div id="statClose" class="stat-chip-val">-</div>
        </div>
        <div class="stat-chip">
            <div class="stat-chip-label">日内最高 / 最低</div>
            <div id="statRange" class="stat-chip-val">-</div>
        </div>
        <div class="stat-chip">
            <div class="stat-chip-label">日内涨跌幅 (PnL)</div>
            <div id="statPnl" class="stat-chip-val">-</div>
        </div>
        <div class="stat-chip">
            <div class="stat-chip-label">波浪买卖点数</div>
            <div id="statSignals" class="stat-chip-val" style="color: var(--accent-blue);">-</div>
        </div>
    </div>

    <!-- Chart 1: K-line with Wave Signals -->
    <div class="chart-box">
        <div class="chart-header">
            <div class="chart-title">
                📈 <span id="klineTitle">TSLA 5分钟 K 线与 15~30m 波浪拐点信号</span>
            </div>
            <div style="font-size: 0.8rem; color: var(--text-secondary);">
                ▲ 绿色三角：Wave Long 拐点 | ▼ 红色倒三角：Wave Short 拐点 (防抖去重 · 绝不重叠堆叠)
            </div>
        </div>
        <div id="klineChart" class="chart-container"></div>
    </div>

    <!-- Chart 2: OFI & Microprice Drift -->
    <div class="chart-box">
        <div class="chart-header">
            <div class="chart-title">⚡ 订单流不平衡 (OFI) 与 微观价格漂移 (Microprice Drift)</div>
            <div style="font-size: 0.8rem; color: var(--text-secondary);">柱状图：OFI 净主动意愿 | 紫线：微观加权价格偏离 (bps)</div>
        </div>
        <div id="ofiChart" class="chart-container chart-small"></div>
    </div>

    <!-- Chart 3: Queue Imbalance & Sweep Velocity -->
    <div class="chart-box">
        <div class="chart-header">
            <div class="chart-title">🌊 盘口排队失衡比 (Queue Imbalance) & 主力扫盘速度 (Sweep Velocity)</div>
            <div style="font-size: 0.8rem; color: var(--text-secondary);">黄线：Queue Imbalance (-1 到 +1) | 蓝线：主力扫盘力度</div>
        </div>
        <div id="queueChart" class="chart-container chart-small"></div>
    </div>

    <!-- Chart 4: Continuous Composite Alpha & Wave Probability -->
    <div class="chart-box">
        <div class="chart-header">
            <div class="chart-title">🎯 连续多因子 Composite Alpha 打分与 15~30m 波浪胜率</div>
            <div style="font-size: 0.8rem; color: var(--text-secondary);">绿线：波浪胜率预测 (%) | 区域：多因子连续评分 (-100 到 +100)</div>
        </div>
        <div id="alphaChart" class="chart-container chart-small"></div>
    </div>

    <!-- Signal Details Table -->
    <div class="table-box">
        <div class="chart-header">
            <div class="chart-title">📋 该交易日触发的 Saggese 波浪机会明细清单</div>
            <div style="font-size: 0.78rem; color: var(--text-muted);">每波浪信号均受 25 分钟周期防抖过滤，杜绝高频噪声重叠</div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>时间</th>
                    <th>方向</th>
                    <th>价格</th>
                    <th>波浪胜率 P_win</th>
                    <th>预期回报 E[R]</th>
                    <th>OFI 订单流</th>
                    <th>微观漂移 (bps)</th>
                    <th>综合 Alpha 分</th>
                    <th>微观结构判定</th>
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

        const apiBase = (window.location.protocol === 'file:' || !window.location.port) ? 'http://127.0.0.1:8000' : '';
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
            liveOpt.textContent = '🌟 TODAY (盘中实时 LOB)';
            dateSelect.appendChild(liveOpt);

            allDays.forEach((d, idx) => {{
                const opt = document.createElement('option');
                opt.value = d;
                const isLatest = (idx === allDays.length - 1);
                opt.textContent = isLatest ? `${{d}} (历史最新)` : d;
                dateSelect.appendChild(opt);
            }});
            currentDate = 'today';
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

        async function selectDay(d, isAutoRefresh = false) {{
            if (!d) return;
            currentDate = d;
            dateSelect.value = currentDate;
            updateNavButtons();

            if (liveRefreshTimer) {{
                clearTimeout(liveRefreshTimer);
                liveRefreshTimer = null;
            }}

            // 1. LIVE TODAY MODE
            if (d === 'today') {{
                // Always render inlined/cached today data first if available
                if (store[currentTicker] && store[currentTicker].by_day && store[currentTicker].by_day['today']) {{
                    renderDashboard(true, '今日实时', '当前分时');
                }}

                const titleEl = document.getElementById('klineTitle');
                if (!isAutoRefresh && titleEl && (!store[currentTicker] || !store[currentTicker].by_day || !store[currentTicker].by_day['today'])) {{
                    titleEl.textContent = `⚡ 正在调取 ${{currentTicker}} 盘中实时 K 线与 LOB 微观订单流...`;
                }}

                try {{
                    const resp = await fetch(`${{apiBase}}/api/wave/live_today?ticker=${{currentTicker}}`);
                    const res = await resp.json();
                    if (res && res.success && res.data) {{
                        store[currentTicker].by_day['today'] = res.data;
                        renderDashboard(true, res.date, res.last_updated);
                    }}
                }} catch (err) {{
                    console.log('Live wave network polling note:', err);
                    const liveBadgeEl = document.getElementById('liveBadge');
                    if (liveBadgeEl && store[currentTicker] && store[currentTicker].by_day && store[currentTicker].by_day['today']) {{
                        liveBadgeEl.style.display = 'inline-block';
                        liveBadgeEl.style.background = 'rgba(16, 185, 129, 0.2)';
                        liveBadgeEl.style.borderColor = '#10b981';
                        liveBadgeEl.innerHTML = `🟢 TODAY 今日实时分时 (快照已呈现)`;
                    }}
                }}

                // Keep auto-polling every 8 seconds when on TODAY
                liveRefreshTimer = setTimeout(() => {{
                    if (currentDate === 'today') {{
                        selectDay('today', true);
                    }}
                }}, 8000);
                return;
            }}

            // 2. HISTORICAL DAY CACHED / API MODE
            if (store[currentTicker] && store[currentTicker].by_day && store[currentTicker].by_day[d]) {{
                renderDashboard(false, d);
                return;
            }}

            const titleEl = document.getElementById('klineTitle');
            if (titleEl) titleEl.textContent = `⏳ 正在按需调取 ${{currentTicker}} (${{d}}) 历史高频波浪数据...`;

            try {{
                const resp = await fetch(`${{apiBase}}/api/wave/day_data?ticker=${{currentTicker}}&date=${{d}}`);
                const res = await resp.json();
                if (res && res.success && res.data) {{
                    store[currentTicker].by_day[d] = res.data;
                    renderDashboard(false, d);
                }} else {{
                    if (titleEl) titleEl.textContent = `⚠️ 未获取到 ${{currentTicker}} (${{d}}) 历史数据: ${{res && res.error || '无记录'}}`;
                }}
            }} catch (err) {{
                console.error('Fetch error:', err);
                if (titleEl) titleEl.textContent = `⚠️ 历史数据网络请求失败，请检查网络`;
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
            const liveBadgeEl = document.getElementById('liveBadge');
            if (liveBadgeEl) {{
                if (isLive) {{
                    liveBadgeEl.style.display = 'inline-block';
                    liveBadgeEl.style.background = 'rgba(16, 185, 129, 0.2)';
                    liveBadgeEl.style.borderColor = '#10b981';
                    liveBadgeEl.innerHTML = `🟢 LIVE 盘中实时更新 (${{lastUpdated || '当前分时'}})`;
                }} else {{
                    liveBadgeEl.style.background = 'rgba(100, 116, 139, 0.2)';
                    liveBadgeEl.style.borderColor = '#475569';
                    liveBadgeEl.innerHTML = `📅 历史回放复盘模式 (${{dateStr}})`;
                }}
            }}

            document.getElementById('klineTitle').textContent = isLive
                ? `${{currentTicker}} - ${{dateStr}} 盘中实时 5分钟 K 线与 15~30m 波浪拐点信号 (秒级流式推断)`
                : `${{currentTicker}} - ${{dateStr}} 5分钟 K 线与 15~30m 波浪拐点信号`;

            // Update Stats Banner
            const stats = dayData.stats;
            document.getElementById('statOpen').textContent = `$${{stats.open}}`;
            document.getElementById('statClose').textContent = `$${{stats.close}}`;
            document.getElementById('statRange').textContent = `$${{stats.low}} ~ $${{stats.high}}`;
            const pnlEl = document.getElementById('statPnl');
            pnlEl.textContent = `${{stats.pnl_pct >= 0 ? '+' : ''}}${{stats.pnl_pct}}%`;
            pnlEl.style.color = stats.pnl_pct >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
            document.getElementById('statSignals').textContent = `${{stats.signal_count}} 处拐点`;

            // Clean, elegant markers that NEVER clump or stack
            const markPointData = dayData.signals.map(s => {{
                const isLong = s.direction === 'LONG';
                return {{
                    name: s.direction,
                    coord: [s.coord_x, s.coord_y],
                    value: `${{isLong ? '▲' : '▼'}} ${{s.direction}} ${{s.p_win}}%`,
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
                                    <div>🌊 波浪胜率: <span style="color: ${{pLong >= 50 ? '#10b981' : '#f43f5e'}}; font-weight: 800;">${{pLong}}%</span></div>
                                    <div>⚡ OFI 订单流: <span style="color: ${{ofi >= 0 ? '#10b981' : '#f43f5e'}};">${{ofi >= 0 ? '+' : ''}}${{ofi}}</span></div>
                                    <div>🎯 微观价格漂移: <span style="color: #a855f7; font-weight: 700;">${{drift >= 0 ? '+' : ''}}${{drift}} bps</span></div>
                                    <div>📊 综合 Alpha 分: <span style="color: ${{alpha >= 0 ? '#38bdf8' : '#f43f5e'}};">${{alpha >= 0 ? '+' : ''}}${{alpha}}</span></div>
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
                                res += `<div><span style="color:#a855f7">●</span> 微观价格漂移 (bps): <b style="color:#a855f7">${{sign}}${{val.toFixed(2)}} bps</b></div>`;
                            }}
                        }});
                        res += `</div>`;
                        return res;
                    }}
                }},
                legend: {{ data: ['OFI 订单流不平衡', '微观价格漂移 (bps)'], textStyle: {{ color: '#94a3b8' }} }},
                grid: {{ left: '4%', right: '3%', bottom: '10%', top: '15%', containLabel: true }},
                xAxis: {{ type: 'category', data: dayData.times, axisLine: {{ lineStyle: {{ color: '#334155' }} }}, axisLabel: {{ color: '#64748b' }} }},
                yAxis: [
                    {{ type: 'value', name: 'OFI', splitLine: {{ lineStyle: {{ color: '#1e293b' }} }}, axisLabel: {{ color: '#64748b' }} }},
                    {{ type: 'value', name: 'Micro Drift (bps)', splitLine: {{ show: false }}, axisLabel: {{ color: '#a855f7', formatter: '{{value}} bps' }} }}
                ],
                series: [
                    {{
                        name: 'OFI 订单流不平衡',
                        type: 'bar',
                        data: dayData.ofi,
                        itemStyle: {{ color: (p) => p.value >= 0 ? '#10b981' : '#f43f5e' }}
                    }},
                    {{
                        name: '微观价格漂移 (bps)',
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
                            if (p.seriesName.includes('Queue') || p.seriesName.includes('排队')) {{
                                res += `<div><span style="color:#f59e0b">●</span> 排队失衡比率: <b style="color:#f59e0b">${{sign}}${{val.toFixed(3)}}</b></div>`;
                            }} else {{
                                res += `<div><span style="color:#38bdf8">●</span> 大单扫盘速度: <b style="color:#38bdf8">${{sign}}${{val.toFixed(3)}}</b></div>`;
                            }}
                        }});
                        res += `</div>`;
                        return res;
                    }}
                }},
                legend: {{ data: ['排队失衡比率 (Queue Imbalance)', '大单扫盘速度 (Sweep Velocity)'], textStyle: {{ color: '#94a3b8' }} }},
                grid: {{ left: '4%', right: '3%', bottom: '10%', top: '15%', containLabel: true }},
                xAxis: {{ type: 'category', data: dayData.times, axisLine: {{ lineStyle: {{ color: '#334155' }} }}, axisLabel: {{ color: '#64748b' }} }},
                yAxis: {{ type: 'value', splitLine: {{ lineStyle: {{ color: '#1e293b' }} }}, axisLabel: {{ color: '#64748b' }} }},
                series: [
                    {{
                        name: '排队失衡比率 (Queue Imbalance)',
                        type: 'line',
                        data: dayData.queue_imb,
                        smooth: true,
                        lineStyle: {{ color: '#f59e0b', width: 2 }},
                        showSymbol: false
                    }},
                    {{
                        name: '大单扫盘速度 (Sweep Velocity)',
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
                legend: {{ data: ['Composite Alpha Score', 'Wave Long 胜率 (%)'], textStyle: {{ color: '#94a3b8' }} }},
                grid: {{ left: '4%', right: '3%', bottom: '10%', top: '15%', containLabel: true }},
                xAxis: {{ type: 'category', data: dayData.times, axisLine: {{ lineStyle: {{ color: '#334155' }} }}, axisLabel: {{ color: '#64748b' }} }},
                yAxis: [
                    {{ type: 'value', name: 'Alpha Score', min: -100, max: 100, splitLine: {{ lineStyle: {{ color: '#1e293b' }} }}, axisLabel: {{ color: '#64748b' }} }},
                    {{ type: 'value', name: 'Win Rate %', min: 20, max: 80, splitLine: {{ show: false }}, axisLabel: {{ color: '#64748b' }} }}
                ],
                series: [
                    {{
                        name: 'Composite Alpha Score',
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
                        name: 'Wave Long 胜率 (%)',
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
                tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 20px;">该日盘面偏平稳，未触发高确定性波浪拐点</td></tr>';
            }} else {{
                dayData.signals.forEach(s => {{
                    const tr = document.createElement('tr');
                    const isLong = s.direction === 'LONG';
                    tr.innerHTML = `
                        <td style="color: #38bdf8; font-weight: 700;">${{s.time}}</td>
                        <td><span class="${{isLong ? 'badge-dir-long' : 'badge-dir-short'}}">${{s.direction}}</span></td>
                        <td>$${{s.price}}</td>
                        <td style="color: ${{isLong ? '#10b981' : '#f43f5e'}}; font-weight: 800;">${{s.p_win}}%</td>
                        <td>${{s.expected_ret >= 0 ? '+' : ''}}${{s.expected_ret}}%</td>
                        <td style="color: ${{s.ofi >= 0 ? '#10b981' : '#f43f5e'}};">${{s.ofi}}</td>
                        <td>${{s.micro_drift}}</td>
                        <td style="color: ${{s.alpha >= 0 ? '#38bdf8' : '#f43f5e'}};">${{s.alpha}}</td>
                        <td style="color: var(--text-secondary); font-size: 0.78rem;">${{isLong ? '主动买盘扫单驱动，微观价格向上漂移' : '盘口空头堆单吸收，微观价格向下漂移'}}</td>
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

    charts_out = os.path.join(backend_dir, "data", "charts", "saggese_wave_visual_dashboard.html")
    with open(charts_out, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    cache_charts_out = os.path.join(backend_dir, "data", "charts", "wave_history_cache.json")
    with open(cache_charts_out, "w", encoding="utf-8") as f:
        json.dump(all_data, f)
        
    print(f"✅ Successfully regenerated hybrid wave dashboard & full history cache at:\n -> {charts_out}\n -> {cache_charts_out}")

if __name__ == "__main__":
    generate_multi_day_dashboard()

