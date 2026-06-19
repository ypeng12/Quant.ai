// frontend/src/components/LedgerTable.tsx

import React from 'react';

export interface LedgerItem {
  timestamp: string;
  action: 'BUY' | 'SELL';
  ticker: string;
  shares: number;
  market_price: number;
  execution_price: number;
  commission: number;
  total_value: number;
  total_cost?: number;
  revenue?: number;
  realized_pnl?: number;
  cash_remaining: number;
}

interface LedgerTableProps {
  ledger: LedgerItem[];
  onRowClick?: (item: LedgerItem) => void;
}

export const LedgerTable: React.FC<LedgerTableProps> = ({ ledger, onRowClick }) => {
  const formatTime = (timeStr: string) => {
    // 简化时间显示，只保留 "YYYY-MM-DD HH:MM"
    try {
      const parts = timeStr.split(' ');
      if (parts.length >= 2) {
        return `${parts[0]} ${parts[1].substring(0, 5)}`;
      }
    } catch (e) {}
    return timeStr;
  };

  return (
    <div className="card" style={{ overflowX: 'auto' }}>
      <h3 className="card-title">交易流水账单 (Transaction Ledger)</h3>
      {ledger.length === 0 ? (
        <p style={{ color: 'var(--color-text-secondary)', margin: 0 }}>
          回测期间系统保持空仓防守，未触发交易信号。
        </p>
      ) : (
        <table className="ledger-table">
          <thead>
            <tr>
              <th>交易时间</th>
              <th>操作</th>
              <th>代码</th>
              <th>股数</th>
              <th>成交均价</th>
              <th>( 盘面价格 )</th>
              <th>交易手续费</th>
              <th style={{ textAlign: 'right' }}>净收益 PnL</th>
            </tr>
          </thead>
          <tbody>
            {[...ledger].reverse().map((item, index) => {
              const pnl = item.realized_pnl;
              const hasPnl = pnl !== undefined && item.action === 'SELL';
              const pnlColor = hasPnl ? (pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)') : 'inherit';
              const pnlText = hasPnl ? `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}` : '--';

              return (
                <tr 
                  key={index}
                  onClick={() => onRowClick && onRowClick(item)}
                  style={{ cursor: onRowClick ? 'pointer' : 'default' }}
                >
                  <td>{formatTime(item.timestamp)}</td>
                  <td>
                    <span className={`action-badge ${item.action.toLowerCase()}`}>
                      {item.action === 'BUY' ? 'BUY / 买入' : 'SELL / 平仓'}
                    </span>
                  </td>
                  <td style={{ fontWeight: 700 }}>{item.ticker}</td>
                  <td>{item.shares}</td>
                  <td>${item.execution_price.toFixed(2)}</td>
                  <td style={{ color: 'var(--color-text-secondary)', fontSize: '0.85rem' }}>
                    ${item.market_price.toFixed(2)}
                  </td>
                  <td style={{ color: 'var(--color-red)' }}>${item.commission.toFixed(2)}</td>
                  <td style={{ textAlign: 'right', fontWeight: 700, color: pnlColor }}>
                    {pnlText}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
};
