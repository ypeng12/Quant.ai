// frontend/src/components/TradeComparisonPanel.tsx

import React from 'react';
import { API_BASE } from '../config';

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
      minHeight: '850px',
      borderRadius: '12px',
      overflow: 'hidden',
      border: '1px solid #e1e8ed',
      background: '#ffffff',
      boxShadow: '0 4px 12px rgba(0,0,0,0.05)',
      position: 'relative'
    }}>
      <div style={{
        padding: '12px 20px',
        background: '#f8f9fa',
        borderBottom: '1px solid #e1e8ed',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div style={{ fontWeight: 700, color: '#0f1419', fontSize: '14px' }}>
          📈 ML 复盘打点图表 (实时强刷模式)
        </div>
        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          style={{
            padding: '6px 14px',
            background: isRefreshing ? '#cfd9de' : '#1d9bf0',
            color: '#ffffff',
            border: 'none',
            borderRadius: '16px',
            fontWeight: 600,
            fontSize: '12px',
            cursor: isRefreshing ? 'not-allowed' : 'pointer',
            transition: 'all 0.2s'
          }}
        >
          {isRefreshing ? '🔄 重新算图中...' : '🔄 重新生成最新 K 线复盘'}
        </button>
      </div>
      <iframe
        key={iframeKey}
        src={`${API_BASE}/charts/trade_comparison_dashboard.html?v=${iframeKey}`}
        title="Trade Comparison Dashboard"
        style={{
          width: '100%',
          height: '800px',
          border: 'none',
          background: '#ffffff'
        }}
      />
    </div>
  );
}
