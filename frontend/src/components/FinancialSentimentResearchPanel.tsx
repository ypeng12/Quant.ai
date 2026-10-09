import { useEffect, useState } from 'react';
import { API_BASE } from '../config';
import { CommunityMonitorPanel } from './CommunityMonitorPanel';
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
        <span className="fsr-audit-badge">Historical audit{status ? ` · ${status.audit_date}` : ''}</span>
        <button className="fsr-reload" onClick={reload}>Reload summary</button>
      </div>
    </header>

    {error ? <div className="fsr-message fsr-error" role="alert"><strong>Research summary unavailable</strong><p>{error}</p><p>No substitute counts or model results are displayed.</p><button className="fsr-reload" onClick={reload}>Retry</button></div> : !status ? <div className="fsr-message" role="status">Loading the saved research summary…</div> : <>
      <div className="fsr-metrics" aria-label="Research status">
        <div><span>Model status</span><strong>{status.model_status}</strong><p>Text models and signals require validation.</p></div>
        <div><span>Evaluation status</span><strong>{status.evaluation_status}</strong><p>No A/B performance claim is established.</p></div>
        <div><span>Exploratory return labels</span><strong>{Number.isFinite(status.exploratory_labels) ? status.exploratory_labels.toLocaleString('en-US') : 'Unavailable'}</strong><p>{status.labels_are_predictions === false ? 'Realized historical outcomes, not predictions.' : 'Label interpretation has not been confirmed.'}</p></div>
      </div>

      <div className="fsr-summary-grid">
        <section className="fsr-card" aria-labelledby="fsr-coverage-title">
          <div className="fsr-section-heading"><h2 id="fsr-coverage-title">Observed data coverage</h2><span>Saved snapshot</span></div>
          <p className="fsr-help">Counts describe different record types. They do not measure independent events, useful signals, or training quality.</p>
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

    <section className="fsr-community" aria-labelledby="fsr-community-title">
      <div className="fsr-section-heading"><h2 id="fsr-community-title">Company community feed</h2><span>Selected company: {symbol}</span></div>
      <p className="fsr-help">This section reads the existing collection database for the selected watchlist company. Its latest source status is separate from the historical audit above. Missing posts or a waiting source are shown as recorded.</p>
      <CommunityMonitorPanel key={symbol} symbol={symbol} />
    </section>

    <footer className="fsr-research-goal"><strong>Target outcome</strong><p>A reproducible comparison of Quant.ai with and without validated text signals, at equal starting capital and comparable risk. Collection coverage and exploratory labels alone do not establish a trading advantage.</p></footer>
  </section>;
}
