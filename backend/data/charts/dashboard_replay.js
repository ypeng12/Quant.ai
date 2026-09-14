(function () {
  'use strict';

  const symbols = ['TSLA', 'NVDA', 'SNDK', 'PLTR'];
  const comparison = Boolean(document.getElementById('datePicker'));
  let currentTicker = 'TSLA';
  let currentDate = '';
  let currentTimeframe = '5m';
  let currentMode = 'real';
  let market = null;
  let fills = [];
  let replayIndex = 0;
  let timer = null;
  let speed = 1;
  let requestSequence = 0;

  const byId = (id) => document.getElementById(id);
  const setText = (id, value) => { const node = byId(id); if (node) node.textContent = value; };
  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function ema(values, period) {
    const factor = 2 / (period + 1);
    let previous = values[0];
    return values.map((value, index) => {
      previous = index ? value * factor + previous * (1 - factor) : value;
      return Number(previous.toFixed(4));
    });
  }

  function vwap(data) {
    let value = 0, volume = 0;
    return data.close.map((close, index) => {
      const typical = (data.high[index] + data.low[index] + close) / 3;
      value += typical * data.volume[index];
      volume += data.volume[index];
      return volume ? Number((value / volume).toFixed(4)) : close;
    });
  }

  function chartOption(data, limit, includeFills) {
    const end = Math.max(1, Math.min(limit, data.time.length));
    const times = data.time.slice(0, end);
    const closes = data.close.slice(0, end);
    const candles = times.map((_, i) => [data.open[i], data.close[i], data.low[i], data.high[i]]);
    const volume = data.volume.slice(0, end).map((value, i) => ({
      value,
      itemStyle: { color: data.close[i] >= data.open[i] ? '#10b981' : '#ef4444' }
    }));
    const annotations = includeFills ? fills.filter(fill => times.includes(fill.time.slice(11, 16))) : [];
    const markerSeries = ['BUY', 'SELL', 'SHORT', 'COVER'].map(action => ({
      name: action,
      type: 'scatter',
      symbol: action === 'BUY' || action === 'COVER' ? 'triangle' : 'pin',
      symbolRotate: action === 'BUY' || action === 'COVER' ? 0 : 180,
      symbolSize: 13,
      itemStyle: { color: action === 'BUY' || action === 'COVER' ? '#22c55e' : '#ef4444' },
      data: annotations.filter(fill => fill.action === action).map(fill => [fill.time.slice(11, 16), fill.price]),
      tooltip: { valueFormatter: value => `$${Number(value).toFixed(2)}` }
    }));
    return {
      animation: false,
      backgroundColor: '#131722',
      title: {
        text: `${data.ticker} · ${data.date} · ${data.interval.toUpperCase()}`,
        subtext: `${data.data_provenance.bar_count} 根已观测 K 线 · 覆盖至 ${data.data_provenance.last_bar_end.slice(11, 16)} · ${data.data_provenance.source}`,
        left: 12, top: 8, textStyle: { color: '#e2e8f0', fontSize: 14 }, subtextStyle: { color: '#94a3b8', fontSize: 11 }
      },
      legend: { top: 10, right: 18, textStyle: { color: '#94a3b8' }, data: ['K线', 'EMA9', 'EMA21', 'VWAP'] },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, backgroundColor: '#0f172a', borderColor: '#334155', textStyle: { color: '#e2e8f0' } },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [{ left: 58, right: 22, top: 58, height: '65%' }, { left: 58, right: 22, top: '78%', height: '14%' }],
      xAxis: [
        { type: 'category', data: times, boundaryGap: true, axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#94a3b8', interval: Math.max(0, Math.floor(times.length / 8) - 1) }, splitLine: { show: false } },
        { type: 'category', gridIndex: 1, data: times, boundaryGap: true, axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { show: false }, splitLine: { show: false } }
      ],
      yAxis: [
        { scale: true, axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#1e293b' } } },
        { gridIndex: 1, scale: true, axisLabel: { color: '#64748b' }, splitLine: { show: false } }
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 }],
      series: [
        { name: 'K线', type: 'candlestick', data: candles, itemStyle: { color: '#10b981', color0: '#ef4444', borderColor: '#10b981', borderColor0: '#ef4444' } },
        { name: 'EMA9', type: 'line', data: ema(closes, 9), showSymbol: false, lineStyle: { color: '#38bdf8', width: 1.4 } },
        { name: 'EMA21', type: 'line', data: ema(closes, 21), showSymbol: false, lineStyle: { color: '#f59e0b', width: 1.2 } },
        { name: 'VWAP', type: 'line', data: vwap({ ...data, close: closes, high: data.high.slice(0, end), low: data.low.slice(0, end), volume: data.volume.slice(0, end) }), showSymbol: false, lineStyle: { color: '#a855f7', width: 1.2, type: 'dashed' } },
        { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volume },
        ...markerSeries
      ]
    };
  }

  function draw(id, limit, showFills) {
    const node = byId(id);
    if (!node || !market || typeof echarts === 'undefined') return;
    const chart = echarts.getInstanceByDom(node) || echarts.init(node, null, { renderer: 'canvas' });
    chart.setOption(chartOption(market, limit, showFills), true);
  }

  function showError(message) {
    ['dynamicChart', 'plotlyChart'].forEach(id => {
      const node = byId(id);
      if (node) {
        if (typeof echarts !== 'undefined' && echarts.getInstanceByDom(node)) echarts.dispose(node);
        node.innerHTML = `<div style="padding:48px;color:#fca5a5;text-align:center">${escapeHtml(message)}</div>`;
      }
    });
  }

  function updateStaticLabels() {
    setText('livePnlDisplay', '模拟净收益：—（未运行策略）');
    setText('mlPwin', '—');
    setText('mlEPnl', '—');
    setText('mlKelly', '—');
    setText('simTickerText', currentTicker);
    setText('activeTickerBadge', `当前联动股票: ${currentTicker}`);
    setText('orderTickerTag', currentTicker);
  }

  function updateLedger() {
    const body = byId('ledgerBody');
    if (!body) return;
    if (currentMode === 'ml') {
      body.innerHTML = '<tr><td colspan="12" style="padding:20px;color:#94a3b8;text-align:center">没有该日期的已验证 ML 策略成交，未生成模拟盈亏。</td></tr>';
      return;
    }
    if (!fills.length) {
      body.innerHTML = '<tr><td colspan="12" style="padding:20px;color:#94a3b8;text-align:center">该日期与股票没有本地券商确认成交。</td></tr>';
      return;
    }
    body.innerHTML = fills.map(fill => `<tr>
      <td>${escapeHtml(currentTicker)}</td><td><span class="badge ${fill.action === 'BUY' || fill.action === 'COVER' ? 'badge-buy' : 'badge-short'}">${escapeHtml(fill.action)}</span></td>
      <td>${escapeHtml(fill.time.slice(11, 19))}</td><td>$${fill.price.toFixed(4)}</td><td>—</td><td>—</td><td>—</td>
      <td>${fill.shares}</td><td>$${(fill.shares * fill.price).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td><td>未做 FIFO 配对</td><td>—</td><td>${escapeHtml(fill.source)}</td>
    </tr>`).join('');
  }

  function renderAll() {
    if (!market) return;
    draw('dynamicChart', replayIndex || market.time.length, currentMode === 'real');
    draw('plotlyChart', market.time.length, currentMode === 'real');
    updateLedger();
  }

  function populateControls() {
    const picker = byId('datePicker');
    if (picker && market) {
      picker.innerHTML = market.available_dates.map(date => `<option value="${date}"${date === market.date ? ' selected' : ''}>${date}</option>`).join('');
    }
    const pills = byId('tickerPills');
    if (pills) pills.innerHTML = symbols.map(symbol => `<button class="ticker-pill${symbol === currentTicker ? ' active' : ''}" onclick="setTicker('${symbol}')">${symbol}</button>`).join('');
  }

  async function loadData(preferredDate) {
    const sequence = ++requestSequence;
    stopReplay();
    showError('正在读取完整历史行情…');
    try {
      const query = new URLSearchParams({ ticker: currentTicker, interval: currentTimeframe });
      if (preferredDate) query.set('date', preferredDate);
      const response = await fetch(`/api/dashboard/market_data?${query}`);
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || '历史行情不可用');
      if (sequence !== requestSequence) return;
      market = data;
      currentDate = data.date;
      const fillResponse = await fetch(`/api/dashboard/trades?ticker=${encodeURIComponent(currentTicker)}&date=${encodeURIComponent(currentDate)}`);
      const fillData = await fillResponse.json();
      fills = fillData.success && Array.isArray(fillData.fills) ? fillData.fills : [];
      replayIndex = data.time.length;
      updateStaticLabels();
      populateControls();
      renderAll();
    } catch (error) {
      if (sequence === requestSequence) showError(error instanceof Error ? error.message : '历史行情不可用');
    }
  }

  function stopReplay() {
    if (timer) window.clearInterval(timer);
    timer = null;
    const button = byId('btnPlay');
    if (button) button.textContent = '▶ 播放仿真';
  }

  window.togglePlay = function () {
    if (!market) return;
    if (timer) { stopReplay(); return; }
    if (replayIndex >= market.time.length) replayIndex = Math.min(5, market.time.length);
    const button = byId('btnPlay');
    if (button) button.textContent = '⏸ 暂停';
    timer = window.setInterval(() => {
      replayIndex = Math.min(market.time.length, replayIndex + 1);
      draw('dynamicChart', replayIndex, currentMode === 'real');
      if (replayIndex >= market.time.length) stopReplay();
    }, Math.max(70, 650 / speed));
  };

  window.resetReplay = function () {
    stopReplay();
    if (market) replayIndex = market.time.length;
    renderAll();
    const stream = byId('orderStream');
    if (stream) stream.innerHTML = '<div style="color:#64748b;font-size:12px;text-align:center;padding:15px">播放使用真实历史 K 线；不会自动生成交易。</div>';
    setText('orderCount', '0 笔');
  };

  window.setSpeed = function (value, button) {
    speed = Number(value) || 1;
    document.querySelectorAll('.speed-btn').forEach(node => node.classList.remove('active'));
    if (button) button.classList.add('active');
  };
  window.setTicker = function (symbol) { currentTicker = symbols.includes(symbol) ? symbol : 'TSLA'; loadData(currentDate); };
  window.setTimeframe = function (interval) {
    currentTimeframe = ['1m', '5m', '15m', '30m'].includes(interval) ? interval : '5m';
    document.querySelectorAll('.tf-pill').forEach(node => node.classList.toggle('active', node.textContent.toLowerCase() === currentTimeframe));
    loadData(currentDate);
  };
  window.onDateChange = function (date) { loadData(date); };
  window.switchMode = function (mode) {
    currentMode = mode === 'ml' ? 'ml' : 'real';
    byId('btnReal')?.classList.toggle('active', currentMode === 'real');
    byId('btnMl')?.classList.toggle('active', currentMode === 'ml');
    renderAll();
  };
  window.onOfiChange = value => setText('valOfi', Number(value).toFixed(2));
  window.onVelChange = value => setText('valVel', `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(2)}`);
  window.triggerManualOrder = function () {
    const stream = byId('orderStream');
    if (!stream || !market) return;
    const time = market.time[Math.max(0, Math.min(replayIndex - 1, market.time.length - 1))];
    stream.innerHTML = `<div class="order-ticket"><strong>${escapeHtml(time)} · ${escapeHtml(currentTicker)}</strong><br>记录了手动情景输入；没有发送券商订单，也没有生成假盈亏。</div>` + stream.innerHTML;
    setText('orderCount', '1 条输入');
  };

  window.addEventListener('resize', () => ['dynamicChart', 'plotlyChart'].forEach(id => {
    const node = byId(id); const chart = node && typeof echarts !== 'undefined' ? echarts.getInstanceByDom(node) : null; chart?.resize();
  }));
  updateStaticLabels();
  loadData('');
})();
