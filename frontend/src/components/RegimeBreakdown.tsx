// frontend/src/components/RegimeBreakdown.tsx

import React from 'react';

interface RegimeData {
  regime: string;
  total_pnl: number;
  trade_count: number;
  win_rate: number;
  wins: number;
  losses: number;
  commission: number;
}

interface RegimeDistribution {
  [key: string]: number;
}

interface RegimeBreakdownProps {
  breakdown: RegimeData[];
  distribution: RegimeDistribution;
}

const REGIME_LABELS: Record<string, { label: string; emoji: string; color: string }> = {
  'trend_up':        { label: 'Trend Up',         emoji: '📈', color: '#00c805' },
  'trend_down':      { label: 'Trend Down',       emoji: '📉', color: '#ff3b30' },
  'range_bound':     { label: 'Range Bound',      emoji: '↔️', color: '#f5a623' },
  'high_volatility': { label: 'High Volatility',  emoji: '⚡', color: '#af52de' },
  'unknown':         { label: 'Unknown',           emoji: '❓', color: '#8e8e93' },
};

export const RegimeBreakdown: React.FC<RegimeBreakdownProps> = ({ breakdown, distribution }) => {
  if (!breakdown || breakdown.length === 0) {
    return (
      <div className="card">
        <h3 className="card-title">🚦 Market Regime Performance</h3>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem' }}>
          No regime-specific trade data available for the current backtest.
        </p>
      </div>
    );
  }

  return (
    <div className="card regime-card">
      <h3 className="card-title">🚦 Market Regime Performance</h3>
      
      {/* Regime Distribution Bar */}
      {Object.keys(distribution).length > 0 && (
        <div className="regime-distribution">
          <div className="regime-bar">
            {Object.entries(distribution).map(([regime, pct]) => {
              const info = REGIME_LABELS[regime] || REGIME_LABELS['unknown'];
              return (
                <div
                  key={regime}
                  className="regime-bar-segment"
                  style={{
                    width: `${pct}%`,
                    backgroundColor: info.color,
                    opacity: 0.7
                  }}
                  title={`${info.label}: ${pct}%`}
                />
              );
            })}
          </div>
          <div className="regime-bar-labels">
            {Object.entries(distribution).map(([regime, pct]) => {
              const info = REGIME_LABELS[regime] || REGIME_LABELS['unknown'];
              return (
                <span key={regime} className="regime-bar-label" style={{ color: info.color }}>
                  {info.emoji} {info.label} {pct}%
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Regime Performance Table */}
      <div className="regime-table-wrapper">
        <table className="regime-table">
          <thead>
            <tr>
              <th>Regime</th>
              <th>Trades</th>
              <th>Win Rate</th>
              <th>PnL</th>
              <th>W / L</th>
              <th>Commission</th>
            </tr>
          </thead>
          <tbody>
            {breakdown.map((item, idx) => {
              const info = REGIME_LABELS[item.regime] || REGIME_LABELS['unknown'];
              const isPositive = item.total_pnl >= 0;
              return (
                <tr key={idx}>
                  <td>
                    <span className="regime-name" style={{ color: info.color }}>
                      {info.emoji} {info.label}
                    </span>
                  </td>
                  <td>{item.trade_count}</td>
                  <td>
                    <span style={{ color: item.win_rate >= 50 ? 'var(--color-green)' : 'var(--color-text-secondary)' }}>
                      {item.win_rate.toFixed(0)}%
                    </span>
                  </td>
                  <td>
                    <span style={{ color: isPositive ? 'var(--color-green)' : 'var(--color-red)', fontWeight: 700 }}>
                      {isPositive ? '+' : ''}${item.total_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </span>
                  </td>
                  <td>
                    <span style={{ color: 'var(--color-green)' }}>{item.wins}</span>
                    {' / '}
                    <span style={{ color: 'var(--color-red)' }}>{item.losses}</span>
                  </td>
                  <td style={{ color: 'var(--color-text-secondary)' }}>
                    ${item.commission.toFixed(2)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
