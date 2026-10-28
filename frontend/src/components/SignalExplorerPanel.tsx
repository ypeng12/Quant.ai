import { useEffect, useState } from 'react';
import { API_BASE } from '../config';
import './SignalExplorerPanel.css';

type ModelId = 'A' | 'B' | 'C';
interface ModelPoint {
  forecast_bps: number | null; nominal_horizon_minutes: number;
  effective_horizon_minutes: number | null; shares: number; weight: number;
  realized_bps: number | null; realized_end_at: string | null;
}
interface Contribution { feature: string; value: number; standardized: number; coefficient_bps: number; contribution_bps: number }
interface TextPoint {
  has_text: boolean; primary_asof_eligible: boolean;
  full_adjustment_bps: number; effective_adjustment_bps: number;
  raw_adjustment_bps: number | null; rounding_adjustment_bps?: number | null; intercept_bps: number | null; clip_adjustment_bps: number | null;
  fallback_reason: string | null; feature_values: Record<string, number>;
  contributions: Contribution[] | null; evidence_keys: string[];
}
interface SignalPoint {
  timestamp: string; bar_start: string; has_decision: boolean;
  price: { open: number; high: number; low: number; close: number; volume: number };
  A: ModelPoint; B: ModelPoint; C: ModelPoint; text: TextPoint | null;
}
interface Fill { model: ModelId; timestamp: string; side: string; quantity: number; fill_price: number; reason: string }
interface SignalSeries {
  symbol: string; date: string; C_scale: number;
  text_calibration: { status: string; reason: string | null; training_text_rows: number; training_sessions: number; training_cutoff: string };
  points: SignalPoint[]; fills: Fill[];
}
interface Evidence {
  source: string; source_id: string; title: string; published_at: string | null;
  updated_at: string | null; received_at: string | null; available_at: string | null; receipt_verified: boolean;
}
interface SignalReport {
  schema_version: 1; generated_at: string; evaluation_kind: 'retrospective_development';
  cost_bps_per_side: number; symbols: string[]; dates: string[];
  default_selection: { symbol: string; date: string };
  tracks: { id: string; label: string; status: string; as_of: string; detail: string }[];
  feature_definitions: { id: string; label: string; unit: string; detail: string }[];
  summary: { series_count: number; decision_count: number; changed_prediction_count: number; distinct_receipt_dates: string[] };
  evidence: Record<string, Evidence>; series: SignalSeries[]; limitations: string[];
}
interface PlotLine { label: string; color: string; values: (number | null)[]; dashed?: boolean }

const colors = { A: '#60a5fa', B: '#2dd4bf', C: '#c4b5fd' };
const time = (value: string | null) => value && Number.isFinite(Date.parse(value))
  ? new Date(value).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false }) : 'Unavailable';
const instant = (value: string | null) => value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value} (date only)` : value && Number.isFinite(Date.parse(value))
  ? new Date(value).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }) : 'Unavailable';
const numeric = (value: number | null, digits = 2) => value === null || !Number.isFinite(value) ? 'Unavailable' : value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const bps = (value: number | null) => value === null || !Number.isFinite(value) ? 'Unavailable' : `${value > 0 ? '+' : ''}${numeric(value, value !== 0 && Math.abs(value) < .01 ? 6 : 2)} bps`;
const readableState = (value: string) => ({
  fitted_development_only: 'Fitted for development research',
  unavailable: 'Unavailable',
  insufficient_eligible_training_coverage: 'There are too few eligible training rows or sessions to fit the text adjustment.',
  no_eligible_calibration: 'The text adjustment is unavailable. B uses the price-only forecast from C.',
  no_asof_text: 'No text was eligible at this decision time. B uses the price-only forecast from C.',
  scheduled_1555_liquidation: 'Scheduled 15:55 exit',
  policy_rebalance: 'Model position adjustment',
} as Record<string, string>)[value] ?? value.replaceAll('_', ' ');

function validReport(value: SignalReport): boolean {
  return value?.schema_version === 1 && value.evaluation_kind === 'retrospective_development'
    && Array.isArray(value.series) && value.series.length > 0 && value.series.every(series =>
      typeof series.symbol === 'string' && typeof series.date === 'string'
      && Array.isArray(series.points) && series.points.length > 0 && Array.isArray(series.fills)
      && !!series.text_calibration && series.points.every(point => point.A && point.B && point.C && Number.isFinite(point.price?.close)))
    && Array.isArray(value.symbols) && Array.isArray(value.dates) && !!value.default_selection
    && Array.isArray(value.tracks) && Array.isArray(value.feature_definitions) && !!value.evidence
    && !!value.summary && Array.isArray(value.summary.distinct_receipt_dates) && Array.isArray(value.limitations);
}

function TimePlot({ title, lines, points, selected, unit, zero = false, fills = [] }: {
  title: string; lines: PlotLine[]; points: SignalPoint[]; selected: number; unit: string; zero?: boolean; fills?: Fill[];
}) {
  const values = [...lines.flatMap(line => line.values.filter((value): value is number => value !== null && Number.isFinite(value))), ...fills.map(fill => fill.fill_price)];
  if (!values.length) return <div className="signal-explorer-plot"><h3>{title}</h3><p className="fsr-help">No available values for this session.</p></div>;
  const low = Math.min(...values, ...(zero ? [0] : []));
  const high = Math.max(...values, ...(zero ? [0] : []));
  const pad = Math.max((high - low) * .12, Math.abs(high) * .002, .01);
  const min = low - pad, max = high + pad;
  const left = 62, right = 754, top = 20, bottom = 176;
  const x = (i: number) => left + i / Math.max(1, points.length - 1) * (right - left);
  const y = (value: number) => bottom - (value - min) / (max - min) * (bottom - top);
  const paths = (values: (number | null)[]) => {
    const result: string[] = []; let current = '';
    values.forEach((value, index) => {
      if (value === null || !Number.isFinite(value)) { if (current) result.push(current); current = ''; }
      else current += `${current ? ' L' : 'M'}${x(index)},${y(value)}`;
    });
    if (current) result.push(current);
    return result;
  };
  const ticks = [min, (min + max) / 2, max];
  const positions = [0, Math.floor((points.length - 1) / 2), points.length - 1];
  return <div className="signal-explorer-plot"><div className="signal-explorer-plot-title"><h3>{title}</h3><span>{unit}</span></div>
    <div className="signal-explorer-svg"><svg viewBox="0 0 780 214" role="img" aria-label={`${title}, ${unit}; selected time ${time(points[selected].timestamp)} New York`}>
      {ticks.map(value => <g key={value}><line x1={left} x2={right} y1={y(value)} y2={y(value)} className="signal-explorer-grid" /><text x={left - 8} y={y(value) + 4} textAnchor="end" className="signal-explorer-axis">{numeric(value, 1)}</text></g>)}
      {zero && <line x1={left} x2={right} y1={y(0)} y2={y(0)} className="signal-explorer-zero" />}
      <line x1={x(selected)} x2={x(selected)} y1={top} y2={bottom} className="signal-explorer-cursor" />
      {lines.map(line => <g key={line.label}>{paths(line.values).map((path, index) => <path key={index} d={path} fill="none" stroke={line.color} strokeWidth="2.3" strokeDasharray={line.dashed ? '6 4' : undefined} />)}{line.values[selected] !== null && Number.isFinite(line.values[selected]) && <circle cx={x(selected)} cy={y(line.values[selected]!)} r="4" fill={line.color}><title>{line.label}: {numeric(line.values[selected])} {unit}</title></circle>}</g>)}
      {fills.map((fill, index) => {
        const i = points.reduce((best, point, candidate) => Math.abs(Date.parse(point.timestamp) - Date.parse(fill.timestamp)) < Math.abs(Date.parse(points[best].timestamp) - Date.parse(fill.timestamp)) ? candidate : best, 0);
        const buy = fill.side.toLowerCase() === 'buy'; const yy = y(fill.fill_price), xx = x(i);
        return <path key={`${fill.timestamp}-${index}`} d={buy ? `M${xx},${yy - 5} L${xx - 4.5},${yy + 4} L${xx + 4.5},${yy + 4} Z` : `M${xx},${yy + 5} L${xx - 4.5},${yy - 4} L${xx + 4.5},${yy - 4} Z`} fill={buy ? '#4ade80' : '#fb7185'} stroke="#0f172a" strokeWidth=".7"><title>{fill.model} {fill.side} {fill.quantity} shares at ${numeric(fill.fill_price)} · {time(fill.timestamp)} · {readableState(fill.reason)}</title></path>;
      })}
      {positions.map(i => <text key={i} x={x(i)} y="200" textAnchor={i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'} className="signal-explorer-axis">{time(points[i].timestamp)}</text>)}
    </svg></div><div className="signal-explorer-legend">{lines.map(line => <span key={line.label}><i style={{ backgroundColor: line.color }} />{line.label}</span>)}</div>
  </div>;
}

export function SignalExplorerPanel({ revision }: { revision: number }) {
  const [report, setReport] = useState<SignalReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [selection, setSelection] = useState<{ symbol: string; date: string } | null>(null);
  const [selectedBar, setSelectedBar] = useState<number | null>(null);
  const [positionModel, setPositionModel] = useState<ModelId>('B');
  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true); setReport(null); setError(null); setMissing(false); setSelection(null); setSelectedBar(null);
      try {
        const response = await fetch(`${API_BASE}/api/research/financial-sentiment/signals`, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(45_000)]), headers: { Accept: 'application/json' },
        });
        if (response.status === 404) { if (!controller.signal.aborted) setMissing(true); return; }
        if (!response.ok) throw new Error(`The saved signal explorer is unavailable (HTTP ${response.status}).`);
        if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Unexpected signal report response.');
        const value = await response.json() as SignalReport;
        if (!validReport(value)) throw new Error('The saved signal report has an unexpected format.');
        if (!controller.signal.aborted) setReport(value);
      } catch (reason: unknown) {
        if (!controller.signal.aborted) setError(reason instanceof Error && reason.name === 'TimeoutError' ? 'Signal loading timed out. Reload saved reports to try again.' : reason instanceof Error ? reason.message : 'The signal explorer is unavailable.');
      } finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void load(); return () => controller.abort();
  }, [revision]);
  const heading = <div className="fsr-section-heading"><h2 id="signal-explorer-title">Signal explorer</h2><span>Saved decisions · Inspect the inputs and outputs</span></div>;
  if (loading) return <section className="fsr-card signal-explorer" aria-labelledby="signal-explorer-title">{heading}<p className="fsr-help" role="status">Loading saved forecasts and simulated positions…</p></section>;
  if (missing) return <section className="fsr-card signal-explorer" aria-labelledby="signal-explorer-title">{heading}<div className="fsr-message"><strong>Signal trace not exported</strong><p>No saved signal artifact is available. This page does not create forecasts or place orders.</p></div></section>;
  if (error || !report) return <section className="fsr-card signal-explorer" aria-labelledby="signal-explorer-title">{heading}<div className="fsr-message fsr-error" role="alert"><strong>Signal explorer unavailable</strong><p>{error ?? 'No valid signal artifact is available.'}</p></div></section>;
  const chosen = selection ?? report.default_selection;
  const series = report.series.find(item => item.symbol === chosen.symbol && item.date === chosen.date) ?? report.series[0];
  const dates = report.series.filter(item => item.symbol === series.symbol).map(item => item.date);
  const firstRevision = series.points.findIndex(point => point.text && Math.abs(point.text.effective_adjustment_bps) > 0);
  const selected = Math.min(selectedBar ?? Math.max(firstRevision, 0), series.points.length - 1);
  const point = series.points[selected], text = point.text;
  const nextRevision = series.points.findIndex((item, i) => i > selected && item.text && Math.abs(item.text.effective_adjustment_bps) > 0);
  const fills = series.fills.filter(fill => fill.model === positionModel);
  const definitions = Object.fromEntries(report.feature_definitions.map(item => [item.id, item]));
  const contributions = text?.contributions ?? [];
  const contributionScale = Math.max(...contributions.map(item => Math.abs(item.contribution_bps)), .000001);
  const evidence = (text?.evidence_keys ?? []).map(key => report.evidence[key]).filter(Boolean);
  const selectSeries = (symbol: string, date: string) => { setSelection({ symbol, date }); setSelectedBar(null); };
  return <section className="fsr-card signal-explorer" aria-labelledby="signal-explorer-title">
    {heading}
    <p className="fsr-help">Trace one company and session from observed prices to forecasts, text adjustments, and simulated holdings. All timestamps below use New York time. This is development evidence, not a live recommendation.</p>
    <details className="signal-explorer-tracks"><summary>Model tracks and artifact status</summary><div className="signal-explorer-track-grid">{report.tracks.map(track => <article key={track.id}><h3>{track.label}</h3><strong>{readableState(track.status)}</strong><span>As of {track.as_of}</span><p>{track.detail}</p></article>)}</div></details>
    <div className="signal-explorer-controls">
      <label>Company<select aria-label="Company" value={series.symbol} onChange={event => { const symbol = event.target.value; const same = report.series.find(item => item.symbol === symbol && item.date === series.date); selectSeries(symbol, same?.date ?? report.series.find(item => item.symbol === symbol)!.date); }}>{report.symbols.map(symbol => <option key={symbol}>{symbol}</option>)}</select></label>
      <label>Session<select aria-label="Session" value={series.date} onChange={event => selectSeries(series.symbol, event.target.value)}>{dates.map(date => <option key={date}>{date}</option>)}</select></label>
      <label>Positions and fills<select aria-label="Positions and fills" value={positionModel} onChange={event => setPositionModel(event.target.value as ModelId)}><option value="A">A · Original price policy</option><option value="B">B · New candidate with text</option><option value="C">C · Price-only control</option></select></label>
    </div>
    <div className="signal-explorer-time"><div><label htmlFor="signal-explorer-time">Selected bar close <strong>{time(point.timestamp)} ET</strong></label><span>{point.has_decision ? 'Saved forecast decision' : 'No forecast decision at this bar'}</span></div><input id="signal-explorer-time" type="range" min="0" max={series.points.length - 1} value={selected} onChange={event => setSelectedBar(Number(event.target.value))} aria-valuetext={`${time(point.timestamp)} New York time`} /><button className="fsr-reload" disabled={nextRevision < 0} onClick={() => setSelectedBar(nextRevision)}>Next forecast revision</button></div>
    <div className="signal-explorer-current"><div><span>{series.symbol} bar close</span><strong>${numeric(point.price.close)}</strong></div><div><span>{positionModel} simulated holdings</span><strong>{numeric(point[positionModel].shares, 0)} shares</strong></div><div><span>{positionModel} signed equity weight</span><strong>{numeric(point[positionModel].weight * 100)}%</strong></div><div><span>Effective text adjustment</span><strong>{bps(text?.effective_adjustment_bps ?? null)}</strong></div></div>
    <TimePlot title={`${series.symbol} price and ${positionModel} fills`} unit="USD" points={series.points} selected={selected} lines={[{ label: 'Completed-bar close', color: '#e2e8f0', values: series.points.map(item => item.price.close) }]} fills={fills} />
    <p className="signal-explorer-helper"><span className="signal-explorer-buy">▲ Buy</span> <span className="signal-explorer-sell">▼ Sell</span> · {fills.length} simulated fills for {positionModel}. A buy can open a long or cover a short; a sell can reduce a long or open a short.</p>
    <TimePlot title={`${positionModel} observed simulated holdings`} unit="shares" zero points={series.points} selected={selected} lines={[{ label: 'Bar-close inventory after simulated fills', color: colors[positionModel], values: series.points.map(item => item[positionModel].shares) }]} />
    <div className="signal-explorer-forecast-grid">
      <TimePlot title="A · Five-minute return forecast" unit="bps" zero points={series.points} selected={selected} lines={[{ label: 'A · Original policy', color: colors.A, values: series.points.map(item => item.A.forecast_bps) }]} />
      <TimePlot title="C and B · Thirty-minute return forecast" unit="bps" zero points={series.points} selected={selected} lines={[{ label: 'C · Price only', color: colors.C, dashed: true, values: series.points.map(item => item.C.forecast_bps) }, { label: 'B · Price plus text adapter', color: colors.B, values: series.points.map(item => item.B.forecast_bps) }]} />
    </div>
    <p className="signal-explorer-helper">A and C/B forecast different horizons and use separate axes. Near the session close, effective horizons shorten. Forecasts use a completed bar; replay execution can occur at the following bar open. Forecast revisions do not necessarily change integer positions or produce a fill. All positions shown are simulated inventory, not desired target orders.</p>
    <TimePlot title="Text adapter · Incremental return forecast" unit="bps" zero points={series.points} selected={selected} lines={[{ label: 'Effective B-minus-C return adjustment', color: '#fbbf24', values: series.points.map(item => item.text?.effective_adjustment_bps ?? null) }]} />
    <div className="signal-explorer-text-block"><div className="signal-explorer-block-heading"><h3>Text evidence at {time(point.timestamp)} ET</h3><span>{text?.primary_asof_eligible ? 'Point-in-time eligibility passed' : 'No eligible text adjustment'}</span></div><p>{(text?.fallback_reason ? readableState(text.fallback_reason) : null) ?? (text?.has_text ? 'Text features were available. Review the calibration status and contribution decomposition below.' : point.has_decision ? 'No usable text snapshot is attached to this decision.' : 'No forecast was scheduled at this bar.')}</p><p>Calibration: <strong>{readableState(series.text_calibration.status)}</strong> · {series.text_calibration.training_text_rows} training rows · {series.text_calibration.training_sessions} training sessions · cutoff {instant(series.text_calibration.training_cutoff)}</p>{series.text_calibration.reason && <p>{readableState(series.text_calibration.reason)}</p>}<p>C price calibration scale: {numeric(series.C_scale, 4)}. Receipt dates across the artifact: {report.summary.distinct_receipt_dates.join(', ') || 'Unavailable'}. Multiple decision rows from a source batch are not independent events.</p></div>
    <div className="signal-explorer-detail-grid"><div className="signal-explorer-contributions"><h3>Text-return contribution decomposition</h3><p className="signal-explorer-helper">Linear-model attribution to the full 30-minute adjustment. This is not a causal explanation of price moves.</p>{contributions.length ? contributions.map(item => <div className="signal-explorer-contribution" key={item.feature}><div><span>{definitions[item.feature]?.label ?? item.feature}</span><strong>{bps(item.contribution_bps)}</strong></div><div className="signal-explorer-contribution-track"><i className={item.contribution_bps >= 0 ? 'is-positive' : 'is-negative'} style={{ width: `${Math.abs(item.contribution_bps) / contributionScale * 50}%`, left: item.contribution_bps >= 0 ? '50%' : `${50 - Math.abs(item.contribution_bps) / contributionScale * 50}%` }} /></div><small>Value {numeric(item.value, 4)} · standardized {numeric(item.standardized, 4)} · coefficient {bps(item.coefficient_bps)}</small></div>) : <p className="signal-explorer-empty">No applied model contributions at this decision. Missing attribution is not a zero-effect estimate.</p>}<dl className="signal-explorer-decomposition"><div><dt>Calibration intercept</dt><dd>{bps(text?.intercept_bps ?? null)}</dd></div><div><dt>Raw adjustment</dt><dd>{bps(text?.raw_adjustment_bps ?? null)}</dd></div><div><dt>Clipping correction</dt><dd>{bps(text?.clip_adjustment_bps ?? null)}</dd></div><div><dt>Serialization rounding correction</dt><dd>{bps(text?.rounding_adjustment_bps ?? null)}</dd></div><div><dt>Full 30-minute adjustment</dt><dd>{bps(text?.full_adjustment_bps ?? null)}</dd></div><div><dt>Effective-horizon adjustment</dt><dd>{bps(text?.effective_adjustment_bps ?? null)}</dd></div></dl><p className="signal-explorer-helper">Contributions plus intercept equal the raw adjustment. Clipping and serialization rounding reconcile it to the full-horizon adjustment.</p><p className="signal-explorer-helper">B minus C includes the full adapter: text features, calibration intercept, availability and clipping. It does not isolate sentiment meaning alone.</p></div>
      <div className="signal-explorer-evidence"><h3>Source versions and availability</h3>{evidence.length ? evidence.map((item, index) => <article key={`${item.source_id}-${index}`}><div><strong>{item.source}</strong><span>{item.receipt_verified ? 'Receipt verified' : 'Receipt unverified'}</span></div><p>{item.title}</p><dl><div><dt>Published</dt><dd>{instant(item.published_at)}</dd></div><div><dt>Updated</dt><dd>{instant(item.updated_at)}</dd></div><div><dt>Received</dt><dd>{instant(item.received_at)}</dd></div><div><dt>Available</dt><dd>{instant(item.available_at)}</dd></div></dl><small>Source ID: {item.source_id}</small></article>) : <p className="signal-explorer-empty">No source versions are attached at this selected time. Later publication or receipt cannot be used to explain an earlier trading decision.</p>}</div></div>
    <details className="signal-explorer-details"><summary>Feature values and definitions</summary><p>These are encoded model inputs. A zero can represent unavailable text or an absent event; it does not automatically mean neutral investor sentiment. The availability status above determines whether text was usable.</p><div className="signal-explorer-table-wrap"><table><thead><tr><th>Feature</th><th>Encoded model value</th><th>Unit and definition</th></tr></thead><tbody>{report.feature_definitions.map(item => <tr key={item.id}><th scope="row">{item.label}</th><td>{text && Object.hasOwn(text.feature_values, item.id) ? numeric(text.feature_values[item.id], 4) : 'Unavailable'}</td><td>{item.unit} · {item.detail}</td></tr>)}</tbody></table></div></details>
    <details className="signal-explorer-details"><summary>Post-decision return diagnostics</summary><p>These realized returns became known after the selected decision. They are diagnostic outcomes, not model inputs, portfolio returns, trading hit rates, or evidence that a forecast was tradable at its reference price.</p><div className="signal-explorer-table-wrap"><table><thead><tr><th>Model</th><th>Nominal / effective horizon</th><th>Forecast</th><th>Realized outcome</th><th>Outcome known at</th></tr></thead><tbody>{(['A', 'C', 'B'] as ModelId[]).map(id => <tr key={id}><th scope="row">{id}</th><td>{point[id].nominal_horizon_minutes}m / {point[id].effective_horizon_minutes === null ? 'Unavailable' : `${numeric(point[id].effective_horizon_minutes, 0)}m`}</td><td>{bps(point[id].forecast_bps)}</td><td>{bps(point[id].realized_bps)}</td><td>{instant(point[id].realized_end_at)}</td></tr>)}</tbody></table></div></details>
    <details className="signal-explorer-details"><summary>Simulated fill records for {positionModel}</summary><p>These rows show executed replay quantities and prices. An adjusted forecast can leave the position unchanged; a position adjustment can require several fills.</p><div className="signal-explorer-table-wrap"><table><thead><tr><th>Time (ET)</th><th>Side</th><th>Shares</th><th>Fill price</th><th>Reason</th></tr></thead><tbody>{fills.map((fill, i) => <tr key={`${fill.timestamp}-${i}`}><th scope="row">{time(fill.timestamp)}</th><td>{fill.side}</td><td>{numeric(fill.quantity, 0)}</td><td>${numeric(fill.fill_price)}</td><td>{readableState(fill.reason)}</td></tr>)}</tbody></table>{fills.length === 0 && <p>No simulated fills for this model and session.</p>}</div></details>
    <details className="signal-explorer-details"><summary>Artifact scope and limitations</summary><p>Generated {instant(report.generated_at)} · {report.summary.series_count} company–session traces · {report.summary.decision_count} saved decisions · {report.summary.changed_prediction_count} revised company forecasts. Assumed friction: {report.cost_bps_per_side} bps per side.</p><ul>{report.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul></details>
  </section>;
}
