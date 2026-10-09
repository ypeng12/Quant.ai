import { useEffect, useState } from 'react'
import { errorMessage, getEvents, getStatus } from './api'
import type { AuditEvent, EventResponse, LabStatus, SourceCoverage } from './api'

const stages = [
  { name: 'Data audit', detail: 'Inspect actual records, timestamps, duplication, and coverage.' },
  { name: 'Persistent collection', detail: 'Keep first-seen timestamps, text versions, and source health.' },
  { name: 'Labels & baselines', detail: 'Align future returns; compare price-only and text baselines.' },
  { name: 'Out-of-sample validation', detail: 'Freeze decisions and evaluate on later dates.' },
  { name: 'Equal-capital A/B', detail: 'Compare net performance under the same risk and execution rules.' },
]

const sourceInitials: Record<string, string> = { news: 'N', futu: 'F', prices: 'P', sec: 'S', x: 'X' }

function timestamp(value: string | null): string {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? 'Invalid timestamp' : new Intl.DateTimeFormat('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
    hour12: false, timeZone: 'UTC',
  }).format(date) + ' UTC'
}

function CoverageRow({ source }: { source: SourceCoverage }) {
  return <div className="coverage-row">
    <div className={`source-icon source-${source.id}`} aria-hidden="true">{sourceInitials[source.id] ?? 'D'}</div>
    <div className="coverage-description"><h3>{source.name}</h3><p>{source.detail}</p></div>
    <div className="coverage-count"><strong>{source.records === null ? '—' : source.records.toLocaleString('en-US')}</strong><span>{source.records === null ? 'Not available' : 'Audit records'}</span></div>
    <span className="source-status">{source.status.replaceAll('_', ' ')}</span>
  </div>
}

function EventCard({ event }: { event: AuditEvent }) {
  return <article className="event-card">
    <div className="event-meta"><span className="event-source">{event.source}</span><span>{event.symbols.length ? event.symbols.join(' · ') : 'No company mapping'}</span></div>
    <h3>{event.title || 'Untitled source record'}</h3>
    <dl className="event-times">
      <div><dt>Published</dt><dd>{timestamp(event.published_at)}</dd></div>
      <div><dt>Received</dt><dd>{timestamp(event.received_at)}</dd></div>
    </dl>
    <div className="event-footer"><span>{event.has_body ? 'Body or excerpt present' : 'Title only'}</span><span className="record-id" title={event.id}>ID {event.id}</span></div>
  </article>
}

function Events({ source, symbol }: { source: 'news' | 'futu'; symbol: string }) {
  const [response, setResponse] = useState<EventResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    getEvents(source, symbol, controller.signal).then(setResponse).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(errorMessage(reason))
    })
    return () => controller.abort()
  }, [source, symbol])
  if (error) return <div className="data-message error-message" role="alert"><strong>Sample records unavailable</strong><p>{error}</p><p>No substitute records are being shown.</p></div>
  if (!response) return <div className="data-message" role="status">Loading archived sample records…</div>
  if (!response.items.length) return <div className="data-message"><strong>No archived records match this filter.</strong><p>Choose another company or source.</p></div>
  return <>
    <p className="results-count" aria-live="polite">Showing {response.items.length} of {response.total.toLocaleString('en-US')} matching archived records. Original source text is preserved.</p>
    <div className="event-grid">{response.items.map(event => <EventCard key={`${event.source}-${event.id}`} event={event} />)}</div>
  </>
}

export default function SignalLab() {
  const [status, setStatus] = useState<LabStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [source, setSource] = useState<'news' | 'futu'>('news')
  const [symbol, setSymbol] = useState('')
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    getStatus(controller.signal).then(setStatus).catch((reason: unknown) => {
      if (!controller.signal.aborted) setStatusError(errorMessage(reason))
    })
    return () => controller.abort()
  }, [refresh])

  function retry() {
    setStatus(null)
    setStatusError(null)
    setRefresh(value => value + 1)
  }

  return <div className="signal-lab">
    <a className="skip-link" href="#main">Skip to content</a>
    <header className="lab-header">
      <a href="/signal-lab.html" className="brand" aria-label="Quant.ai Signal Lab home"><span className="brand-mark" aria-hidden="true">Q<span>·</span></span><span>Quant.ai <span className="brand-divider">/</span> <strong>Signal Lab</strong></span></a>
      <div className="header-right"><span className="research-badge">Research environment</span><a href="#samples">Explore samples <span aria-hidden="true">↗</span></a></div>
    </header>

    <main id="main">
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-copy"><p className="eyebrow"><span className="small-line" />TEXT · MARKET RESPONSE · EVIDENCE</p><h1 id="hero-title">From market text<br />to measurable signal.</h1><p className="hero-description">A research workspace for testing whether company news and community sentiment add value to Quant.ai.</p><div className="hero-tags"><span>Company-level research</span><span>Historical samples only</span></div></div>
        <aside className="research-state" aria-label="Research readiness"><div className="state-heading"><span className="status-dot" />RESEARCH READINESS</div><div className="state-row"><span>Model</span><strong>{status?.model_status ?? 'Not trained'}</strong></div><div className="state-row"><span>Evaluation</span><strong>{status?.evaluation_status ?? 'Not evaluated'}</strong></div><div className="state-row"><span>Current stage</span><strong>{status?.current_stage ?? 'Data audit'}</strong></div><p>These records are evidence for data exploration. They are not live market data, forecasts, or trading signals.</p></aside>
      </section>

      <section className="objective-bar" aria-label="Research objective"><span className="objective-label">THE QUESTION</span><p>Does adding news and sentiment improve <strong>net returns at comparable risk?</strong></p><span className="planned-pill">A/B evaluation planned</span></section>

      <div className="research-layout">
        <section className="panel coverage-panel" aria-labelledby="coverage-title">
          <div className="section-heading"><div><p className="eyebrow">01 / DATA FOUNDATION</p><h2 id="coverage-title">What we actually have</h2></div><span className="subtle-label">Audit: {status?.audit_date ?? '2026-10-07'}</span></div>
          <p className="section-description">Observed coverage from a bounded collection trial. Record counts are not independent events or training-ready samples.</p>
          {statusError ? <div className="data-message error-message" role="alert"><strong>Coverage could not be loaded</strong><p>{statusError}</p><button className="text-button" onClick={retry}>Retry connection</button></div> : status ? <div className="coverage-list">{status.sources.map(item => <CoverageRow key={item.id} source={item} />)}</div> : <div className="data-message" role="status">Loading verified audit coverage…</div>}
          <div className="coverage-note"><span aria-hidden="true">↳</span><p>News, community posts, prices, and filings serve different roles. A larger raw count does not establish predictive value.</p></div>
        </section>

        <aside className="panel stages-panel" aria-labelledby="stages-title"><p className="eyebrow">02 / RESEARCH PATH</p><h2 id="stages-title">One stage at a time</h2><ol className="stage-list">{stages.map((stage, index) => {
          const active = stage.name === (status?.current_stage ?? 'Data audit')
          return <li key={stage.name} className={active ? 'stage-active' : ''}><span className="stage-number">{String(index + 1).padStart(2, '0')}</span><div><h3>{stage.name}{active && <span className="stage-current">Current</span>}</h3><p>{stage.detail}</p></div></li>
        })}</ol><div className="next-step"><span>Next milestone</span><strong>{status?.next_stage ?? 'Persistent collection'} <span aria-hidden="true">→</span></strong></div></aside>
      </div>

      <section className="panel sample-panel" id="samples" aria-labelledby="samples-title"><div className="section-heading"><div><p className="eyebrow">03 / LOOK AT THE EVIDENCE</p><h2 id="samples-title">Inside the sample</h2></div><button className="refresh-button" onClick={retry}>Reload archive <span aria-hidden="true">↻</span></button></div><p className="section-description">A small view into the saved audit. Source publication times and recorded receipt times are different; missing receipt times remain visible.</p>
        <div className="sample-controls"><div className="source-selector" role="group" aria-label="Sample source"><button aria-pressed={source === 'news'} onClick={() => setSource('news')}>Company news</button><button aria-pressed={source === 'futu'} onClick={() => setSource('futu')}>Futu community</button></div><label className="symbol-filter">Company<select value={symbol} onChange={event => setSymbol(event.target.value)}><option value="">All audited companies</option><option>NVDA</option><option>SNDK</option><option>TSLA</option><option>PLTR</option></select></label></div>
        {source === 'futu' && <div className="source-caveat">Futu records include short opinions, questions, and price commentary. The trial does not provide author IDs or prove full community coverage. Text has not been assigned validated sentiment labels.</div>}
        <Events key={`${source}-${symbol}-${refresh}`} source={source} symbol={symbol} />
      </section>

      <section className="acceptance-panel" aria-labelledby="acceptance-title"><div><p className="eyebrow">THE FINISH LINE</p><h2 id="acceptance-title">Evidence before performance claims.</h2></div><p>The planned comparison uses equal starting capital, the same stock universe, risk limits, and execution assumptions. Neither a winning strategy nor a validated signal has been established.</p></section>
    </main>
    <footer className="lab-footer"><span>Quant.ai Signal Lab <span aria-hidden="true">·</span> 610 research project</span><a href={status?.plan_url ?? '/api/research/signal-lab/plan'} target="_blank" rel="noopener noreferrer">Read research plan <span aria-hidden="true">↗</span></a><span>Archived observations. Reproducible questions.</span></footer>
  </div>
}
