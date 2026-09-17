// frontend/src/components/TradeComparisonPanel.tsx

import React from 'react';
import { API_BASE } from '../config';
import { IntradayKlineChart } from './IntradayKlineChart';
import { PriceActionReplayChart } from './PriceActionReplayChart';

interface TradeComparisonPanelProps {
  watchlist: string[];
  activeTicker: string;
  onSelectTicker: (ticker: string) => void;
}

export function TradeComparisonPanel({ watchlist, activeTicker, onSelectTicker }: TradeComparisonPanelProps) {
  const [iframeKey, setIframeKey] = React.useState(Date.now());
  const [isRefreshing, setIsRefreshing] = React.useState(false);
  const [chartView, setChartView] = React.useState<'price' | 'classic'>('price');
  const iframeRef = React.useRef<HTMLIFrameElement>(null);
  const iframeQuery = new URLSearchParams({ v: String(iframeKey), ticker: activeTicker || 'TSLA' });

  React.useEffect(() => {
    const receiveSelection = (event: MessageEvent) => {
      if (event.origin !== new URL(API_BASE, window.location.href).origin || event.source !== iframeRef.current?.contentWindow) return;
      if (event.data?.type !== 'quant-replay-selection-change') return;
      if (typeof event.data.ticker === 'string' && /^[A-Z.]{1,10}$/.test(event.data.ticker)) onSelectTicker(event.data.ticker);
      // Research and broker archives can cover different dates. Keep each
      // source's date selector independent while synchronizing the stock.
    };
    window.addEventListener('message', receiveSelection);
    return () => window.removeEventListener('message', receiveSelection);
  }, [onSelectTicker]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await fetch(`${API_BASE}/charts/trade_comparison_dashboard.html?force_refresh=true&v=${Date.now()}`);
      setIframeKey(Date.now());
    } catch (e) {
      console.error(e);
    } finally {
      setIsRefreshing(false);
    }
  };

  return (
    <div style={{
      width: '100%',
      minHeight: '1450px',
      borderRadius: '12px',
      overflow: 'hidden',
      border: '1px solid rgba(255,255,255,0.08)',
      background: '#0b0e14',
      boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
      position: 'relative'
    }}>
      <div style={{
        padding: '12px 20px',
        background: '#131722',
        borderBottom: '1px solid rgba(255,255,255,0.08)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div style={{ fontWeight: 800, color: '#38bdf8', fontSize: '15px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          📈 价格走势与买卖点复盘 · 研究模拟 / 券商成交
        </div>
        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          style={{
            padding: '6px 14px',
            background: isRefreshing ? '#64748b' : 'linear-gradient(135deg, #0284c7, #0369a1)',
            color: '#ffffff',
            border: 'none',
            borderRadius: '6px',
            fontWeight: 700,
            fontSize: '12px',
            cursor: isRefreshing ? 'not-allowed' : 'pointer',
            transition: 'all 0.2s'
          }}
        >
          {isRefreshing ? '🔄 正在算图...' : '🔄 重新算图刷新'}
        </button>
      </div>
      <div style={{ padding: '16px' }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          {([{ value: 'price', label: '📈 Price, Trades & P&L' }, { value: 'classic', label: '📊 Rule Signals & Candlesticks' }] as const).map(view => <button
            key={view.value} onClick={() => setChartView(view.value)} aria-pressed={chartView === view.value}
            style={{ padding: '8px 12px', borderRadius: 7, border: `1px solid ${chartView === view.value ? '#288bb1' : '#2b394d'}`, background: chartView === view.value ? '#12364c' : '#121d2b', color: chartView === view.value ? '#7dd3fc' : '#94a3b8', fontWeight: 700, cursor: 'pointer' }}
          >{view.label}</button>)}
        </div>
        {chartView === 'price' ? <PriceActionReplayChart ticker={activeTicker || 'TSLA'} watchlist={watchlist} onSelectTicker={onSelectTicker} refreshKey={iframeKey} /> : <IntradayKlineChart ticker={activeTicker || 'TSLA'} />}
      </div>
      <div style={{ padding: '4px 22px 12px', color: '#94a3b8', fontSize: 12 }}>
        下方 Dynamic Replay 使用券商归档行情与成交，日期在下方独立选择。
      </div>
      <iframe
        ref={iframeRef}
        key={iframeKey}
        src={`${API_BASE}/charts/trade_comparison_dashboard.html?${iframeQuery}`}
        title="Trade Comparison Dashboard"
        style={{
          width: '100%',
          height: '1400px',
          border: 'none',
          background: '#0b0e14'
        }}
      />
    </div>
  );
}
