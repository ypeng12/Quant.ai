// frontend/src/components/CompanyInfoCard.tsx

import React from 'react';

interface CompanyInfo {
  name: string;
  sector: string;
  industry: string;
  market_cap: number;
  description: string;
}

interface CompanyInfoCardProps {
  ticker: string;
  info: CompanyInfo | null;
  loading: boolean;
}

export const CompanyInfoCard: React.FC<CompanyInfoCardProps> = ({ ticker, info, loading }) => {
  if (loading) {
    return (
      <div className="card" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '120px' }}>
        <span style={{ color: 'var(--color-text-secondary)' }}>正在加载 {ticker} 公司档案数据...</span>
      </div>
    );
  }

  if (!info) {
    return (
      <div className="card">
        <h3 className="card-title">公司档案：{ticker}</h3>
        <p style={{ color: 'var(--color-text-secondary)', margin: 0 }}>暂无该公司档案信息。</p>
      </div>
    );
  }

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
        <div>
          <h2 style={{ margin: '0 0 4px 0', fontSize: '1.4rem', color: '#ffffff' }}>{info.name}</h2>
          <span style={{ 
            background: 'rgba(255,255,255,0.08)', 
            padding: '2px 8px', 
            borderRadius: '4px', 
            fontSize: '0.8rem', 
            fontWeight: 700, 
            color: 'var(--color-green)' 
          }}>
            {ticker}
          </span>
        </div>
        <div style={{ textAlign: 'right' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', display: 'block' }}>总估值 (Market Cap)</span>
          <strong style={{ fontSize: '1.1rem', color: '#ffffff' }}>
            {info.market_cap > 0 ? `$${(info.market_cap / 1e9).toLocaleString(undefined, { maximumFractionDigits: 1 })}B` : '估算中'}
          </strong>
        </div>
      </div>

      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: '1fr 1fr', 
        gap: '12px', 
        padding: '10px 0', 
        borderTop: '1px solid var(--color-border)', 
        borderBottom: '1px solid var(--color-border)',
        fontSize: '0.85rem',
        marginBottom: '0.75rem'
      }}>
        <div>
          <span style={{ color: 'var(--color-text-secondary)', display: 'block' }}>板块 (Sector)</span>
          <span style={{ color: '#ffffff', fontWeight: 600 }}>{info.sector}</span>
        </div>
        <div>
          <span style={{ color: 'var(--color-text-secondary)', display: 'block' }}>细分行业 (Industry)</span>
          <span style={{ color: '#ffffff', fontWeight: 600 }}>{info.industry}</span>
        </div>
      </div>

      <div style={{ fontSize: '0.85rem', lineHeight: '1.5', color: 'var(--color-text-secondary)' }}>
        <strong style={{ color: '#ffffff', display: 'block', marginBottom: '4px' }}>公司简介：</strong>
        {info.description}
      </div>
    </div>
  );
};
