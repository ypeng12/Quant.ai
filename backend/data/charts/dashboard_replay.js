(function () {
  'use strict';

  const symbols = ['TSLA', 'NVDA', 'SNDK', 'PLTR'];
  const parentOrigin = (() => {
    try {
      const referrer = new URL(document.referrer);
      return ['http:', 'https:'].includes(referrer.protocol) ? referrer.origin : window.location.origin;
    } catch { return window.location.origin; }
  })();
  const initial = new URLSearchParams(window.location.search);
  let currentTicker = symbols.includes(initial.get('ticker')) ? initial.get('ticker') : 'TSLA';
  let currentDate = /^\d{4}-\d{2}-\d{2}$/.test(initial.get('date') || '') ? initial.get('date') : '';
  let currentTimeframe = ['1m', '5m', '15m', '30m'].includes(initial.get('interval')) ? initial.get('interval') : '5m';
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
  const etTime = new Intl.DateTimeFormat('en-GB', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const etSeconds = new Intl.DateTimeFormat('en-GB', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
  const actions = {
    BUY: { letter: 'B', label: '买入', color: '#fb7185', rotation: 0 },
    SELL: { letter: 'S', label: '卖出', color: '#10b981', rotation: 180 },
    SHORT: { letter: 'X', label: '做空', color: '#f59e0b', rotation: 180 },
    COVER: { letter: 'C', label: '平空', color: '#a78bfa', rotation: 0 }
  };

  function fillTimestamp(fill, data) {
    // Broker archives may store an ET wall-clock timestamp without a UTC offset.
    // Anchor those records to the selected session's explicit market-data offset,
    // never the browser's local timezone or a rounded five-minute label.
    let value = String(fill.time || '').replace(' ', 'T');
    if (/^\d{2}:\d{2}/.test(value)) value = `${data.date}T${value}`;
    if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(value)) {
      const offset = String(data.full_time?.[0] || '').match(/(Z|[+-]\d{2}:?\d{2})$/i);
      if (!offset) return NaN;
      value += offset[0];
    }
    return Date.parse(value);
  }

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
    const intervalMs = Number.parseInt(data.interval, 10) * 60000;
    const starts = data.full_time.map(value => Date.parse(value));
    // A closing price becomes available at the end of its bar.
    const times = starts.slice(0, end).map(value => value + intervalMs);
    const closes = data.close.slice(0, end);
    const candles = times.map((time, i) => [time, data.open[i], data.close[i], data.low[i], data.high[i]]);
    const volume = data.volume.slice(0, end).map((value, i) => ({
      value: [times[i], value],
      itemStyle: { color: data.close[i] >= data.open[i] ? '#10b981' : '#ef4444' }
    }));
    const annotations = includeFills ? fills.map(fill => ({ ...fill, timestamp: fillTimestamp(fill, data) }))
      .filter(fill => Number.isFinite(fill.timestamp) && fill.timestamp >= starts[0] && fill.timestamp <= times[end - 1]) : [];
    const markerSeries = Object.entries(actions).map(([action, style]) => ({
      name: `${style.letter} ${style.label}`,
      type: 'scatter',
      symbol: 'triangle', symbolRotate: style.rotation, symbolSize: 12, z: 8,
      itemStyle: { color: style.color },
      label: { show: true, position: style.rotation ? 'bottom' : 'top', color: style.color, fontSize: 10,
        formatter: params => `${style.letter}${params.data.shares}` },
      labelLayout: { hideOverlap: true },
      data: annotations.filter(fill => fill.action === action).map(fill => ({ value: [fill.timestamp, fill.price], shares: fill.shares, source: fill.source })),
      tooltip: { trigger: 'item', formatter: params => `${escapeHtml(etSeconds.format(params.value[0]))} ET · ${style.letter} ${style.label}<br>${params.data.shares} 股 · $${Number(params.value[1]).toFixed(4)}<br>${escapeHtml(params.data.source || 'broker_archive')}` }
    }));
    const pair = values => values.map((value, index) => [times[index], value]);
    const timeAxis = { type: 'time', min: starts[0], max: starts[starts.length - 1] + intervalMs,
      axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#94a3b8', formatter: value => etTime.format(value) }, splitLine: { show: false } };
    return {
      animation: false,
      backgroundColor: '#131722',
      title: {
        text: `${data.ticker} · ${data.date} · ${data.interval.toUpperCase()}`,
        subtext: `${end}/${data.time.length} 根已完成 · 复盘至 ${etTime.format(times[end - 1])} ET · ${data.data_provenance.source}`,
        left: 12, top: 8, textStyle: { color: '#e2e8f0', fontSize: 14 }, subtextStyle: { color: '#94a3b8', fontSize: 11 }
      },
      legend: { type: 'scroll', top: 54, left: 12, right: 18, textStyle: { color: '#94a3b8', fontSize: 10 },
        data: ['PRICE', 'OHLCV VWAP 近似', 'B 买入', 'S 卖出', 'X 做空', 'C 平空', 'K线', 'EMA9', 'EMA21'],
        selected: { K线: false, EMA9: false, EMA21: false } },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross', label: { formatter: params => params.axisDimension === 'x' ? `${etTime.format(params.value)} ET` : Number(params.value).toFixed(2) } },
        formatter: params => {
          const rows = params.filter(row => row.seriesType !== 'scatter');
          if (!rows.length) return '';
          return `${etTime.format(rows[0].value[0])} ET<br>` + rows.map(row => row.seriesType === 'candlestick'
            ? `${row.marker} K线 O ${row.value[1]} · C ${row.value[2]} · L ${row.value[3]} · H ${row.value[4]}`
            : `${row.marker} ${escapeHtml(row.seriesName)}: ${row.seriesName === '成交量' ? Number(row.value[1]).toLocaleString() : '$' + Number(row.value[1]).toFixed(2)}`).join('<br>');
        }, backgroundColor: '#0f172a', borderColor: '#334155', textStyle: { color: '#e2e8f0' } },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [{ left: 58, right: 22, top: 92, bottom: '29%' }, { left: 58, right: 22, top: '78%', bottom: 28 }],
      xAxis: [timeAxis, { ...timeAxis, gridIndex: 1 }],
      yAxis: [
        { scale: true, axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#1e293b' } } },
        { gridIndex: 1, scale: true, axisLabel: { color: '#64748b', formatter: value => Math.abs(value) >= 1000000 ? `${(value / 1000000).toFixed(1)}M` : Math.abs(value) >= 1000 ? `${(value / 1000).toFixed(0)}k` : value }, splitLine: { show: false } }
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 }],
      series: [
        { name: 'PRICE', type: 'line', data: pair(closes), smooth: false, showSymbol: false, itemStyle: { color: '#38bdf8' }, lineStyle: { color: '#38bdf8', width: 2 } },
        { name: 'OHLCV VWAP 近似', type: 'line', data: pair(vwap({ ...data, close: closes })), smooth: false, showSymbol: false, itemStyle: { color: '#f59e0b' }, lineStyle: { color: '#f59e0b', width: 1.6 } },
        { name: 'K线', type: 'candlestick', data: candles, encode: { x: 0, y: [1, 2, 3, 4] }, itemStyle: { color: '#10b981', color0: '#ef4444', borderColor: '#10b981', borderColor0: '#ef4444' } },
        { name: 'EMA9', type: 'line', data: pair(ema(closes, 9)), showSymbol: false, itemStyle: { color: '#a78bfa' }, lineStyle: { color: '#a78bfa', width: 1.2 } },
        { name: 'EMA21', type: 'line', data: pair(ema(closes, 21)), showSymbol: false, itemStyle: { color: '#94a3b8' }, lineStyle: { color: '#94a3b8', width: 1.2 } },
        { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volume },
        ...markerSeries
      ]
    };
  }

  function draw(id, limit, showFills) {
    const node = byId(id);
    if (!node || !market || typeof echarts === 'undefined') return;
    const chart = echarts.getInstanceByDom(node) || echarts.init(node, null, { renderer: 'canvas' });
    const option = chartOption(market, limit, showFills);
    const selected = chart.getOption()?.legend?.[0]?.selected;
    if (selected) option.legend.selected = { ...option.legend.selected, ...selected };
    chart.setOption(option, true);
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
    document.querySelectorAll('.tf-pill').forEach(node => node.classList.toggle('active', node.textContent.toLowerCase() === currentTimeframe));
  }

  async function loadData(preferredDate) {
    const sequence = ++requestSequence;
    const requestedTicker = currentTicker;
    const requestedTimeframe = currentTimeframe;
    stopReplay();
    showError('正在读取完整历史行情…');
    try {
      const query = new URLSearchParams({ ticker: requestedTicker, interval: requestedTimeframe });
      if (preferredDate) query.set('date', preferredDate);
      const response = await fetch(`/api/dashboard/market_data?${query}`);
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || '历史行情不可用');
      if (sequence !== requestSequence) return;
      const fillResponse = await fetch(`/api/dashboard/trades?ticker=${encodeURIComponent(requestedTicker)}&date=${encodeURIComponent(data.date)}`);
      const fillData = await fillResponse.json();
      if (sequence !== requestSequence) return;
      market = data;
      currentDate = data.date;
      fills = fillData.success && Array.isArray(fillData.fills) ? fillData.fills : [];
      replayIndex = data.time.length;
      updateStaticLabels();
      populateControls();
      renderAll();
      if (window.parent !== window) window.parent.postMessage({ type: 'quant-replay-selection-change', ticker: currentTicker, date: currentDate, interval: currentTimeframe }, parentOrigin);
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
    if (replayIndex >= market.time.length) replayIndex = 1;
    draw('dynamicChart', replayIndex, currentMode === 'real');
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
    if (market) replayIndex = 1;
    renderAll();
    const stream = byId('orderStream');
    if (stream) stream.innerHTML = '<div style="color:#64748b;font-size:12px;text-align:center;padding:15px">播放使用真实历史 K 线；不会自动生成交易。</div>';
    setText('orderCount', '0 笔');
  };

  window.setSpeed = function (value, button) {
    const playing = Boolean(timer);
    speed = Number(value) || 1;
    document.querySelectorAll('.speed-btn').forEach(node => node.classList.remove('active'));
    if (button) button.classList.add('active');
    if (playing) { stopReplay(); window.togglePlay(); }
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
  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.origin !== parentOrigin || event.data?.type !== 'quant-replay-selection') return;
    const { ticker, date, interval } = event.data;
    const symbol = symbols.includes(ticker) ? ticker : currentTicker;
    const day = /^\d{4}-\d{2}-\d{2}$/.test(date || '') ? date : currentDate;
    const timeframe = ['1m', '5m', '15m', '30m'].includes(interval) ? interval : currentTimeframe;
    if (symbol === currentTicker && day === currentDate && timeframe === currentTimeframe) return;
    currentTicker = symbol;
    currentTimeframe = timeframe;
    loadData(day);
  });
  updateStaticLabels();
  loadData(currentDate);
})();
