// frontend/src/components/ReplayAndExperimentsPanel.tsx

import React from 'react';
import { TradeComparisonPanel } from './TradeComparisonPanel';

interface ReplayAndExperimentsPanelProps {
  watchlist: string[];
  activeTicker: string;
  onSelectTicker: (ticker: string) => void;
}

export function ReplayAndExperimentsPanel({ watchlist, activeTicker, onSelectTicker }: ReplayAndExperimentsPanelProps) {
  return (
    <div style={{ width: '100%' }}>
      <TradeComparisonPanel
        watchlist={watchlist}
        activeTicker={activeTicker}
        onSelectTicker={onSelectTicker}
      />
    </div>
  );
}
