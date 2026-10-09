import React, { useEffect, useState } from 'react';
import { API_BASE } from '../config';
import './NewsMonitorPanel.css';

type Topic = 'elections' | 'markets';
type Item = {
  id: string;
  topic: Topic;
  publisher: string;
  title: string;
  content: string;
  url: string;
  published_at: string | null;
  discovered_at: string;
  priority: number;
};
type Source = {
  id: string;
  topic: Topic;
  label: string;
  last_success: string | null;
  status: 'ok' | 'error' | 'waiting';
  error: string | null;
};
type Summary = {
  relevance: 'high' | 'medium' | 'low' | 'unclear';
  event_type: string;
  summary: string;
  evidence_quote: string;
  race_hint: string | null;
  reason: string;
  source_excerpt_reviewed: true;
  model: string;
};
type SummaryStatus = { available: boolean; model: string; calls_today: number; failed_today: number; paused_until: string | null };

const dateLabel = (value: string | null) => value
  ? new Date(value).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
  : 'Time unavailable';

export const NewsMonitorPanel: React.FC<{ initialTopic?: Topic; electionsOnly?: boolean }> = ({ initialTopic = 'elections', electionsOnly = false }) => {
  const [selectedTopic, setTopic] = useState<Topic>(initialTopic);
  const topic: Topic = electionsOnly ? 'elections' : selectedTopic;
  const [items, setItems] = useState<Item[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState(false);
  const [summaries, setSummaries] = useState<Record<string, Summary>>({});
  const [summaryStatus, setSummaryStatus] = useState<SummaryStatus | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [itemsResponse, sourcesResponse, summaryResponse] = await Promise.all([
          fetch(`${API_BASE}/api/news/items?topic=${topic}&limit=100`),
          fetch(`${API_BASE}/api/news/sources`),
          topic === 'elections' ? fetch(`${API_BASE}/api/sig/triage`) : Promise.resolve(null),
        ]);
        if (!itemsResponse.ok || !sourcesResponse.ok || (summaryResponse && !summaryResponse.ok)) throw new Error('News service unavailable');
        const [itemData, sourceData, summaryData] = await Promise.all([
          itemsResponse.json(), sourcesResponse.json(), summaryResponse ? summaryResponse.json() : Promise.resolve(null),
        ]);
        if (active) {
          setItems(Array.isArray(itemData.items) ? itemData.items : []);
          setSources(Array.isArray(sourceData.sources) ? sourceData.sources : []);
          if (summaryData) {
            setSummaries(summaryData.results || {});
            setSummaryStatus(summaryData.status || null);
          }
          setError(false);
        }
      } catch {
        if (active) setError(true);
      }
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, 60_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [topic]);

  const visibleSources = sources.filter(source => source.topic === topic);
  const latest = visibleSources.reduce<string | null>((value, source) => {
    if (!source.last_success) return value;
    return !value || source.last_success > value ? source.last_success : value;
  }, null);
  const relevanceOrder = { high: 0, medium: 1, unclear: 2, low: 3 };
  const summarizedItems = items.filter(item => Boolean(summaries[item.id])).sort((a, b) => {
    const byRelevance = relevanceOrder[summaries[a.id].relevance] - relevanceOrder[summaries[b.id].relevance];
    return byRelevance || (b.published_at || b.discovered_at).localeCompare(a.published_at || a.discovered_at);
  });
  const intakeItems = items.filter(item => !summaries[item.id]);

  const renderStory = (item: Item) => <article className="news-monitor-item" key={item.id}>
    <div className="news-monitor-story">
      <a href={item.url} target="_blank" rel="noopener noreferrer">{item.title} ↗</a>
      <p>{item.publisher} · Published {dateLabel(item.published_at)}</p>
      {summaries[item.id]
        ? <div className="news-monitor-ai-result">
            <strong>{summaries[item.id].relevance} relevance · {summaries[item.id].event_type.replaceAll('_', ' ')}</strong>
            <p>{summaries[item.id].summary}</p>
            {summaries[item.id].race_hint && <small>Race hint: {summaries[item.id].race_hint}</small>}
            <p className="news-monitor-verify">Verify: {summaries[item.id].reason}</p>
          </div>
        : <p className="news-monitor-pending">
            {item.content
              ? item.priority >= 3 ? 'Source excerpt collected · NLP summary pending' : 'Source excerpt collected · Below the current NLP screening threshold'
              : 'Headline collected · This feed did not provide an article excerpt'}
          </p>}
    </div>
  </article>;

  return <section className="news-monitor" aria-label="Election news feed">
    <div className="news-monitor-header">
      <div><h2>NLP Briefs</h2><p>New election stories are deduplicated. NLP summarizes source-provided excerpts once; saved summaries stay linked to the original report.</p></div>
      {!electionsOnly && <div className="news-monitor-topics" role="group" aria-label="News topic">
        <button type="button" className={topic === 'elections' ? 'selected' : ''} onClick={() => setTopic('elections')}>Elections</button>
        <button type="button" className={topic === 'markets' ? 'selected' : ''} onClick={() => setTopic('markets')}>Markets</button>
      </div>}
    </div>
    <div className="news-monitor-health">
      <span>Last successful source check: {dateLabel(latest)}</span>
      {topic === 'elections' && <span className={`news-monitor-ai-status ${summaryStatus?.paused_until ? 'paused' : ''}`}>
        NLP: {summaryStatus?.available ? `${summaryStatus.model} · ${summaryStatus.calls_today} summaries today` : 'not configured'}
        {summaryStatus?.failed_today ? ` · ${summaryStatus.failed_today} failed` : ''}
        {summaryStatus?.paused_until ? ` · Paused until ${dateLabel(summaryStatus.paused_until)}` : ''}
      </span>}
      {visibleSources.map(source => <span key={source.id} className={`news-monitor-source ${source.status}`} title={source.error || undefined}>
        {source.label}: {source.status}
      </span>)}
    </div>
    {error && <p className="news-monitor-error" role="alert">The news service could not be reached. Saved articles may be temporarily unavailable.</p>}
    {!error && items.length === 0 && <p className="news-monitor-empty">No election stories collected yet. The collector checks public RSS feeds in the background.</p>}
    {!error && summarizedItems.length > 0 && <div className="news-monitor-list">{summarizedItems.map(renderStory)}</div>}
    {!error && summarizedItems.length === 0 && items.length > 0 && <p className="news-monitor-empty">Stories are collected. NLP briefs will appear when a source provides an excerpt and the item meets the screening threshold.</p>}
    {!error && intakeItems.length > 0 && <details className="news-monitor-intake">
      <summary>News intake · {intakeItems.length} stories not summarized</summary>
      <div className="news-monitor-list">{intakeItems.map(renderStory)}</div>
    </details>}
    <p className="news-monitor-footnote">Summaries use RSS excerpts only, not full article pages. Every result links to its original publisher; no probability or trade recommendation is generated.</p>
  </section>;
};
