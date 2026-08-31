// frontend/src/components/TradeComparisonPanel.tsx

import React from 'react';
import { API_BASE } from '../config';
import { IntradayKlineChart } from './IntradayKlineChart';

interface TradeComparisonPanelProps {
  watchlist: string[];
  activeTicker: string;
  onSelectTicker: (ticker: string) => void;
}

export function TradeComparisonPanel({ watchlist, activeTicker, onSelectTicker }: TradeComparisonPanelProps) {
  const [iframeKey, setIframeKey] = React.useState(Date.now());
  const [isRefreshing, setIsRefreshing] = React.useState(false);

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
        <div style={{ fontWeight: 800, color: '#38bdf8', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          📈 HRT ML 动态仿真与历史 K 线复盘大屏 (2-in-1 实时强刷模式)
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
        <IntradayKlineChart ticker={activeTicker || 'TSLA'} />
      </div>
      <iframe
        key={iframeKey}
        src={`${API_BASE}/charts/trade_comparison_dashboard.html?v=${iframeKey}`}
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
