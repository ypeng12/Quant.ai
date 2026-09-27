import React, { useEffect, useState } from 'react';
import { API_BASE } from '../config';
import './NewsMonitorPanel.css';

type Topic = 'elections' | 'markets';
type Item = {
  id: string;
  topic: Topic;
  publisher: string;
  title: string;
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
type Triage = {
  relevance: 'high' | 'medium' | 'low' | 'unclear';
  event_type: string;
  summary: string;
  evidence_quote: string;
  race_hint: string | null;
  reason: string;
  source_review_required: true;
  headline_only: true;
  market_mapping: 'pending';
  model: string;
};
type TriageStatus = { available: boolean; model: string; calls_today: number; failed_today: number; paused_until: string | null };

const dateLabel = (value: string | null) => value
  ? new Date(value).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
  : 'Time unavailable';

export const NewsMonitorPanel: React.FC<{ initialTopic?: Topic; electionsOnly?: boolean }> = ({ initialTopic = 'elections', electionsOnly = false }) => {
  const [selectedTopic, setTopic] = useState<Topic>(initialTopic);
  const topic: Topic = electionsOnly ? 'elections' : selectedTopic;
  const [items, setItems] = useState<Item[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState(false);
  const [triage, setTriage] = useState<Record<string, Triage>>({});
  const [triageStatus, setTriageStatus] = useState<TriageStatus | null>(null);
  const [triageBusy, setTriageBusy] = useState<string | null>(null);
  const [triageError, setTriageError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [itemsResponse, sourcesResponse] = await Promise.all([
          fetch(`${API_BASE}/api/news/items?topic=${topic}&limit=40`),
          fetch(`${API_BASE}/api/news/sources`),
        ]);
        if (!itemsResponse.ok || !sourcesResponse.ok) throw new Error('News service unavailable');
        const [itemData, sourceData] = await Promise.all([itemsResponse.json(), sourcesResponse.json()]);
        if (active) {
          setItems(Array.isArray(itemData.items) ? itemData.items : []);
          setSources(Array.isArray(sourceData.sources) ? sourceData.sources : []);
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

  useEffect(() => {
    if (topic !== 'elections') return;
    let active = true;
    const load = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/sig/triage`);
        if (!response.ok) return;
        const data = await response.json();
        if (active) {
          setTriage(data.results || {});
          setTriageStatus(data.status || null);
        }
      } catch { /* News remains available when AI triage is unavailable. */ }
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, 60_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [topic]);

  const analyze = async (id: string) => {
    setTriageBusy(id);
    setTriageError(null);
    try {
      const response = await fetch(`${API_BASE}/api/sig/triage/${id}`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'AI triage failed');
      setTriage(previous => ({ ...previous, [id]: data.result }));
      setTriageStatus(data.status);
    } catch (cause) {
      setTriageError(cause instanceof Error ? cause.message : 'AI triage failed');
    } finally { setTriageBusy(null); }
  };

  const visibleSources = sources.filter(source => source.topic === topic);
  const latest = visibleSources.reduce<string | null>((value, source) => {
    if (!source.last_success) return value;
    return !value || source.last_success > value ? source.last_success : value;
  }, null);

  return <section className="news-monitor" aria-label="News monitor">
    <div className="news-monitor-header">
      <div><h2>News Monitor</h2><p>Source headlines are collected automatically. High-priority election titles receive AI triage; no probabilities or trade signals are produced.</p></div>
      {!electionsOnly && <div className="news-monitor-topics" role="group" aria-label="News topic">
        <button type="button" className={topic === 'elections' ? 'selected' : ''} onClick={() => setTopic('elections')}>Elections</button>
        <button type="button" className={topic === 'markets' ? 'selected' : ''} onClick={() => setTopic('markets')}>Markets</button>
      </div>}
    </div>
    <div className="news-monitor-health">
      <span>Last successful source check: {dateLabel(latest)}</span>
      {visibleSources.map(source => <span key={source.id} className={`news-monitor-source ${source.status}`} title={source.error || undefined}>
        {source.label}: {source.status}
      </span>)}
    </div>
    {topic === 'elections' && <p className="news-monitor-ai-status">AI triage: {triageStatus?.available ? `${triageStatus.model} · ${triageStatus.calls_today} analyzed today` : 'unavailable'}{triageStatus?.failed_today ? ` · ${triageStatus.failed_today} failed` : ''}{triageStatus?.paused_until ? ` · Paused until ${dateLabel(triageStatus.paused_until)}` : ''} · High-priority headlines analyzed automatically · Headline only</p>}
    {triageError && topic === 'elections' && <p className="news-monitor-error" role="alert">{triageError}</p>}
    {error && <p className="news-monitor-error" role="alert">The news service could not be reached. Saved headlines may be temporarily unavailable.</p>}
    {!error && items.length === 0 && <p className="news-monitor-empty">No headlines collected yet. The collector checks sources in the background.</p>}
    {!error && items.length > 0 && <div className="news-monitor-list">{items.map(item =>
      <article className="news-monitor-item" key={item.id}>
        <div><a href={item.url} target="_blank" rel="noopener noreferrer">{item.title} ↗</a>
          <p>{item.publisher} · Published {dateLabel(item.published_at)} · Found {dateLabel(item.discovered_at)}</p>
        </div>
        {item.priority >= 3 && <span className="news-monitor-review">Review</span>}
        {topic === 'elections' && <div className="news-monitor-ai">
          {!triage[item.id] && <button type="button" onClick={() => void analyze(item.id)} disabled={!triageStatus?.available || Boolean(triageStatus.paused_until) || triageBusy !== null}>
            {triageBusy === item.id ? 'Analyzing…' : 'AI triage'}
          </button>}
          {triage[item.id] && <div className="news-monitor-ai-result">
            <strong>AI triage · {triage[item.id].relevance} relevance · {triage[item.id].event_type.replaceAll('_', ' ')}</strong>
            <p>{triage[item.id].summary}</p>
            <small>Headline evidence: “{triage[item.id].evidence_quote}”{triage[item.id].race_hint ? ` · Race hint: ${triage[item.id].race_hint}` : ''}</small>
            <p>{triage[item.id].reason}</p>
            <small>Verify original source · Market mapping pending · No probability estimate</small>
          </div>}
        </div>}
      </article>
    )}</div>}
    <p className="news-monitor-footnote">“Review” marks matching headline keywords. Verify the original article and market resolution rules before changing a forecast.</p>
  </section>;
};
