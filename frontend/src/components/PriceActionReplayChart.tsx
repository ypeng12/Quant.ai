import { useEffect, useId, useMemo, useState } from 'react';
import type { MouseEvent } from 'react';
import { API_BASE } from '../config';
import './PriceActionReplayChart.css';

type Bar = { time: string; open: number; high: number; low: number; close: number; volume: number; vwap: number | null };
type Fill = { time: string; action: 'B' | 'S' | 'C' | 'X'; shares: number; price: number; reference_price: number; commission_cost: number; shares_after: number };
type Mark = { time: string; shares: number; pnl: number | null };
type ReplayData = {
  success: boolean; error?: string; ticker: string; date: string; available_dates: string[];
  variants: Array<string | { value?: string; id?: string; label?: string }>;
  variant: string; source_label: string; is_simulated: boolean; as_of: string;
  partial: boolean; starting_equity: number; cost_bps: number; opening_shares: number;
  bars: Bar[]; fills: Fill[]; marks: Mark[];
  summary: { net_pnl: number; gross_pnl: number; cost: number; fill_count: number; ending_shares: number };
};

interface Props {
  ticker: string;
  watchlist: string[];
  onSelectTicker: (ticker: string) => void;
  refreshKey?: number;
}

const marketTime = new Intl.DateTimeFormat('en-GB', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
const minute = (time: string) => {
  const [h, m, s] = marketTime.format(new Date(time)).split(':').map(Number);
  return h * 60 + m + s / 60 - 570;
};
const timeLabel = (m: number) => `${Math.floor((m + 570) / 60).toString().padStart(2, '0')}:${Math.floor((m + 570) % 60).toString().padStart(2, '0')}`;
const money = (value: number | null | undefined) => Number.isFinite(value) ? `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';
const variants: Record<string, string> = { context: '原 Context', levels: '支撑压力', levels_error_risk: '支撑压力＋误差风险' };
const actions = { B: { label: '买入开多', color: '#fb7185' }, S: { label: '卖出多仓', color: '#34d399' }, C: { label: '平空', color: '#c4a0f4' }, X: { label: '开空', color: '#fbbf24' } };

function bounds(values: number[], includeZero = false): [number, number] {
  const finite = values.filter(Number.isFinite);
  if (includeZero || finite.length === 0) finite.push(0);
  const low = Math.min(...finite), high = Math.max(...finite);
  const padding = Math.max((high - low) * .12, high === low ? Math.max(Math.abs(high) * .002, .1) : .01);
  return [low - padding, high + padding];
}

export function PriceActionReplayChart({ ticker, watchlist, onSelectTicker, refreshKey }: Props) {
  const [date, setDate] = useState('');
  const [variant, setVariant] = useState('levels_error_risk');
  const [dates, setDates] = useState<string[]>([]);
  const [data, setData] = useState<ReplayData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [count, setCount] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [range, setRange] = useState<[number, number]>([0, 390]);
  const [hover, setHover] = useState<number | null>(null);
  const clip = useId().replace(/:/g, '');

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setData(null); setError(''); setPlaying(false); setHover(null);
    const query = new URLSearchParams({ ticker, variant });
    if (date) query.set('date', date);
    fetch(`${API_BASE}/api/dashboard/price_replay?${query}`, { signal: controller.signal })
      .then(async response => {
        const result: ReplayData = await response.json();
        if (controller.signal.aborted) return;
        if (result.available_dates?.length) setDates(result.available_dates);
        if (!response.ok || !result.success || !result.bars?.length) throw new Error(result.error || '这个股票和日期暂无保存的研究回放。');
        setData(result); setCount(result.bars.length);
      }).catch(reason => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '读取回放失败');
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [ticker, date, variant, refreshKey]);

  useEffect(() => {
    if (!playing || !data) return;
    const timer = window.setInterval(() => setCount(value => Math.min(value + 1, data.bars.length)), 650 / speed);
    return () => window.clearInterval(timer);
  }, [playing, speed, data]);
  useEffect(() => { if (data && count >= data.bars.length) setPlaying(false); }, [count, data]);

  const visible = useMemo(() => {
    const bars = data?.bars.slice(0, count) || [];
    const until = bars.length ? Date.parse(bars[bars.length - 1].time) : -Infinity;
    return { bars, fills: data?.fills.filter(fill => Date.parse(fill.time) <= until) || [], marks: data?.marks.filter(mark => Date.parse(mark.time) <= until) || [] };
  }, [data, count]);
  const valuation = useMemo(() => {
    // Saved close marks precede next-open executions sharing that timestamp.
    // Append their cash/inventory effect so replay never pairs new holdings
    // with a pre-fill PnL (nor subtracts embedded slippage twice).
    return visible.marks.flatMap(mark => {
      const bar = visible.bars.find(item => item.time === mark.time);
      const sameTimeFills = visible.fills.filter(fill => fill.time === mark.time);
      if (!bar || mark.pnl === null || !sameTimeFills.length) return [mark];
      let cash = mark.pnl - mark.shares * bar.close;
      let shares = mark.shares;
      for (const fill of sameTimeFills) {
        cash -= (fill.shares_after - shares) * fill.price + fill.commission_cost;
        shares = fill.shares_after;
      }
      return [mark, { time: mark.time, shares, pnl: cash + shares * sameTimeFills.at(-1)!.reference_price }];
    });
  }, [visible]);
  const activeBar = visible.bars.length ? visible.bars[hover === null ? visible.bars.length - 1 : Math.min(hover, visible.bars.length - 1)] : undefined;
  const latestMark = valuation.at(-1);
  const lastShares = visible.fills.at(-1)?.shares_after ?? data?.opening_shares ?? 0;
  const width = 1200, left = 76, right = 28, plotWidth = width - left - right;
  const panels = [{ top: 28, height: 338, label: '价格 ($)' }, { top: 400, height: 82, label: '成交量' }, { top: 513, height: 82, label: '持仓 (股)' }, { top: 626, height: 82, label: '净盈亏 ($)' }];
  const x = (m: number) => left + (m - range[0]) / (range[1] - range[0]) * plotWidth;
  const priceBounds = bounds([...visible.bars.flatMap(bar => [bar.close, ...(bar.vwap === null ? [] : [bar.vwap])]), ...visible.fills.map(fill => fill.price)]);
  const shareBounds = bounds([data?.opening_shares || 0, ...visible.fills.map(fill => fill.shares_after)], true);
  const pnlBounds = bounds(valuation.flatMap(mark => mark.pnl === null ? [] : [mark.pnl]), true);
  const volumeMax = Math.max(1, ...visible.bars.map(bar => bar.volume));
  const domains = [priceBounds, [0, volumeMax * 1.1], shareBounds, pnlBounds];
  const y = (value: number, panel: number) => panels[panel].top + panels[panel].height * (1 - (value - domains[panel][0]) / (domains[panel][1] - domains[panel][0]));
  const path = (points: Array<[number, number | null]>, panel: number, step = false) => {
    let started = false;
    return points.map(([m, value]) => {
      if (value === null || !Number.isFinite(value)) { started = false; return ''; }
      const command = !started ? 'M' : step ? 'H' : 'L'; started = true;
      return step && command === 'H' ? `H${x(m)}V${y(value, panel)}` : `${command}${x(m)},${y(value, panel)}`;
    }).join(' ');
  };
  const sharePoints: Array<[number, number]> = [[0, data?.opening_shares || 0], ...visible.fills.map(fill => [minute(fill.time), fill.shares_after] as [number, number])];
  if (visible.bars.length) sharePoints.push([minute(visible.bars.at(-1)!.time), lastShares]);
  const step = range[1] - range[0] <= 150 ? 15 : 30;
  const ticks: number[] = [];
  for (let m = Math.ceil(range[0] / step) * step; m <= range[1]; m += step) ticks.push(m);
  const handleHover = (event: MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const position = (event.clientX - rect.left) / rect.width * width;
    const target = range[0] + (position - left) / plotWidth * (range[1] - range[0]);
    let best = 0;
    visible.bars.forEach((bar, index) => { if (Math.abs(minute(bar.time) - target) < Math.abs(minute(visible.bars[best].time) - target)) best = index; });
    setHover(best);
  };
  const zoom = (factor: number) => setRange(previous => {
    const span = Math.min(390, Math.max(30, (previous[1] - previous[0]) * factor));
    const start = Math.max(0, Math.min(390 - span, (previous[0] + previous[1] - span) / 2));
    return [start, start + span];
  });
  const symbols = [...new Set([ticker, ...watchlist, 'SNDK', 'TSLA', 'NVDA', 'PLTR'])];
  const variantChoices = data?.variants?.map(item => typeof item === 'string' ? item : item.id || item.value || '').filter(Boolean) || Object.keys(variants);

  return <section className="price-replay" aria-label="价格与买卖点回放">
    <header className="price-replay-heading">
      <div>
        <div className="price-replay-eyebrow">QUANT.AI · 价格与买卖点复盘</div>
        <div className="price-replay-price">{money(activeBar?.close)} <span>{ticker}</span></div>
        <div className="price-replay-subtitle">{data ? `${data.date} · 截至 ${marketTime.format(new Date(data.as_of)).slice(0, 5)} 美东 · ${data.partial ? '盘中保存' : '完整交易日'}` : '读取已保存的行情与成交'}</div>
      </div>
      <div className="price-replay-selectors">
        <label>日期 <select aria-label="价格回放日期" value={date || data?.date || ''} onChange={event => setDate(event.target.value)}>
          {!dates.length && <option value="">最近保存</option>}
          {date && dates.length > 0 && !dates.includes(date) && <option value={date}>{date} · 暂无研究回放</option>}
          {dates.map(value => <option key={value} value={value}>{value}</option>)}
        </select></label>
        <label>研究模型 <select aria-label="回放研究模型" value={variant} onChange={event => setVariant(event.target.value)}>
          {variantChoices.map(value => <option key={value} value={value}>{variants[value] || value}</option>)}
        </select></label>
        <div className="price-replay-symbols">{symbols.map(symbol => <button key={symbol} className={ticker === symbol ? 'active' : ''} onClick={() => onSelectTicker(symbol)}>{symbol}</button>)}</div>
      </div>
    </header>
    <div className="price-replay-context">
      <span className="price-replay-source">研究模拟成交</span>
      <span>{data?.source_label || '已保存的研究回放'}</span>
      {data && <span>组合期初资金 {money(data.starting_equity)} · 单边摩擦假设 {data.cost_bps} bps</span>}
    </div>
    <div className="price-replay-toolbar">
      <div className="price-replay-buttons">
        <button disabled={!data || loading} className={playing ? 'active' : ''} onClick={() => { if (!data) return; if (count >= data.bars.length) setCount(1); setPlaying(!playing); }}>{playing ? '⏸ 暂停' : '▶ 播放仿真'}</button>
        <button disabled={!data || loading} onClick={() => { setPlaying(false); setCount(1); setRange([0, 390]); setHover(null); }}>⟲ 重置</button>
        {[1, 2, 5, 10].map(value => <button key={value} aria-label={`${value}倍播放速度`} className={speed === value ? 'active' : ''} onClick={() => setSpeed(value)}>{value}x</button>)}
      </div>
      <div className="price-replay-buttons">
        {([{ label: '全天', range: [0, 390] }, { label: '早盘', range: [0, 150] }, { label: '午盘', range: [150, 270] }, { label: '尾盘', range: [270, 390] }] as Array<{ label: string; range: [number, number] }>).map(item => <button key={item.label} className={range[0] === item.range[0] && range[1] === item.range[1] ? 'active' : ''} onClick={() => setRange(item.range)}>{item.label}</button>)}
        <button aria-label="放大价格图" onClick={() => zoom(.65)}>＋ 放大</button>
        <button aria-label="缩小价格图" onClick={() => zoom(1.5)}>－ 缩小</button>
      </div>
    </div>
    {loading ? <div className="price-replay-message" role="status">正在读取 {ticker} 的价格与买卖点…</div> : error ? <div className="price-replay-message error" role="status">{error}</div> : data && <>
      <div className="price-replay-readout">
        <span>美东时间 <b>{activeBar ? marketTime.format(new Date(activeBar.time)).slice(0, 5) : '—'}</b></span>
        <span>价格 <b>{money(activeBar?.close)}</b></span><span>均价代理 <b>{money(activeBar?.vwap)}</b></span>
        <span>该棒成交量 <b>{activeBar?.volume.toLocaleString() ?? '—'}</b></span>
        <span>回放持仓 <b>{lastShares} 股</b></span>
        <span>回放净盈亏 <b style={{ color: (latestMark?.pnl ?? 0) >= 0 ? '#34d399' : '#fb7185' }}>{money(latestMark?.pnl)}</b></span>
      </div>
      <div className="price-replay-legend"><span style={{ color: '#38bdf8' }}>━ Price 价格线</span><span style={{ color: '#e9ad54' }}>━ OHLCV 均价代理</span>{Object.entries(actions).map(([key, value]) => <span key={key} style={{ color: value.color }}>{key} · {value.label}</span>)}<span>标记数字＝股数</span></div>
      <div className="price-replay-canvas">
        <svg viewBox={`0 0 ${width} 744`} role="img" aria-label={`${ticker}价格线、成交量、持仓和模拟盈亏`} onMouseMove={handleHover} onMouseLeave={() => setHover(null)}>
          <defs>{panels.map((panel, i) => <clipPath id={`${clip}-${i}`} key={i}><rect x={left} y={panel.top - 8} width={plotWidth} height={panel.height + 16} /></clipPath>)}</defs>
          {panels.map((panel, index) => <g key={panel.label}>
            <rect x={left} y={panel.top} width={plotWidth} height={panel.height} fill={index % 2 ? '#0d1520' : '#0b121c'} stroke="#263244" />
            <text x={left} y={panel.top - 10} fill="#94a3b8" fontSize="11">{panel.label}</text>
            {[0, .5, 1].map(fraction => { const value = domains[index][0] + fraction * (domains[index][1] - domains[index][0]); const py = y(value, index); return <g key={fraction}><line x1={left} x2={width - right} y1={py} y2={py} stroke="#202b3b" /><text x={left - 9} y={py + 4} textAnchor="end" fill="#94a3b8" fontSize="11">{index === 1 ? `${(value / 1000).toFixed(0)}k` : index === 2 ? value.toFixed(0) : value.toFixed(2)}</text></g>; })}
            {ticks.map(tick => <line key={tick} x1={x(tick)} x2={x(tick)} y1={panel.top} y2={panel.top + panel.height} stroke="#1b2635" />)}
          </g>)}
          <g clipPath={`url(#${clip}-0)`}>
            <path data-testid="replay-price-line" d={path(visible.bars.map(bar => [minute(bar.time), bar.close]), 0)} fill="none" stroke="#38bdf8" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            <path d={path(visible.bars.map(bar => [minute(bar.time), bar.vwap]), 0)} fill="none" stroke="#e9ad54" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
            {visible.fills.map((fill, index) => {
              const px = x(minute(fill.time)), py = y(fill.price, 0), up = fill.action === 'B' || fill.action === 'C';
              const size = Math.min(8, 4 + Math.sqrt(fill.shares) / 2), color = actions[fill.action].color;
              const sameTime = visible.fills.slice(0, index).filter(other => other.time === fill.time).length;
              return <g key={`${fill.time}-${index}`} data-testid="replay-fill" tabIndex={0} role="img" aria-label={`${marketTime.format(new Date(fill.time))} ${actions[fill.action].label} ${fill.shares}股 ${money(fill.price)}`}>
                <title>{`${marketTime.format(new Date(fill.time))} · ${actions[fill.action].label} ${fill.shares}股 @ ${money(fill.price)} · 成交后 ${fill.shares_after}股`}</title>
                <path d={up ? `M${px},${py-size}L${px-size},${py+size}L${px+size},${py+size}Z` : `M${px},${py+size}L${px-size},${py-size}L${px+size},${py-size}Z`} fill={color} />
                <text x={px} y={py + (up ? -12 : 19) + (up ? -1 : 1) * sameTime * 11} textAnchor="middle" fontSize="10" fontWeight="700" fill={color}>{fill.action}{fill.shares}</text>
              </g>;
            })}
          </g>
          <g clipPath={`url(#${clip}-1)`}>{visible.bars.map(bar => { const barWidth = Math.min(30, plotWidth * 4 / (range[1] - range[0])); return <rect key={bar.time} x={x(minute(bar.time)) - barWidth / 2} y={y(bar.volume, 1)} width={barWidth} height={y(0, 1) - y(bar.volume, 1)} fill={bar.close >= bar.open ? '#29b991' : '#e25876'} />; })}</g>
          <g clipPath={`url(#${clip}-2)`}><line x1={left} x2={width - right} y1={y(0, 2)} y2={y(0, 2)} stroke="#536172" /><path d={path(sharePoints, 2, true)} fill="none" stroke="#b5a0ea" strokeWidth="1.8" /></g>
          <g clipPath={`url(#${clip}-3)`}><line x1={left} x2={width - right} y1={y(0, 3)} y2={y(0, 3)} stroke="#536172" /><path d={path(valuation.map(mark => [minute(mark.time), mark.pnl]), 3)} fill="none" stroke="#36bca9" strokeWidth="1.8" /></g>
          {hover !== null && activeBar && minute(activeBar.time) >= range[0] && minute(activeBar.time) <= range[1] && panels.map(panel => <line key={panel.top} x1={x(minute(activeBar.time))} x2={x(minute(activeBar.time))} y1={panel.top} y2={panel.top + panel.height} stroke="#8a9bb0" strokeDasharray="4 4" pointerEvents="none" />)}
          {ticks.map(tick => <text key={tick} x={x(tick)} y={733} textAnchor="middle" fill="#94a3b8" fontSize="12">{timeLabel(tick)}</text>)}
        </svg>
      </div>
      <div className="price-replay-seek"><span>{count} / {data.bars.length} 根</span><input aria-label="回放进度" type="range" min={1} max={data.bars.length} value={Math.max(1, count)} onChange={event => { setPlaying(false); setCount(Number(event.target.value)); setHover(null); }} /><span>{visible.fills.length} 笔成交</span></div>
      <div className="price-replay-footnote">价格使用已完成 K 线的收盘价；成交标在实际模拟成交时刻。净盈亏包含持仓估值和上述摩擦假设。</div>
    </>}
  </section>;
}
