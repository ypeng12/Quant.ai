import React from 'react';
import { NewsMonitorPanel } from './NewsMonitorPanel';
import './ElectionNewsPanel.css';

export const ElectionNewsPanel: React.FC = () => <main className="election-news-page">
  <header className="election-news-hero">
    <div className="election-news-kicker">QUANT.AI / U.S. MIDTERMS 2026</div>
    <h1>Election News</h1>
    <p>Collect election reporting, summarize source-provided excerpts with NLP, and keep every brief linked to its original source.</p>
    <a href="https://sig.thesuper.market/markets?tournament=midterm-elections" target="_blank" rel="noopener noreferrer">Browse SIG election markets ↗</a>
  </header>
  <NewsMonitorPanel initialTopic="elections" electionsOnly />
</main>;
