import { useEffect, useState } from 'react';
import { API_BASE } from '../config';
import './StrategyComparisonPanel.css';

type ModelId = 'A' | 'B' | 'C';
interface ComparisonModel {
  id: ModelId;
  name: string;
  description: string;
  net_pnl: number;
  net_return: number;
  max_drawdown: number;
  costs: number;
  fill_count: number;
  mean_gross_exposure: number;
  mean_daily_turnover: number;
}
interface CurvePoint { date: string; A: number; B: number; C: number }
interface ComparisonReport {
  schema_version: 1;
  generated_at: string;
  evaluation_kind: 'retrospective_development';
  requested_start: string;
  requested_end: string;
  evaluated_start: string;
  evaluated_end: string;
  sessions: number;
  starting_capital: number;
  currency: 'USD';
  models: ComparisonModel[];
  curves: CurvePoint[];
  text: {
    source_records: number;
    usable_decisions: number;
    changed_decisions: number;
    calibration_status: string;
    fallback_reason: string | null;
  };
  coverage: { complete_requested_period: boolean; missing_sessions: string[] };
  limitations: string[];
  promoted: false;
}

const labels: Record<ModelId, string> = { A: 'A · Original policy', B: 'B · New candidate', C: 'C · Price-only control' };
const colors: Record<ModelId, string> = { A: '#60a5fa', B: '#2dd4bf', C: '#c4b5fd' };
const money = (value: number) => new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 2,
}).format(value);
const signedMoney = (value: number) => `${value > 0 ? '+' : ''}${money(value)}`;
const percent = (value: number) => `${(value * 100).toFixed(2)}%`;
const number = (value: number) => value.toLocaleString('en-US');

function validReport(value: ComparisonReport): boolean {
  const metricKeys = ['net_pnl', 'net_return', 'max_drawdown', 'costs', 'fill_count', 'mean_gross_exposure', 'mean_daily_turnover'] as const;
  return value?.schema_version === 1 && value.evaluation_kind === 'retrospective_development'
    && value.promoted === false && value.currency === 'USD'
    && Number.isFinite(value.starting_capital) && value.starting_capital > 0
    && Array.isArray(value.models) && value.models.length === 3
    && new Set(value.models.map(model => model.id)).size === 3
    && value.models.every(model => ['A', 'B', 'C'].includes(model.id)
      && typeof model.name === 'string' && typeof model.description === 'string'
      && metricKeys.every(key => Number.isFinite(model[key])))
    && Array.isArray(value.curves) && value.curves.length === value.sessions && value.sessions > 0
    && value.curves.every(row => typeof row.date === 'string' && [row.A, row.B, row.C].every(Number.isFinite))
    && !!value.text && ['source_records', 'usable_decisions', 'changed_decisions'].every(key =>
      Number.isFinite(value.text[key as 'source_records' | 'usable_decisions' | 'changed_decisions']))
    && typeof value.text.calibration_status === 'string'
    && (value.text.fallback_reason === null || typeof value.text.fallback_reason === 'string')
    && !!value.coverage && typeof value.coverage.complete_requested_period === 'boolean'
    && Array.isArray(value.coverage.missing_sessions)
    && Array.isArray(value.limitations) && value.limitations.every(item => typeof item === 'string');
}

function EquityChart({ report, showControl }: { report: ComparisonReport; showControl: boolean }) {
  const series: ModelId[] = showControl ? ['A', 'B', 'C'] : ['A', 'B'];
  const points: CurvePoint[] = [
    { date: 'Start', A: report.starting_capital, B: report.starting_capital, C: report.starting_capital },
    ...report.curves,
  ];
  const values = points.flatMap(point => series.map(id => point[id]));
  const low = Math.min(...values), high = Math.max(...values);
  const padding = Math.max((high - low) * .12, report.starting_capital * .001);
  const min = low - padding, max = high + padding;
  const left = 82, right = 790, top = 22, bottom = 256;
  const x = (index: number) => left + index / (points.length - 1) * (right - left);
  const y = (value: number) => bottom - (value - min) / (max - min) * (bottom - top);
  const ticks = Array.from({ length: 5 }, (_, index) => min + index * (max - min) / 4);
  const dateIndices = [...new Set([0, Math.round((points.length - 1) / 2), points.length - 1])];
  return <div className="strategy-comparison-chart">
    <svg viewBox="0 0 820 302" role="img" aria-labelledby="strategy-comparison-chart-title strategy-comparison-chart-desc">
      <title id="strategy-comparison-chart-title">Equal-capital simulated equity: original policy versus new candidate</title>
      <desc id="strategy-comparison-chart-desc">Daily closing equity in US dollars, from {money(report.starting_capital)} shared starting capital. {report.evaluated_start} through {report.evaluated_end}. Assumed transaction friction is included. Daily values are also available in the table below.</desc>
      {ticks.map(value => <g key={value}>
        <line x1={left} x2={right} y1={y(value)} y2={y(value)} className="strategy-comparison-grid" />
        <text x={left - 12} y={y(value) + 4} textAnchor="end" className="strategy-comparison-axis">{new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1, style: 'currency', currency: 'USD' }).format(value)}</text>
      </g>)}
      <line x1={left} x2={right} y1={y(report.starting_capital)} y2={y(report.starting_capital)} className="strategy-comparison-start-line" />
      {series.map(id => <g key={id}>
        <polyline fill="none" stroke={colors[id]} strokeWidth={id === 'C' ? 2 : 2.8} strokeDasharray={id === 'C' ? '7 5' : undefined}
          points={points.map((point, index) => `${x(index)},${y(point[id])}`).join(' ')} />
        {points.map((point, index) => <circle key={point.date} cx={x(index)} cy={y(point[id])} r={index === points.length - 1 ? 4 : 2.5} fill={colors[id]}>
          <title>{labels[id]} · {point.date}: {money(point[id])}</title>
        </circle>)}
      </g>)}
      {dateIndices.map(index => <text key={index} x={x(index)} y={282} textAnchor={index === 0 ? 'start' : index === points.length - 1 ? 'end' : 'middle'} className="strategy-comparison-axis">{points[index].date}</text>)}
    </svg>
    <div className="strategy-comparison-legend">{series.map(id => <span key={id}><i style={{ backgroundColor: colors[id] }} />{labels[id]}</span>)}</div>
  </div>;
}

export function StrategyComparisonPanel({ revision }: { revision: number }) {
  const [report, setReport] = useState<ComparisonReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [showControl, setShowControl] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true); setReport(null); setError(null); setMissing(false);
      try {
        const response = await fetch(`${API_BASE}/api/research/financial-sentiment/comparison`, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12_000)]),
          headers: { Accept: 'application/json' },
        });
        if (response.status === 404) { if (!controller.signal.aborted) setMissing(true); return; }
        if (!response.ok) throw new Error(`The saved comparison is unavailable (HTTP ${response.status}).`);
        if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('The comparison service returned an unexpected response.');
        const value = await response.json() as ComparisonReport;
        if (!validReport(value)) throw new Error('The saved comparison has an unexpected format.');
        if (!controller.signal.aborted) setReport(value);
      } catch (reason: unknown) {
        if (!controller.signal.aborted) setError(reason instanceof Error && reason.name === 'TimeoutError'
          ? 'The comparison took too long to respond. Reload saved reports to try again.'
          : reason instanceof Error ? reason.message : 'The saved comparison is unavailable.');
      } finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void load();
    return () => controller.abort();
  }, [revision]);

  const heading = <div className="fsr-section-heading"><h2 id="strategy-comparison-title">Old vs new strategy</h2><span>Equal-capital development replay</span></div>;
  if (loading) return <section className="fsr-card strategy-comparison" aria-labelledby="strategy-comparison-title">{heading}<p className="fsr-help" role="status">Loading the saved strategy comparison…</p></section>;
  if (missing) return <section className="fsr-card strategy-comparison" aria-labelledby="strategy-comparison-title">{heading}<div className="fsr-message"><strong>Comparison not generated</strong><p>No saved A/B experiment is available. Reloading this page does not run a backtest or place orders.</p></div></section>;
  if (error || !report) return <section className="fsr-card strategy-comparison" aria-labelledby="strategy-comparison-title">{heading}<div className="fsr-message fsr-error" role="alert"><strong>Comparison unavailable</strong><p>{error ?? 'No validated saved comparison is available.'}</p></div></section>;

  const a = report.models.find(model => model.id === 'A')!;
  const b = report.models.find(model => model.id === 'B')!;
  const c = report.models.find(model => model.id === 'C')!;
  const visibleModels = showControl ? [a, b, c] : [a, b];
  const difference = b.net_pnl - a.net_pnl;
  const dailyRows = [{ date: 'Starting capital', A: report.starting_capital, B: report.starting_capital, C: report.starting_capital }, ...report.curves];
  return <section className="fsr-card strategy-comparison" aria-labelledby="strategy-comparison-title">
    {heading}
    <p className="strategy-comparison-intro">The original policy and the new candidate start with <strong>{money(report.starting_capital)}</strong> each, over the same <strong>{report.sessions} trading sessions</strong>.</p>
    <div className="strategy-comparison-period"><span>Evaluated: {report.evaluated_start} → {report.evaluated_end}</span><span>Retrospective development · No live promotion</span></div>
    <p className="fsr-help">Simulated results include an assumed 2 bps of friction per side (0.02% of traded value). These are not broker account returns or measured trading costs.</p>
    {!report.coverage.complete_requested_period && <div className="strategy-comparison-notice" role="note"><strong>Partial requested-period coverage</strong><p>Requested: {report.requested_start} → {report.requested_end}. The chart only covers the evaluated dates above; missing sessions are not treated as zero-return days.</p>{report.coverage.missing_sessions.length > 0 && <details><summary>{report.coverage.missing_sessions.length} missing sessions</summary><p>{report.coverage.missing_sessions.join(', ')}</p></details>}</div>}
    <div className="strategy-comparison-headline-metrics">
      {[a, b].map(model => <div key={model.id}><span>{labels[model.id]}</span><strong className={model.net_pnl >= 0 ? 'strategy-comparison-positive' : 'strategy-comparison-negative'}>{signedMoney(model.net_pnl)}</strong><small>Net simulated PnL · {percent(model.net_return)}</small></div>)}
      <div><span>B minus A</span><strong className={difference >= 0 ? 'strategy-comparison-positive' : 'strategy-comparison-negative'}>{signedMoney(difference)}</strong><small>{difference > 0 && b.net_pnl < 0 ? 'Lower simulated loss; still negative' : difference > 0 ? 'Higher simulated PnL' : difference < 0 ? 'Lower simulated PnL' : 'No simulated difference'}</small></div>
    </div>
    <EquityChart report={report} showControl={showControl} />
    <label className="strategy-comparison-toggle"><input type="checkbox" checked={showControl} onChange={event => setShowControl(event.target.checked)} />Show C: price-only control</label>
    <div className="strategy-comparison-table-wrap"><table className="strategy-comparison-table"><caption>Risk, trading activity, and assumed costs</caption><thead><tr><th scope="col">Metric</th>{visibleModels.map(model => <th scope="col" key={model.id}>{labels[model.id]}</th>)}</tr></thead><tbody>
      <tr><th scope="row">Maximum drawdown</th>{visibleModels.map(model => <td key={model.id}>{percent(model.max_drawdown)}</td>)}</tr>
      <tr><th scope="row">Assumed costs</th>{visibleModels.map(model => <td key={model.id}>{money(model.costs)}</td>)}</tr>
      <tr><th scope="row">Fills</th>{visibleModels.map(model => <td key={model.id}>{number(model.fill_count)}</td>)}</tr>
      <tr><th scope="row">Average gross exposure</th>{visibleModels.map(model => <td key={model.id}>{percent(model.mean_gross_exposure)}</td>)}</tr>
      <tr><th scope="row">Daily turnover / equity</th>{visibleModels.map(model => <td key={model.id}>{model.mean_daily_turnover.toFixed(2)}×</td>)}</tr>
    </tbody></table></div>
    <div className="strategy-comparison-text"><div className="strategy-comparison-text-heading"><h3>What did the text adapter change?</h3><span>B minus C: <strong>{signedMoney(b.net_pnl - c.net_pnl)}</strong></span></div><p>{report.text.changed_decisions === 0 ? 'No text-adapter forecast revisions in this window. Any A/B difference comes from the price-policy changes.' : 'Compare B with the price-only C control to measure the incremental replay result of the text adapter.'}</p><div className="strategy-comparison-text-counts"><span><strong>{number(report.text.source_records)}</strong> unique text versions audited</span><span><strong>{number(report.text.usable_decisions)}</strong> company–bar pairs with usable text</span><span><strong>{number(report.text.changed_decisions)}</strong> decisions with revised forecasts</span></div><p>Forecast revisions count portfolio decision times with at least one changed return forecast; they are not changed orders or fills. Text versions are not independent events. B minus C includes the entire adapter, including calibration intercepts and availability, rather than isolating sentiment meaning.</p><p>Calibration: {report.text.calibration_status}</p>{report.text.fallback_reason && <p>{report.text.fallback_reason}</p>}</div>
    <details className="strategy-comparison-details"><summary>Model definitions and evidence limits</summary>{report.models.map(model => <p key={model.id}><strong>{labels[model.id]} — {model.name}</strong><br />{model.description}</p>)}<ul>{report.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul><p>Generated: {report.generated_at}</p></details>
    <details className="strategy-comparison-details"><summary>Daily equity values</summary><div className="strategy-comparison-table-wrap"><table className="strategy-comparison-table"><caption>Daily closing simulated equity in USD</caption><thead><tr><th scope="col">Date</th>{visibleModels.map(model => <th scope="col" key={model.id}>{model.id}</th>)}</tr></thead><tbody>{dailyRows.map(row => <tr key={row.date}><th scope="row">{row.date}</th>{visibleModels.map(model => <td key={model.id}>{money(row[model.id])}</td>)}</tr>)}</tbody></table></div></details>
  </section>;
}
