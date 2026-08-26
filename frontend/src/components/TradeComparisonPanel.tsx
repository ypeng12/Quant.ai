// frontend/src/components/TradeComparisonPanel.tsx

import React from 'react';
import { API_BASE } from '../config';

interface TradeComparisonPanelProps {
  watchlist: string[];
  activeTicker: string;
  onSelectTicker: (ticker: string) => void;
}

export function TradeComparisonPanel({ watchlist, activeTicker, onSelectTicker }: TradeComparisonPanelProps) {
  return (
    <div style={{
      width: '100%',
      minHeight: '850px',
      borderRadius: '12px',
      overflow: 'hidden',
      border: '1px solid #e1e8ed',
      background: '#ffffff',
      boxShadow: '0 4px 12px rgba(0,0,0,0.05)'
    }}>
      <iframe
        src={`${API_BASE}/charts/trade_comparison_dashboard.html?v=${Date.now()}`}
        title="Trade Comparison Dashboard"
        style={{
          width: '100%',
          height: '850px',
          border: 'none',
          background: '#ffffff'
        }}
      />
    </div>
  );
}
