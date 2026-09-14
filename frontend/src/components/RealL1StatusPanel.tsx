import React, { useEffect, useState } from 'react';
import { API_BASE } from '../config';

interface L1Status {
  success: boolean;
  status: 'complete' | 'unavailable';
  ticker: string;
  source?: string;
  market_depth?: string | null;
  events: number;
  quote_events?: number;
  trade_events?: number;
  last_event?: string;
  latest_quote?: { timestamp: string; bid_price: number; bid_size: number; ask_price: number; ask_size: number } | null;
  reason: string;
}

export const RealL1StatusPanel: React.FC = () => {
  const [ticker, setTicker] = useState('TSLA');
  const [data, setData] = useState<L1Status | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/orderbook/l1_status?ticker=${ticker}`, { cache: 'no-store' });
        const payload = await response.json();
        if (active) setData(payload);
      } catch {
        if (active) setData({ success: false, status: 'unavailable', ticker, events: 0, reason: 'Unable to read L1 capture status.' });
      }
    };
    load();
    const interval = window.setInterval(load, 5000);
    return () => { active = false; window.clearInterval(interval); };
  }, [ticker]);

  const quote = data?.latest_quote;
  const imbalance = quote ? (quote.bid_size - quote.ask_size) / Math.max(1, quote.bid_size + quote.ask_size) : null;
  const microprice = quote ? (quote.ask_price * quote.bid_size + quote.bid_price * quote.ask_size) / Math.max(1, quote.bid_size + quote.ask_size) : null;

  return <div style={{ background: '#0b0e14', color: '#e2e8f0', padding: 24, borderRadius: 12 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', borderBottom: '1px solid rgba(255,255,255,.1)', paddingBottom: 16 }}>
      <div>
        <h2 style={{ margin: 0, color: '#38bdf8', fontSize: '1.2rem' }}>真实 L1 报价与成交采集</h2>
        <p style={{ color: '#94a3b8', marginBottom: 0, fontSize: '.85rem' }}>仅显示已保存的 Alpaca WebSocket 数据；没有 L2 深度订阅时，不显示伪造多档盘口。</p>
      </div>
      <div>{['TSLA', 'NVDA', 'PLTR', 'SNDK'].map(symbol => <button key={symbol} onClick={() => setTicker(symbol)} style={{ marginLeft: 6, padding: '7px 12px', border: 0, borderRadius: 6, cursor: 'pointer', background: ticker === symbol ? '#0369a1' : '#1e293b', color: '#fff' }}>{symbol}</button>)}</div>
    </div>
    {data?.status === 'complete' && quote ? <div style={{ marginTop: 18, display: 'grid', gridTemplateColumns: 'repeat(4, minmax(130px, 1fr))', gap: 12 }}>
      <Metric label="真实买一" value={`$${quote.bid_price.toFixed(2)} × ${quote.bid_size}`} />
      <Metric label="真实卖一" value={`$${quote.ask_price.toFixed(2)} × ${quote.ask_size}`} />
      <Metric label="微价格" value={`$${microprice?.toFixed(4)}`} />
      <Metric label="买卖盘不平衡" value={`${((imbalance || 0) * 100).toFixed(1)}%`} />
      <Metric label="Quote 事件" value={String(data.quote_events)} />
      <Metric label="Trade 事件" value={String(data.trade_events)} />
      <Metric label="最近事件" value={data.last_event?.slice(11, 19) || '—'} />
      <Metric label="数据等级" value={`${data.market_depth} · ${data.source}`} />
    </div> : <div style={{ marginTop: 18, padding: 16, borderRadius: 8, background: '#1e293b', color: '#cbd5e1' }}>
      <strong>真实 L1 尚不可用</strong><p style={{ marginBottom: 0 }}>{data?.reason || '正在读取采集状态。'}</p>
      <code style={{ display: 'block', marginTop: 12, whiteSpace: 'pre-wrap', color: '#7dd3fc' }}>python3 scripts/capture_alpaca_l1.py --symbols SNDK TSLA PLTR NVDA --feed iex</code>
    </div>}
    <p style={{ marginTop: 18, color: '#94a3b8', fontSize: '.8rem' }}>L1 是真实最优买卖价与数量，适合计算价差、微价格、OFI 和成交方向；它不是十档 L2，也还没有被验证为可盈利 Alpha。</p>
  </div>;
};

function Metric({ label, value }: { label: string; value: string }) {
  return <div style={{ background: '#131b2e', padding: 12, borderRadius: 8 }}><div style={{ color: '#94a3b8', fontSize: '.75rem' }}>{label}</div><div style={{ marginTop: 4, color: '#f8fafc', fontWeight: 700 }}>{value}</div></div>;
}
