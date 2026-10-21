import { useEffect, useId, useState } from 'react';
import { API_BASE } from '../config';
import './StockContextPanel.css';

type NullableNumber = number | null;
interface ContextSnapshot {
  schema_version: 'context-1.0';
  generated_at: string;
  analysis_cutoff: string;
  price_received_at: string | null;
  symbol: string;
  mode: string;
  prediction_status: string;
  summary: {
    last_price: NullableNumber; previous_close: NullableNumber; change_pct: NullableNumber;
    gap_pct: NullableNumber; open_to_cutoff_pct: NullableNumber; excess_vs_spy_pp: NullableNumber;
    excess_vs_sector_pp: NullableNumber; mean_true_range_14: NullableNumber;
    sma20: NullableNumber; sma50: NullableNumber; session_vwap: NullableNumber; session_volume: NullableNumber;
  };
  benchmarks: { symbol: string; change_pct: NullableNumber; return_5d_pct: NullableNumber; return_20d_pct: NullableNumber }[];
  intraday: { timestamp: string; symbol: string; price: number; return_pct: number; volume: number; session: 'premarket' | 'regular' }[];
  daily: { date: string; symbol: string; close: number; return_pct: number }[];
  levels: { id: string; label: string; price: number; known_at: string; basis: string; kind: string }[];
  news: {
    status: string; received_at: string | null; records_total: number; precutoff_publications: number;
    usable_at_cutoff: number;
    items: {
      id: string; source: string; published_at: string | null; received_at: string | null;
      timing: string; association: string; summary: string; url: string; evidence_type: string;
    }[];
  };
  community: {
    source: string; received_at: string | null; status: string; records: number; unique_posts: number;
    available_at_cutoff: number; window_start: string | null; window_end: string | null;
    bullish: number; bearish: number; mixed: number; unknown: number; classified: number;
    stance_balance: NullableNumber; method: string; limitations: string[];
  };
  sources: { id: string; label: string; status: string; records: number | null; received_at: string | null; detail: string }[];
  limitations: string[];
}

interface ChartSeries { symbol: string; color: string; points: { time: number; value: number }[] }
interface ReferenceLine { id: string; label: string; price: number }
const SERIES_COLORS: Record<string, string> = { SNDK: '#6ce3ce', SPY: '#bcb3ff', QQQ: '#75afff', SOXX: '#f0c173', MU: '#ef9acb' };
const EXTRA_COLORS = ['#a1d07c', '#e6a57e', '#c3d5e4'];
const DEFAULT_SERIES = ['SNDK', 'SPY', 'QQQ', 'SOXX', 'MU'];

function finite(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value); }
function count(value: unknown) { return finite(value) && value >= 0 ? value.toLocaleString('en-US') : 'Unavailable'; }
function money(value: unknown) { return finite(value) ? value.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }) : 'Unavailable'; }
function change(value: unknown, unit = '%') { return finite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}${unit === '%' ? '%' : ' pp'}` : 'Unavailable'; }
function direction(value: unknown) { return finite(value) ? value > 0 ? 'scp-positive' : value < 0 ? 'scp-negative' : '' : ''; }
function words(value: string) { return value.replaceAll('_', ' '); }
function time(value: string | null | undefined, short = false) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Unavailable';
  return new Date(value).toLocaleString('en-US', {
    timeZone: 'America/New_York', ...(short ? {} : { month: 'short', day: 'numeric' }),
    hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  });
}
function axisTime(value: number, daily: boolean) {
  return new Date(value).toLocaleString('en-US', { timeZone: 'America/New_York',
    ...(daily ? { month: 'short', day: 'numeric' } as const : { hour: 'numeric', minute: '2-digit' } as const) });
}
function safeUrl(value: string) {
  try { const url = new URL(value); return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null; }
  catch { return null; }
}

function TimeSeriesChart({ series, title, description, daily = false, dollars = false, references = [] }: {
  series: ChartSeries[]; title: string; description: string; daily?: boolean; dollars?: boolean; references?: ReferenceLine[];
}) {
  const chartId = useId();
  const [cursorTime, setCursorTime] = useState<number | null>(null);
  const points = series.flatMap(item => item.points);
  const timestamps = [...new Set(points.map(point => point.time))].sort((a, b) => a - b);
  if (!timestamps.length) return <div className="scp-chart-empty" role="status">Unavailable · No price observations for this selection.</div>;
  const cursorIndex = cursorTime === null ? timestamps.length - 1 : timestamps.reduce((best, stamp, index) =>
    Math.abs(stamp - cursorTime) < Math.abs(timestamps[best] - cursorTime) ? index : best, 0);
  const cursor = timestamps[cursorIndex];
  const width = 820, height = 290, left = dollars ? 76 : 55, right = 24, top = 22, bottom = 39;
  const values = [...points.map(point => point.value), ...references.map(level => level.price), ...(dollars ? [] : [0])];
  const low = Math.min(...values), high = Math.max(...values);
  const padding = Math.max((high - low) * .12, dollars ? .5 : .15);
  const min = low - padding, max = high + padding;
  const first = timestamps[0], last = timestamps[timestamps.length - 1];
  const x = (stamp: number) => left + (stamp - first) / Math.max(1, last - first) * (width - left - right);
  const y = (value: number) => top + (max - value) / (max - min) * (height - top - bottom);
  const xTicks = [...new Set([0, .25, .5, .75, 1].map(fraction => timestamps[Math.round((timestamps.length - 1) * fraction)]))];
  const yTicks = Array.from({ length: 5 }, (_, index) => min + (max - min) * index / 4);
  const format = (value: unknown) => dollars ? money(value) : change(value);
  const pointPath = (item: ChartSeries) => {
    const intervals = item.points.slice(1).map((point, index) => point.time - item.points[index].time).sort((a, b) => a - b);
    const usualInterval = intervals[Math.floor(intervals.length / 2)] ?? Infinity;
    return item.points.map((point, index) => `${index === 0 || (!daily && point.time - item.points[index - 1].time > usualInterval * 1.8) ? 'M' : 'L'}${x(point.time).toFixed(2)},${y(point.value).toFixed(2)}`).join(' ');
  };
  return <figure className="scp-chart">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby={`${chartId}-title ${chartId}-desc`}
      onPointerMove={event => {
        const bounds = event.currentTarget.getBoundingClientRect();
        const fraction = ((event.clientX - bounds.left) / bounds.width * width - left) / (width - left - right);
        setCursorTime(first + Math.max(0, Math.min(1, fraction)) * (last - first));
      }}>
      <title id={`${chartId}-title`}>{title}</title><desc id={`${chartId}-desc`}>{description} Use the time slider or expandable data table to inspect observations.</desc>
      {yTicks.map(value => <g key={value}><line className="scp-grid-line" x1={left} x2={width - right} y1={y(value)} y2={y(value)} /><text className="scp-axis-label" x={left - 10} y={y(value) + 4} textAnchor="end">{dollars ? Math.round(value).toLocaleString('en-US') : `${value.toFixed(1)}%`}</text></g>)}
      {!dollars && <line className="scp-zero-line" x1={left} x2={width - right} y1={y(0)} y2={y(0)} />}
      {references.map(level => <line className="scp-reference-line" key={level.id} x1={left} x2={width - right} y1={y(level.price)} y2={y(level.price)}><title>{level.label}: {money(level.price)}</title></line>)}
      {xTicks.map(stamp => <text key={stamp} className="scp-axis-label" x={x(stamp)} y={height - 12} textAnchor={stamp === first ? 'start' : stamp === last ? 'end' : 'middle'}>{axisTime(stamp, daily)}</text>)}
      {series.map(item => <g key={item.symbol}><path d={pointPath(item)} fill="none" stroke={item.color} strokeWidth={item.symbol === 'SNDK' ? 2.7 : 1.8} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />{item.points.length === 1 && <circle cx={x(item.points[0].time)} cy={y(item.points[0].value)} r="3.5" fill={item.color} />}</g>)}
      <line className="scp-cursor-line" x1={x(cursor)} x2={x(cursor)} y1={top} y2={height - bottom} />
      {series.map(item => { const point = item.points.find(p => p.time === cursor); return point ? <circle key={item.symbol} cx={x(cursor)} cy={y(point.value)} r="4" fill={item.color} stroke="#0e1924" strokeWidth="2" /> : null; })}
    </svg>
    <div className="scp-chart-readout"><strong>{daily ? axisTime(cursor, true) : time(new Date(cursor).toISOString(), true)}</strong>{series.map(item => <span key={item.symbol}><i style={{ background: item.color }} aria-hidden="true" />{item.symbol} <b>{format(item.points.find(point => point.time === cursor)?.value)}</b></span>)}</div>
    <label className="scp-slider-label" htmlFor={`${chartId}-slider`}>Inspect observation <span>{cursorIndex + 1} / {timestamps.length}</span></label>
    <input className="scp-time-slider" id={`${chartId}-slider`} type="range" min={0} max={Math.max(0, timestamps.length - 1)} value={cursorIndex} disabled={timestamps.length === 1}
      aria-valuetext={`${axisTime(cursor, daily)}${daily ? '' : ' Eastern time'}; ${series.map(item => `${item.symbol} ${format(item.points.find(point => point.time === cursor)?.value)}`).join('; ')}`}
      onChange={event => setCursorTime(timestamps[Number(event.target.value)])} />
    <figcaption>{description}</figcaption>
    <details className="scp-data-table"><summary>View chart data</summary><div className="scp-table-scroll"><table><caption>{title} · {daily ? 'Daily observations' : 'Bar-ending times in New York'}</caption><thead><tr><th scope="col">{daily ? 'Date' : 'Time (ET)'}</th>{series.map(item => <th scope="col" key={item.symbol}>{item.symbol}</th>)}</tr></thead><tbody>{timestamps.map(stamp => <tr key={stamp}><th scope="row">{axisTime(stamp, daily)}</th>{series.map(item => <td key={item.symbol}>{format(item.points.find(point => point.time === stamp)?.value)}</td>)}</tr>)}</tbody></table></div></details>
  </figure>;
}

function ContextContent({ data }: { data: ContextSnapshot }) {
  const [period, setPeriod] = useState<'intraday' | 'daily'>('intraday');
  const [regularOnly, setRegularOnly] = useState(false);
  const [selected, setSelected] = useState(DEFAULT_SERIES);
  const [showLevels, setShowLevels] = useState(true);
  const [rankingPeriod, setRankingPeriod] = useState<'change_pct' | 'return_5d_pct' | 'return_20d_pct'>('change_pct');
  const [newsFilter, setNewsFilter] = useState('all');
  const [showAllNews, setShowAllNews] = useState(false);
  const availableSymbols = [...new Set([...data.intraday, ...data.daily].map(row => row.symbol))].sort((a, b) => {
    const rank = (symbol: string) => DEFAULT_SERIES.includes(symbol) ? DEFAULT_SERIES.indexOf(symbol) : 99;
    return rank(a) - rank(b) || a.localeCompare(b);
  });
  const color = (symbol: string) => SERIES_COLORS[symbol] ?? EXTRA_COLORS[Math.max(0, availableSymbols.indexOf(symbol)) % EXTRA_COLORS.length];
  const intraday = data.intraday.filter(row => !regularOnly || row.session === 'regular');
  const chartSeries: ChartSeries[] = availableSymbols.filter(symbol => selected.includes(symbol)).map(symbol => ({ symbol, color: color(symbol),
    points: (period === 'intraday'
      ? intraday.filter(row => row.symbol === symbol).map(row => ({ time: Date.parse(row.timestamp), value: row.return_pct }))
      : data.daily.filter(row => row.symbol === symbol).map(row => ({ time: Date.parse(`${row.date}T12:00:00Z`), value: row.return_pct })))
      .filter(point => finite(point.time) && finite(point.value)).sort((a, b) => a.time - b.time),
  }));
  const priceSeries: ChartSeries[] = [{ symbol: data.symbol, color: color(data.symbol), points: intraday.filter(row => row.symbol === data.symbol && finite(row.price))
    .map(row => ({ time: Date.parse(row.timestamp), value: row.price })).filter(point => finite(point.time)).sort((a, b) => a.time - b.time) }];
  const levels = data.levels.filter(level => finite(level.price));
  const ranked = [...data.benchmarks].sort((a, b) => (finite(b[rankingPeriod]) ? b[rankingPeriod] : -Infinity) - (finite(a[rankingPeriod]) ? a[rankingPeriod] : -Infinity));
  const rankMax = Math.max(...ranked.map(row => finite(row[rankingPeriod]) ? Math.abs(row[rankingPeriod]) : 0), .01);
  const news = data.news.items.filter(item => newsFilter === 'all' || (newsFilter === 'official' ? item.evidence_type === 'company_statement' : item.association === newsFilter))
    .sort((a, b) => (Date.parse(b.published_at ?? '') || 0) - (Date.parse(a.published_at ?? '') || 0));
  const visibleNews = showAllNews ? news : news.slice(0, 6);
  const community = data.community;
  const ruleCoverage = finite(community.classified) && finite(community.unique_posts) && community.unique_posts > 0 ? community.classified / community.unique_posts * 100 : null;
  const unknownShare = finite(community.unknown) && finite(community.unique_posts) && community.unique_posts > 0 ? community.unknown / community.unique_posts * 100 : null;
  const stances = [{ label: 'Bullish', value: community.bullish, color: '#6ce3ce' }, { label: 'Bearish', value: community.bearish, color: '#ee8f9c' }, { label: 'Mixed', value: community.mixed, color: '#e7bf79' }, { label: 'Unknown', value: community.unknown, color: '#95a4b8' }];
  const stanceMax = Math.max(...stances.map(item => finite(item.value) ? item.value : 0), 1);
  const summary = data.summary;

  return <>
    <div className="scp-overview">
      <div className="scp-price-hero"><div className="scp-symbol-line"><span className="scp-symbol">{data.symbol}</span><span className="scp-badge">Historical snapshot</span></div><strong className="scp-last-price">{money(summary.last_price)}</strong><div className={`scp-price-change ${direction(summary.change_pct)}`}>{change(summary.change_pct)} <span>vs previous close</span></div><p>Through {time(data.analysis_cutoff)} · Not a live quote</p></div>
      <div className="scp-metric-grid">
        <div><span>Opening gap</span><strong className={direction(summary.gap_pct)}>{change(summary.gap_pct)}</strong><small>Open vs previous close</small></div>
        <div><span>After the open</span><strong className={direction(summary.open_to_cutoff_pct)}>{change(summary.open_to_cutoff_pct)}</strong><small>Open to cutoff</small></div>
        <div><span>Relative to SPY</span><strong className={direction(summary.excess_vs_spy_pp)}>{change(summary.excess_vs_spy_pp, 'pp')}</strong><small>Difference in percentage points</small></div>
        <div><span>Relative to SOXX</span><strong className={direction(summary.excess_vs_sector_pp)}>{change(summary.excess_vs_sector_pp, 'pp')}</strong><small>Sector comparison</small></div>
      </div>
    </div>
    <div className="scp-timestamps"><span><b>Price cutoff</b>{time(data.analysis_cutoff)}</span><span><b>Prices received</b>{time(data.price_received_at)}</span><span><b>News received</b>{time(data.news.received_at)}</span><span><b>Snapshot generated</b>{time(data.generated_at)}</span></div>

    <section className="scp-surface" aria-labelledby="scp-performance-heading">
      <div className="scp-section-heading"><div><p className="scp-kicker">01 / PRICE CONTEXT</p><h3 id="scp-performance-heading">Price performance vs benchmarks</h3></div><div className="scp-segmented" aria-label="Chart period"><button aria-pressed={period === 'intraday'} onClick={() => setPeriod('intraday')}>Intraday</button><button aria-pressed={period === 'daily'} onClick={() => setPeriod('daily')}>Daily history</button></div></div>
      <p className="scp-help">{period === 'intraday' ? 'Every series is measured from its own previous session close. Compare the stock, broad market, and memory peers on the same percentage scale.' : 'Every series is measured from its close on the archive’s first common trading day. This view does not use today’s reference levels.'}</p>
      <div className="scp-chart-controls"><div className="scp-series-toggles" aria-label="Visible chart series">{availableSymbols.map(symbol => <button key={symbol} aria-pressed={selected.includes(symbol)} onClick={() => setSelected(current => current.includes(symbol) ? current.filter(item => item !== symbol) : [...current, symbol])}><i style={{ background: color(symbol) }} aria-hidden="true" />{symbol}</button>)}</div><label className="scp-checkbox"><input type="checkbox" checked={regularOnly} onChange={event => setRegularOnly(event.target.checked)} />Regular session only</label></div>
      <TimeSeriesChart key={period} series={chartSeries} title={`${data.symbol} and benchmarks · ${period} returns`} daily={period === 'daily'} description={period === 'intraday' ? 'Previous close = 0%. Intraday timestamps mark bar ends; missing observations stay unavailable. Session filtering also applies to the price chart below.' : 'First common archive close = 0%. Daily closes show realized history, not expected returns. Session filtering applies only to intraday charts.'} />
    </section>

    <div className="scp-two-column">
      <section className="scp-surface" aria-labelledby="scp-levels-heading"><div className="scp-section-heading"><div><p className="scp-kicker">02 / REFERENCE LEVELS</p><h3 id="scp-levels-heading">{data.symbol} price map</h3></div><label className="scp-checkbox"><input type="checkbox" checked={showLevels} onChange={event => setShowLevels(event.target.checked)} />Prior levels</label></div><p className="scp-help">Reference levels reconstructed from prior-session prices. Crossing a line does not establish support, resistance, or a trade signal.</p>
        <TimeSeriesChart series={priceSeries} dollars references={showLevels ? levels : []} title={`${data.symbol} intraday price and prior reference levels`} description="USD price. Dashed lines are reconstructed from prior prices, not preregistered forecasts or proof of prior system receipt. They appear only on this session’s chart." />
        <div className="scp-level-list">{levels.length ? levels.map(level => <div key={level.id}><div><span>{level.label}</span><strong>{money(level.price)}</strong></div><p>{level.basis}</p><small>Based on prices through {time(level.known_at)}</small></div>) : <p className="scp-help">Reference levels unavailable.</p>}</div>
        <div className="scp-context-facts"><div><span>Session VWAP</span><b>{money(summary.session_vwap)}</b></div><div><span>Session volume</span><b>{count(summary.session_volume)}</b></div><div><span>14-session mean true range</span><b>{money(summary.mean_true_range_14)}</b></div></div><p className="scp-microcopy">VWAP and session volume are observed through the cutoff. True range is historical price variability, not a confidence interval.</p>
      </section>

      <section className="scp-surface" aria-labelledby="scp-ranking-heading"><div className="scp-section-heading"><div><p className="scp-kicker">03 / RELATIVE STRENGTH</p><h3 id="scp-ranking-heading">Relative strength</h3></div><label className="scp-select-label">Window<select value={rankingPeriod} onChange={event => setRankingPeriod(event.target.value as typeof rankingPeriod)}><option value="change_pct">Session</option><option value="return_5d_pct">5 sessions</option><option value="return_20d_pct">20 sessions</option></select></label></div><p className="scp-help">Observed percentage returns, sorted strongest first. Different assets have different risks; this is not a beta-adjusted comparison.</p>
        <div className="scp-ranking" role="list" aria-label="Observed return ranking">{ranked.length ? ranked.map(row => { const value = row[rankingPeriod]; const known = finite(value); const width = known ? Math.abs(value) / rankMax * 48 : 0; return <div role="listitem" key={row.symbol} className={`scp-rank-row ${row.symbol === data.symbol ? 'scp-rank-focus' : ''}`}><strong>{row.symbol}</strong><div className="scp-rank-track" aria-hidden="true"><span className="scp-rank-zero" />{known && <span className={`scp-rank-bar ${value < 0 ? 'scp-rank-negative' : 'scp-rank-positive'}`} style={{ width: `${width}%`, left: `${value < 0 ? 50 - width : 50}%` }} />}</div><b className={direction(value)}>{change(value)}</b></div>; }) : <p className="scp-help">Comparison data unavailable.</p>}</div>
        <div className="scp-reading-note"><span>Read the difference</span><p>A stock can weaken more than its sector while the broad market stays stable. Price differences alone do not isolate a news effect.</p></div>
      </section>
    </div>

    <div className="scp-two-column scp-evidence-columns">
      <section className="scp-surface" aria-labelledby="scp-news-heading"><div className="scp-section-heading"><div><p className="scp-kicker">04 / WHAT WAS REPORTED</p><h3 id="scp-news-heading">Evidence timeline</h3></div><span className="scp-small-tag">{words(data.news.status)}</span></div><p className="scp-help">Publication and system receipt are separate. A retrospective archive does not establish what this system knew before the cutoff.</p>
        <div className="scp-mini-stats"><div><b>{count(data.news.records_total)}</b><span>Archive records</span></div><div><b>{count(data.news.precutoff_publications)}</b><span>Published before cutoff</span></div><div><b>{count(data.news.usable_at_cutoff)}</b><span>Usable at cutoff</span></div></div>
        <div className="scp-filter-row" aria-label="Evidence filter">{[{ id: 'all', label: 'All evidence' }, { id: 'direct', label: 'Company' }, { id: 'sector', label: 'Sector' }, { id: 'macro', label: 'Macro' }, { id: 'official', label: 'Company statements' }].map(filter => <button key={filter.id} aria-pressed={newsFilter === filter.id} onClick={() => { setNewsFilter(filter.id); setShowAllNews(false); }}>{filter.label}</button>)}</div>
        <ol className="scp-timeline">{visibleNews.map(item => { const url = safeUrl(item.url); return <li key={item.id}><div className="scp-event-top"><span>{item.source}</span><time dateTime={item.published_at ?? undefined}>{time(item.published_at)}</time></div><div className="scp-event-tags"><span>{words(item.association)}</span><span>{words(item.evidence_type)}</span><span className={item.timing === 'available_at_cutoff' ? 'scp-timing-available' : 'scp-timing-late'}>{item.timing === 'received_after_cutoff' ? 'Received after cutoff' : item.timing === 'available_at_cutoff' ? 'Available at cutoff' : item.timing === 'publication_time_unknown' ? 'Publication time unknown' : words(item.timing)}</span></div><p>{item.summary}</p><div className="scp-event-bottom"><span>Received {time(item.received_at)}</span>{url ? <a href={url} target="_blank" rel="noopener noreferrer">Open source ↗</a> : <span>Source link unavailable</span>}</div></li>; })}</ol>
        {!visibleNews.length && <p className="scp-help">No evidence is available for this filter.</p>}
        {news.length > 6 && <button className="scp-text-button" onClick={() => setShowAllNews(value => !value)}>{showAllNews ? 'Show fewer events' : `Show all ${count(news.length)} events`}</button>}
        <p className="scp-microcopy">Short review summaries are shown here. Source statements, opinions, and unverified claims retain their evidence labels.</p>
      </section>

      <section className="scp-surface" aria-labelledby="scp-community-heading"><div className="scp-section-heading"><div><p className="scp-kicker">05 / COMMUNITY SAMPLE</p><h3 id="scp-community-heading">Futu post stance</h3></div><span className="scp-small-tag">{words(community.status)}</span></div>
        <p className="scp-help">Rule-assigned stance in the returned posts. Counts describe this sample, not the proportion of all investors or the probability of a price rise.</p>
        <div className="scp-community-cutoff"><strong>{count(community.available_at_cutoff)} posts available at cutoff</strong><span>Received {time(community.received_at)}</span><p>{community.available_at_cutoff === 0 ? 'This sample cannot be backfilled into the cutoff’s information set.' : 'Use only the eligible subset for a cutoff-based analysis. The bars below describe all sampled posts.'}</p></div>
        <div className="scp-stance-bars" aria-label="Sampled post stance counts">{stances.map(item => <div className="scp-stance-row" key={item.label}><span>{item.label}</span><div className="scp-stance-track" aria-hidden="true"><i style={{ width: finite(item.value) ? `${item.value / stanceMax * 100}%` : '0%', background: item.color }} /></div><strong>{count(item.value)}</strong></div>)}</div>
        <div className="scp-community-stats"><div><span>Sampled posts</span><b>{count(community.records)}</b></div><div><span>Unique post IDs</span><b>{count(community.unique_posts)}</b></div><div><span>Directional balance (-100 to +100)</span><b>{finite(community.stance_balance) ? community.stance_balance.toFixed(2) : 'Unavailable'}</b></div><div><span>Rule coverage</span><b>{finite(ruleCoverage) ? `${ruleCoverage.toFixed(1)}%` : 'Unavailable'}</b></div></div>
        <p className="scp-microcopy">Directional balance compares bullish and bearish labels; it is not an upward-return probability. Rule coverage is classified posts divided by unique post IDs. {finite(unknownShare) ? `${unknownShare.toFixed(1)}% of unique posts have an unknown stance. ` : ''}Unknown does not mean neutral.</p>
        <dl className="scp-community-method"><div><dt>Post window</dt><dd>{time(community.window_start)} — {time(community.window_end)}</dd></div><div><dt>Method</dt><dd>{community.method || 'Unavailable'}</dd></div></dl>
        <details className="scp-inline-details"><summary>Sample limitations</summary>{community.limitations.length ? <ul>{community.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="scp-help">Sampling coverage and stance accuracy have not been established.</p>}</details>
      </section>
    </div>

    <details className="scp-sources"><summary><span>Data sources &amp; coverage</span><small>{count(data.sources.length)} sources · Saved status and receipt times</small></summary><div className="scp-source-grid">{data.sources.map(source => <article key={source.id}><div><h3>{source.label}</h3><span>{words(source.status)}</span></div><p>{source.detail}</p><footer><span>{count(source.records)} records</span><span>Received {time(source.received_at)}</span></footer></article>)}</div>{data.limitations.length > 0 && <div className="scp-global-limits"><h3>Interpretation limits</h3><ul>{data.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}</details>
  </>;
}

export function StockContextPanel({ revision }: { revision: number }) {
  const [data, setData] = useState<ContextSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true); setError(null); setData(null);
      try {
        const response = await fetch(`${API_BASE}/api/research/financial-sentiment/context`, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12_000)]), headers: { Accept: 'application/json' },
        });
        if (response.status === 404) throw new Error('No saved stock-context snapshot is available yet.');
        if (!response.ok) throw new Error(`The saved context is unavailable (HTTP ${response.status}).`);
        if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('The context service returned an unexpected response.');
        const result = await response.json() as ContextSnapshot;
        if (result?.schema_version !== 'context-1.0' || typeof result.symbol !== 'string' || !result.summary || !result.news || !result.community
          || ![result.intraday, result.daily, result.levels, result.benchmarks, result.sources, result.limitations, result.news.items, result.community.limitations].every(Array.isArray)) throw new Error('The saved context has an unexpected format.');
        if (!controller.signal.aborted) setData(result);
      } catch (reason: unknown) {
        if (!controller.signal.aborted) setError(reason instanceof Error && reason.name === 'TimeoutError' ? 'The snapshot took too long to respond. Try reloading the saved file.' : reason instanceof Error ? reason.message : 'The saved context is unavailable.');
      } finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void load();
    return () => controller.abort();
  }, [revision, retry]);

  return <section className="stock-context-panel" aria-labelledby="scp-title"><header className="scp-header"><div><p className="scp-kicker">MARKET CONTEXT / SAVED RESEARCH</p><h2 id="scp-title">Stock context explorer</h2><p>{data?.mode ?? 'Retrospective research snapshot'}. Explore prices, public evidence, and community coverage together.</p></div><div className="scp-header-meta"><span className="scp-badge">Not a forecast</span><span>Price model: {data?.prediction_status ?? 'Unavailable'}</span></div></header><p className="scp-independent">Research company: {data?.symbol ?? 'SNDK'} · Independent of your watchlist and trading settings. Reloading only reads a saved snapshot.</p>
    {loading ? <div className="scp-loading" role="status"><span aria-hidden="true" /><strong>Loading saved market context…</strong><p>Reading the archived snapshot.</p></div> : error || !data ? <div className="scp-error" role="alert"><strong>Stock context unavailable</strong><p>{error ?? 'No valid snapshot is available.'}</p><button onClick={() => setRetry(value => value + 1)}>Retry saved snapshot</button></div> : <ContextContent key={`${data.generated_at}-${data.symbol}`} data={data} />}
  </section>;
}
