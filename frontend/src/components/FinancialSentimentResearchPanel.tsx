import { useEffect, useState } from 'react';
import { API_BASE } from '../config';
import { CommunityMonitorPanel } from './CommunityMonitorPanel';
import { StockContextPanel } from './StockContextPanel';
import './FinancialSentimentResearchPanel.css';

interface ResearchSource {
  id: string;
  name: string;
  records: number | null;
  status: string;
  detail: string;
}

interface ResearchStatus {
  project: string;
  audit_date: string;
  model_status: string;
  evaluation_status: string;
  current_stage: string;
  next_stage?: string;
  exploratory_labels: number;
  labels_are_predictions: boolean;
  sources: ResearchSource[];
}

interface EvidenceEvent {
  id: string;
  event_type: string;
  claim_kind: string;
  summary: string;
  article_count: number;
  earliest_reported_at: string | null;
  source_urls: string[];
  tone: string;
  headline_only: boolean;
}

interface EvidenceCompany {
  symbol: string;
  article_count: number;
  headline_only_count: number;
  cluster_count: number;
  price_context: {
    status: string;
    return_pct: number | null;
    excess_vs_spy_pp: number | null;
    excess_vs_sector_pp: number | null;
    sector_benchmark: string;
  };
  sentiment: { positive: number; negative: number; neutral: number; unavailable: number };
  findings: string[];
  limitations: string[];
  events: EvidenceEvent[];
}

interface EvidenceReport {
  schema_version: '1.0';
  generated_at: string;
  price_asof: string;
  analysis_mode: string;
  extraction_method: string;
  model_status: string;
  prediction_status: string;
  ab_status: string;
  coverage: { articles_loaded: number; article_company_pairs: number; classified_pairs: number; clusters: number };
  companies: EvidenceCompany[];
}

const companyEventTypes = new Set(['analyst_revision', 'partnership', 'product', 'financial_results', 'contract_change']);

function reportTime(value: string | null): string {
  if (!value) return 'Time unavailable';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value} (date only)`;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? 'Time unavailable' : parsed.toLocaleString('en-US', {
    timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  });
}

function observedReturn(value: number | null, unit: '%' | 'pp'): string {
  if (value === null || !Number.isFinite(value)) return 'Unavailable';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}${unit === '%' ? '%' : ' pp'}`;
}

function EvidenceReportPanel({ symbol, revision }: { symbol: string; revision: number }) {
  const [report, setReport] = useState<EvidenceReport | null>(null);
  const [reportSymbol, setReportSymbol] = useState<string | null>(null);
  const [expandedCompany, setExpandedCompany] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      setError(null);
      setMissing(false);
      setReport(null);
      try {
        const response = await fetch(`${API_BASE}/api/research/financial-sentiment/report`, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12_000)]),
          headers: { Accept: 'application/json' },
        });
        if (response.status === 404) {
          if (!controller.signal.aborted) setMissing(true);
          return;
        }
        if (!response.ok) throw new Error(`Saved report unavailable (HTTP ${response.status}).`);
        if (!response.headers.get('content-type')?.includes('application/json')) {
          throw new Error('The report service returned an unexpected response.');
        }
        const result = await response.json() as EvidenceReport;
        if (result?.schema_version !== '1.0' || !result.coverage || !Array.isArray(result.companies)
            || !result.companies.length) throw new Error('The saved report has an unexpected format.');
        if (!controller.signal.aborted) setReport(result);
      } catch (reason: unknown) {
        if (!controller.signal.aborted) setError(reason instanceof Error && reason.name === 'TimeoutError'
          ? 'The saved report took too long to respond. Reload the saved reports to try again.'
          : reason instanceof Error ? reason.message : 'The saved report is unavailable.');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, [revision]);

  const company = report?.companies.find(item => item.symbol === (reportSymbol ?? symbol)) ?? report?.companies[0];
  const heading = <div className="fsr-section-heading"><h2 id="fsr-report-title">Automated evidence report</h2><span>Saved prototype output</span></div>;

  if (loading) return <section className="fsr-card fsr-report" aria-labelledby="fsr-report-title">{heading}<p className="fsr-help" role="status">Loading the saved evidence report…</p></section>;
  if (missing) return <section className="fsr-card fsr-report" aria-labelledby="fsr-report-title">{heading}<div className="fsr-message"><strong>Report not generated</strong><p>The prototype has no saved report available. Opening this page does not collect data or run a model.</p></div></section>;
  if (error || !report || !company) return <section className="fsr-card fsr-report" aria-labelledby="fsr-report-title">{heading}<div className="fsr-message fsr-error" role="alert"><strong>Evidence report unavailable</strong><p>{error ?? 'No valid saved report is available.'}</p><p>No substitute events or analysis are displayed.</p></div></section>;

  const prices = company.price_context;
  const sortedEvents = [...company.events].sort((left, right) => {
    const leftTime = Date.parse(left.earliest_reported_at ?? '');
    const rightTime = Date.parse(right.earliest_reported_at ?? '');
    const order = (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
    return order || left.id.localeCompare(right.id);
  });
  const companyEvents = sortedEvents.filter(event => companyEventTypes.has(event.event_type));
  const showingAll = expandedCompany === company.symbol;
  const visibleEvents = showingAll ? sortedEvents : (companyEvents.length ? companyEvents : sortedEvents).slice(0, 12);
  return <section className="fsr-card fsr-report" aria-labelledby="fsr-report-title">
    {heading}
    <p className="fsr-help"><strong>{report.analysis_mode}</strong> · {report.extraction_method}. Rules identify candidate events; pretrained FinBERT classifies text tone. Tone is not a forecast of a stock’s return.</p>
    <div className="fsr-report-times"><span>Generated: <time dateTime={report.generated_at}>{reportTime(report.generated_at)}</time></span><span>Prices through: <time dateTime={report.price_asof}>{reportTime(report.price_asof)}</time></span></div>
    <div className="fsr-metrics fsr-report-status">
      <div><span>Text analysis</span><strong>{report.model_status}</strong><p>Rule extraction and pretrained tone inference.</p></div>
      <div><span>Price prediction</span><strong>{report.prediction_status}</strong><p>No calibrated probability of a price increase.</p></div>
      <div><span>Equal-capital A/B</span><strong>{report.ab_status}</strong><p>No trading advantage has been established.</p></div>
    </div>
    <div className="fsr-report-coverage" aria-label="Report coverage">
      <span><strong>{report.coverage.articles_loaded.toLocaleString('en-US')}</strong> articles loaded</span>
      <span><strong>{report.coverage.article_company_pairs.toLocaleString('en-US')}</strong> article–company pairs</span>
      <span><strong>{report.coverage.classified_pairs.toLocaleString('en-US')}</strong> classified pairs</span>
      <span><strong>{report.coverage.clusters.toLocaleString('en-US')}</strong> candidate event clusters</span>
    </div>
    <div className="fsr-report-selector"><label htmlFor="fsr-report-company">Report company</label><select id="fsr-report-company" value={company.symbol} onChange={event => { setReportSymbol(event.target.value); setExpandedCompany(null); }}>{report.companies.map(item => <option key={item.symbol} value={item.symbol}>{item.symbol}</option>)}</select><span>This selection does not change your watchlist.</span></div>
    {!report.companies.some(item => item.symbol === symbol) && <p className="fsr-help">No prototype report is available for watchlist selection {symbol}. Choose an available report company above.</p>}
    <div className="fsr-section-heading"><h3 className="fsr-company-heading">{company.symbol} · Observed price context</h3><span>{prices.status}</span></div>
    <div className="fsr-price-context">
      <div><span>Observed return</span><strong>{observedReturn(prices.return_pct, '%')}</strong></div>
      <div><span>Difference vs SPY</span><strong>{observedReturn(prices.excess_vs_spy_pp, 'pp')}</strong></div>
      <div><span>Difference vs {prices.sector_benchmark}</span><strong>{observedReturn(prices.excess_vs_sector_pp, 'pp')}</strong></div>
    </div>
    <p className="fsr-help">Realized price changes in the saved review window. Benchmark differences do not identify a news effect or account for trading costs.</p>
    <div className="fsr-tone-counts" aria-label="Text tone counts">{(['positive', 'negative', 'neutral', 'unavailable'] as const).map(tone => <span key={tone} className={`fsr-tone fsr-tone-${tone}`}>{tone === 'unavailable' ? 'Tone unavailable' : `${tone[0].toUpperCase()}${tone.slice(1)} tone`}: <strong>{company.sentiment[tone]}</strong></span>)}</div>
    <p className="fsr-help">{company.article_count} associated articles · {company.headline_only_count} headline-only articles · {company.cluster_count} candidate clusters. Text tone counts do not represent investor sentiment or independent votes.</p>
    {company.findings.length > 0 && <div className="fsr-report-findings"><h3>Review findings</h3><ul>{company.findings.map((finding, index) => <li key={index}>{finding}</li>)}</ul></div>}
    <div className="fsr-event-list">
      <div className="fsr-event-list-heading"><h3>Candidate events and sources</h3>{(showingAll || visibleEvents.length < sortedEvents.length) && <button className="fsr-reload" onClick={() => setExpandedCompany(showingAll ? null : company.symbol)}>{showingAll ? 'Show company events' : 'Show all candidate events'}</button>}</div>
      <p className="fsr-help" aria-live="polite">Showing {visibleEvents.length} of {sortedEvents.length} candidate events, newest archive reports first. {showingAll ? 'The full list includes market commentary, trading activity, and other mentions.' : companyEvents.length ? 'Up to 12 company events: analyst revisions, partnerships, products, financial results, and contract changes.' : 'No company event types were identified; showing up to 12 other candidates.'}</p>
      {company.events.length === 0 ? <p className="fsr-help">No candidate events are available in this saved report.</p> : visibleEvents.map(event => <article className="fsr-event" key={event.id}>
        <div className="fsr-event-tags"><span>{event.event_type.replaceAll('_', ' ')}</span><span>{event.claim_kind.replaceAll('_', ' ')}</span><span>Text tone: {event.tone}</span>{event.headline_only && <span className="fsr-headline-only">Headline-only evidence</span>}</div>
        <p className="fsr-event-summary">{event.summary}</p>
        <div className="fsr-event-meta"><span>{event.article_count} associated {event.article_count === 1 ? 'article' : 'articles'}</span><span>Earliest report in this archive: {reportTime(event.earliest_reported_at)}</span></div>
        <div className="fsr-event-sources">{event.source_urls.length ? event.source_urls.map((url, index) => <a key={`${url}-${index}`} href={url} target="_blank" rel="noopener noreferrer">Source {index + 1} ↗</a>) : <span>Source link unavailable</span>}</div>
      </article>)}
    </div>
    <p className="fsr-footnote">Archive publication times do not establish earliest public availability or first system receipt. Candidate clusters and tone labels are automated research outputs; they do not establish causality.</p>
    {company.limitations.length > 0 && <div className="fsr-report-limitations"><h3>Evidence limits</h3><ul>{company.limitations.map((limit, index) => <li key={index}>{limit}</li>)}</ul></div>}
  </section>;
}

const milestones = [
  { title: 'Data audit', description: 'Check actual coverage, missing fields, timing, and duplicate records.' },
  { title: 'Persistent collection', description: 'Retain first-seen times and text versions before constructing signals.' },
  { title: 'Price-label models', description: 'Compare price-only, traditional sentiment, and price-label text baselines.' },
  { title: 'Equal-capital A/B', description: 'Evaluate net performance using the same starting capital and risk constraints.' },
];

function loadError(reason: unknown): string {
  if (reason instanceof Error && reason.name === 'TimeoutError') {
    return 'The research summary took too long to respond. Try again.';
  }
  return reason instanceof Error ? reason.message : 'The research summary is unavailable.';
}

export function FinancialSentimentResearchPanel({ symbol }: { symbol: string }) {
  const [status, setStatus] = useState<ResearchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/research/financial-sentiment/status`, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12_000)]),
          headers: { Accept: 'application/json' },
        });
        if (!response.ok) throw new Error(`Research summary unavailable (HTTP ${response.status}).`);
        if (!response.headers.get('content-type')?.includes('application/json')) {
          throw new Error('The research service returned an unexpected response.');
        }
        const result = await response.json() as ResearchStatus;
        if (!result || typeof result.project !== 'string' || !Array.isArray(result.sources)) {
          throw new Error('The research summary has an unexpected format.');
        }
        if (!controller.signal.aborted) setStatus(result);
      } catch (reason: unknown) {
        if (!controller.signal.aborted) setError(loadError(reason));
      }
    };
    void load();
    return () => controller.abort();
  }, [revision]);

  const reload = () => {
    setStatus(null);
    setError(null);
    setRevision(value => value + 1);
  };

  return <section className="financial-sentiment-research" aria-label="Financial sentiment research">
    <header className="fsr-header">
      <div>
        <p className="fsr-eyebrow">QUANT.AI · TEXT RESEARCH</p>
        <h1>Financial Sentiment</h1>
        <p className="fsr-intro">Test whether company news and community sentiment add predictive value to Quant.ai.</p>
        {status && <p className="fsr-project-name">{status.project}</p>}
      </div>
      <div className="fsr-header-actions">
        <span className="fsr-audit-badge">Saved research outputs</span>
        <button className="fsr-reload" onClick={reload}>Reload saved reports</button>
        <span className="fsr-reload-help">Reads saved files; does not run collection or inference.</span>
      </div>
    </header>

    <StockContextPanel revision={revision} />
    <EvidenceReportPanel symbol={symbol} revision={revision} />

    <details className="fsr-diagnostics">
      <summary>Data diagnostics <span>Historical audit{status ? ` · ${status.audit_date}` : ''}</span></summary>
    {error ? <div className="fsr-message fsr-error" role="alert"><strong>Research summary unavailable</strong><p>{error}</p><p>No substitute counts or model results are displayed.</p><button className="fsr-reload" onClick={reload}>Retry</button></div> : !status ? <div className="fsr-message" role="status">Loading the saved research summary…</div> : <>
      <div className="fsr-metrics" aria-label="Research status">
        <div><span>Model status</span><strong>{status.model_status}</strong><p>Text models and signals require validation.</p></div>
        <div><span>Evaluation status</span><strong>{status.evaluation_status}</strong><p>No A/B performance claim is established.</p></div>
        <div><span>Exploratory return labels</span><strong>{Number.isFinite(status.exploratory_labels) ? status.exploratory_labels.toLocaleString('en-US') : 'Unavailable'}</strong><p>{status.labels_are_predictions === false ? 'Realized historical outcomes, not predictions.' : 'Label interpretation has not been confirmed.'}</p></div>
      </div>

      <div className="fsr-summary-grid">
        <section className="fsr-card" aria-labelledby="fsr-coverage-title">
          <div className="fsr-section-heading"><h2 id="fsr-coverage-title">Observed data coverage</h2><span>Saved snapshot</span></div>
          <p className="fsr-help">This global historical audit does not change with the selected company. Counts describe different record types; they do not measure independent events, useful signals, or training quality.</p>
          <div className="fsr-source-list">
            {status.sources.map(source => <article key={source.id} className="fsr-source-row">
              <div><h3>{source.name}</h3><p>{source.detail}</p><span className="fsr-source-status">{source.status}</span></div>
              <div className="fsr-source-count"><strong>{source.records === null ? '—' : source.records.toLocaleString('en-US')}</strong><span>{source.records === null ? 'Not available' : 'Records'}</span></div>
            </article>)}
          </div>
          <p className="fsr-footnote">This view exposes aggregate audit results. It does not publish the archived news corpus or imply access to original article bodies.</p>
        </section>

        <section className="fsr-card" aria-labelledby="fsr-roadmap-title">
          <div className="fsr-section-heading"><h2 id="fsr-roadmap-title">Research progress</h2></div>
          <p className="fsr-help">Current stage: <strong>{status.current_stage}</strong></p>
          <ol className="fsr-milestones">{milestones.map((milestone, index) => <li key={milestone.title} className={milestone.title === status.current_stage ? 'fsr-current-stage' : ''}>
            <span className="fsr-step-number" aria-hidden="true">{index + 1}</span><div><h3>{milestone.title}{milestone.title === status.current_stage && <span>Current</span>}</h3><p>{milestone.description}</p></div>
          </li>)}</ol>
          <div className="fsr-next-stage"><span>Next stage</span><strong>{status.next_stage ?? 'Persistent collection'}</strong></div>
        </section>
      </div>
    </>}
    </details>

    <section className="fsr-community" aria-labelledby="fsr-community-title">
      <div className="fsr-section-heading"><h2 id="fsr-community-title">Company community feed</h2><span>Selected company: {symbol}</span></div>
      <p className="fsr-help">This section reads the existing collection database for the selected watchlist company. Its latest source status is separate from the historical audit above. Missing posts or a waiting source are shown as recorded.</p>
      <CommunityMonitorPanel key={symbol} symbol={symbol} />
    </section>

    <footer className="fsr-research-goal"><strong>Target outcome</strong><p>A reproducible comparison of Quant.ai with and without validated text signals, at equal starting capital and comparable risk. Collection coverage and exploratory labels alone do not establish a trading advantage.</p></footer>
  </section>;
}
