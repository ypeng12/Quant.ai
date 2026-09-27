import React, { useMemo, useState } from 'react';
import { NewsMonitorPanel } from './NewsMonitorPanel';
import './PredictionsCupPanel.css';

type Idea = { id: string; market: string; url: string; side: 'YES' | 'NO'; marketPrice: number; fairPrice: number; stake: number; thesis: string };
const KEY = 'quant-predictions-cup-ideas-v1';
const isMarketUrl = (value: string) => /^https:\/\/sig\.thesuper\.market\/markets\//.test(value.trim());
const isIdea = (value: unknown): value is Idea => {
  if (!value || typeof value !== 'object') return false;
  const idea = value as Partial<Idea>;
  return typeof idea.id === 'string' && typeof idea.market === 'string'
    && typeof idea.url === 'string' && (!idea.url || isMarketUrl(idea.url))
    && (idea.side === 'YES' || idea.side === 'NO')
    && typeof idea.marketPrice === 'number' && Number.isFinite(idea.marketPrice)
    && idea.marketPrice > 0 && idea.marketPrice < 1
    && typeof idea.fairPrice === 'number' && Number.isFinite(idea.fairPrice)
    && idea.fairPrice >= 0 && idea.fairPrice <= 1
    && typeof idea.stake === 'number' && Number.isFinite(idea.stake)
    && idea.stake > 0 && idea.stake <= 100000
    && typeof idea.thesis === 'string';
};
const initialIdeas = (): Idea[] => {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(KEY) || '[]');
    return Array.isArray(saved) ? saved.filter(isIdea) : [];
  } catch { return []; }
};
const clamp = (n: number, low: number, high: number) => Math.min(high, Math.max(low, n));
const fmt = (n: number) => new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(n);

export const PredictionsCupPanel: React.FC = () => {
  const [ideas, setIdeas] = useState<Idea[]>(initialIdeas);
  const [market, setMarket] = useState('');
  const [url, setUrl] = useState('');
  const [side, setSide] = useState<'YES' | 'NO'>('YES');
  const [marketPrice, setMarketPrice] = useState('50');
  const [fairPrice, setFairPrice] = useState('60');
  const [stake, setStake] = useState('1000');
  const [thesis, setThesis] = useState('');
  const [storageError, setStorageError] = useState(false);
  const price = Number(marketPrice) / 100;
  const fair = Number(fairPrice) / 100;
  const budget = Number(stake);
  const valid = Boolean(market.trim()) && [marketPrice, fairPrice, stake].every(value => value.trim() !== '') && Number.isFinite(price) && Number.isFinite(fair) && Number.isFinite(budget) && price > 0 && price < 1 && fair >= 0 && fair <= 1 && budget > 0 && budget <= 100000 && (!url.trim() || isMarketUrl(url));
  const edge = fair - price;
  const expected = valid ? budget * (fair / price - 1) : 0;
  const shares = valid ? budget / price : 0;
  const kelly = valid ? clamp((fair - price) / (1 - price), 0, 1) : 0;
  const totalStake = useMemo(() => ideas.reduce((sum, idea) => sum + idea.stake, 0), [ideas]);
  const save = (next: Idea[]) => {
    setIdeas(next);
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
      setStorageError(false);
    } catch {
      setStorageError(true);
    }
  };
  const addIdea = (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    save([{ id: crypto.randomUUID(), market: market.trim(), url: url.trim(), side, marketPrice: price, fairPrice: fair, stake: budget, thesis: thesis.trim() }, ...ideas]);
    setMarket(''); setUrl(''); setThesis('');
  };
  return <section className="cup">
    <div className="cup-hero">
      <div><div className="cup-eyebrow">QUANT.AI / PREDICTION RESEARCH</div><h1>🏆 SIG Predictions Cup Research Desk</h1><p>Record your research on the 2026 U.S. midterm election markets and estimate outcomes from your own inputs. Live market data and model forecasts are not connected.</p></div>
      <a className="cup-primary" href="https://sig.thesuper.market/markets?tournament=midterm-elections" target="_blank" rel="noopener noreferrer">Browse Official Markets ↗</a>
    </div>
    <div className="cup-stats"><div><span>Competition Dates</span><strong>Oct 1–Nov 4</strong><small>2026 · Opens and closes at noon ET</small></div><div><span>Starting Balance</span><strong>100,000</strong><small>SUSQies · Virtual competition currency</small></div><div><span>Planned Allocation</span><strong>{fmt(totalStake)}</strong><small>Research notes · No orders placed</small></div><div><span>Unallocated Budget</span><strong>{fmt(Math.max(0, 100000 - totalStake))}</strong><small>Based on the starting balance</small></div></div>
    <div className="cup-grid"><form className="cup-card" onSubmit={addIdea}><h2>Build a Market Thesis</h2><p>Copy a question and link from an official market. Enter the price and your probability estimate for the selected outcome.</p><label>Market Question<input value={market} onChange={e => setMarket(e.target.value)} placeholder="e.g., Will the Republican Party win control of the Senate?" required /></label><label>Official Market URL (optional)<input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://sig.thesuper.market/markets/..." /></label><div className="cup-form-row"><label>Outcome<select value={side} onChange={e => setSide(e.target.value as 'YES' | 'NO')}><option>YES</option><option>NO</option></select></label><label>Entry Price %<input type="number" min="0.01" max="99.99" step="0.01" value={marketPrice} onChange={e => setMarketPrice(e.target.value)} required /></label><label>Your Probability %<input type="number" min="0" max="100" step="0.01" value={fairPrice} onChange={e => setFairPrice(e.target.value)} required /></label></div><label>Planned Stake (SUSQies)<input type="number" min="1" max="100000" step="1" value={stake} onChange={e => setStake(e.target.value)} required /></label><label>Research Notes<textarea value={thesis} onChange={e => setThesis(e.target.value)} placeholder="Record your sources, their dates, and the main risks so you can review this decision later." rows={3} /></label><button className="cup-primary" type="submit" disabled={!valid}>Save Research Note</button>{url.trim() && !isMarketUrl(url) && <small className="cup-error">Enter a link to an official market page.</small>}</form>
    <div className="cup-card cup-preview"><h2>Manual Trade Estimates</h2><p>Calculated from your inputs, including your own probability estimate. Actual fills depend on available liquidity and the prices in the order book.</p><div className="cup-result"><span>Probability Edge</span><strong className={edge > 0 ? 'positive' : 'negative'}>{valid ? `${edge >= 0 ? '+' : ''}${(edge * 100).toFixed(1)} pp` : '—'}</strong></div><div className="cup-result"><span>Expected Profit (before costs)</span><strong className={expected > 0 ? 'positive' : 'negative'}>{valid ? `${expected >= 0 ? '+' : ''}${fmt(expected)} SUSQies` : '—'}</strong></div><div className="cup-result"><span>Estimated Shares</span><strong>{valid ? fmt(shares) : '—'}</strong></div><div className="cup-result"><span>Net Profit if Correct</span><strong>{valid ? `+${fmt(shares - budget)}` : '—'}</strong></div><div className="cup-result"><span>Loss if Incorrect</span><strong>{valid ? `−${fmt(budget)}` : '—'}</strong></div><div className="cup-result"><span>Theoretical Full Kelly Fraction</span><strong>{valid ? `${(kelly * 100).toFixed(1)}%` : '—'}</strong></div><div className="cup-note">These illustrative estimates assume a winning share pays 1 SUSQie and exclude trading costs. Full Kelly is a theoretical fraction for a single position, assumes your probability estimate is accurate, and ignores correlated positions and tournament ranking. It is not a recommended allocation.</div><a href="https://sig.thesuper.market/docs/markets-and-trading" target="_blank" rel="noopener noreferrer">Read the Official Trading Guide ↗</a></div></div>
    <div className="cup-card cup-ideas"><div className="cup-ideas-head"><div><h2>Research Watchlist</h2><p>Saved in this browser. Prices and probability estimates do not update automatically.</p></div><a href="https://predictionscup.com/rules/" target="_blank" rel="noopener noreferrer">Competition Rules ↗</a></div>{ideas.length === 0 ? <div className="cup-empty">No research notes yet. Choose an official market and record your probability estimate.</div> : <div className="cup-list">{ideas.map(idea => <article key={idea.id} className="cup-idea"><div><strong>{idea.market}</strong><div className="cup-meta">{idea.side} · Entry {(idea.marketPrice * 100).toFixed(1)}% · Your estimate {(idea.fairPrice * 100).toFixed(1)}% · Stake {fmt(idea.stake)} SUSQies</div>{idea.thesis && <p>{idea.thesis}</p>}</div><div className="cup-actions"><span className={idea.fairPrice > idea.marketPrice ? 'positive' : 'negative'}>{((idea.fairPrice - idea.marketPrice) * 100).toFixed(1)}pp</span>{idea.url && <a href={idea.url} target="_blank" rel="noopener noreferrer">Market ↗</a>}<button type="button" onClick={() => save(ideas.filter(x => x.id !== idea.id))}>Delete</button></div></article>)}</div>}</div>
    <NewsMonitorPanel initialTopic="elections" electionsOnly />
    {storageError && <p className="cup-error" role="alert">Browser storage is unavailable. Your changes are available for this session but may be lost when you reload.</p>}
    <p className="cup-footer">This desk supports independent research and planning. It is not connected to your competition account and does not submit orders. Check each market’s resolution criteria and current prices before trading.</p>
  </section>;
};
