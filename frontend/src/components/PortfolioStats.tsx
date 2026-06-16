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
}

interface PortfolioStatsProps {
  summary: SummaryData;
}

export const PortfolioStats: React.FC<PortfolioStatsProps> = ({ summary }) => {
  const isUp = summary.net_pnl >= 0;
  const pnlColor = isUp ? 'var(--color-green)' : 'var(--color-red)';
  const pnlSign = isUp ? '+' : '';

  return (
    <div className="card">
      <h3 className="card-title">回测业绩统计 (Performance Summary)</h3>
      <div className="stats-grid">
        <div className="stat-box">
          <span className="stat-label">初始账户本金</span>
          <span className="stat-value">${summary.initial_cash.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        
        <div className="stat-box">
          <span className="stat-label">期末账户总值</span>
          <span className="stat-value">${summary.final_equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>

        <div className="stat-box">
          <span className="stat-label">累计净收益</span>
          <span className="stat-value" style={{ color: pnlColor }}>
            {pnlSign}${summary.net_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({pnlSign}{summary.pnl_pct.toFixed(2)}%)
          </span>
        </div>

        <div className="stat-box">
          <span className="stat-label">完整交易笔数</span>
          <span className="stat-value">{summary.round_trips} 次</span>
        </div>

        <div className="stat-box">
          <span className="stat-label">系统实战胜率</span>
          <span className="stat-value" style={{ color: summary.win_rate >= 50 ? 'var(--color-green)' : 'inherit' }}>
            {summary.win_rate.toFixed(1)}%
          </span>
        </div>

        <div className="stat-box">
          <span className="stat-label">交易佣金损耗</span>
          <span className="stat-value" style={{ color: 'var(--color-red)' }}>
            ${summary.commission.toFixed(2)}
          </span>
        </div>
      </div>
    </div>
  );
};
