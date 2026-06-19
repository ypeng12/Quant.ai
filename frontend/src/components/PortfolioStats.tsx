// frontend/src/components/PortfolioStats.tsx

import React from 'react';

interface SummaryData {
  initial_cash: number;
  final_equity: number;
  net_pnl: number;
  pnl_pct: number;
  total_trades: number;
  round_trips: number;
  win_rate: number;
  commission: number;
  max_drawdown?: number;
  sharpe?: number;
  calmar?: number;
  cagr?: number;
  profit_factor?: number;
  gross_profit?: number;
  gross_loss?: number;
}

interface PortfolioStatsProps {
  summary: SummaryData;
}

export const PortfolioStats: React.FC<PortfolioStatsProps> = ({ summary }) => {
  const isUp = summary.net_pnl >= 0;
  const pnlColor = isUp ? 'var(--color-green)' : 'var(--color-red)';
  const pnlSign = isUp ? '+' : '';

  const sharpe = summary.sharpe ?? 0;
  const calmar = summary.calmar ?? 0;
  const cagr = summary.cagr ?? 0;
  const profitFactor = summary.profit_factor ?? 0;
  const maxDD = (summary.max_drawdown ?? 0) * 100;

  const sharpeColor = sharpe > 1 ? 'var(--color-green)' : sharpe > 0 ? '#f5a623' : 'var(--color-red)';
  const calmarColor = calmar > 1 ? 'var(--color-green)' : calmar > 0 ? '#f5a623' : 'var(--color-red)';
  const pfColor = profitFactor > 1.5 ? 'var(--color-green)' : profitFactor > 1 ? '#f5a623' : 'var(--color-red)';

  return (
    <div className="card">
      <h3 className="card-title">Performance Summary</h3>
      
      {/* Primary Metrics */}
      <div className="stats-grid">
        <div className="stat-box">
          <span className="stat-label">Initial Capital</span>
          <span className="stat-value">${summary.initial_cash.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}</span>
        </div>
        
        <div className="stat-box">
          <span className="stat-label">Final Equity</span>
          <span className="stat-value">${summary.final_equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>

        <div className="stat-box">
          <span className="stat-label">Net PnL</span>
          <span className="stat-value" style={{ color: pnlColor }}>
            {pnlSign}${summary.net_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({pnlSign}{summary.pnl_pct.toFixed(2)}%)
          </span>
        </div>

        <div className="stat-box">
          <span className="stat-label">Round Trips</span>
          <span className="stat-value">{summary.round_trips}</span>
        </div>

        <div className="stat-box">
          <span className="stat-label">Win Rate</span>
          <span className="stat-value" style={{ color: summary.win_rate >= 50 ? 'var(--color-green)' : 'inherit' }}>
            {summary.win_rate.toFixed(1)}%
          </span>
        </div>

        <div className="stat-box">
          <span className="stat-label">Commission Paid</span>
          <span className="stat-value" style={{ color: 'var(--color-red)' }}>
            ${summary.commission.toFixed(2)}
          </span>
        </div>
      </div>

      {/* Advanced Quant Metrics */}
      <div className="stats-divider"></div>
      <div className="stats-grid">
        <div className="stat-box">
          <span className="stat-label">CAGR</span>
          <span className="stat-value" style={{ color: cagr >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
            {cagr >= 0 ? '+' : ''}{cagr.toFixed(1)}%
          </span>
        </div>

        <div className="stat-box">
          <span className="stat-label">Sharpe Ratio</span>
          <span className="stat-value" style={{ color: sharpeColor }}>
            {sharpe.toFixed(2)}
          </span>
        </div>

        <div className="stat-box">
          <span className="stat-label">Calmar Ratio</span>
          <span className="stat-value" style={{ color: calmarColor }}>
            {calmar.toFixed(2)}
          </span>
        </div>

        <div className="stat-box">
          <span className="stat-label">Profit Factor</span>
          <span className="stat-value" style={{ color: pfColor }}>
            {profitFactor.toFixed(2)}
          </span>
        </div>

        <div className="stat-box">
          <span className="stat-label">Max Drawdown</span>
          <span className="stat-value" style={{ color: maxDD > 10 ? 'var(--color-red)' : '#f5a623' }}>
            {maxDD.toFixed(2)}%
          </span>
        </div>

        <div className="stat-box">
          <span className="stat-label">Profit / Loss</span>
          <span className="stat-value">
            <span style={{ color: 'var(--color-green)' }}>${(summary.gross_profit ?? 0).toFixed(0)}</span>
            {' / '}
            <span style={{ color: 'var(--color-red)' }}>${(summary.gross_loss ?? 0).toFixed(0)}</span>
          </span>
        </div>
      </div>
    </div>
  );
};

