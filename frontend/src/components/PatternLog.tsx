// frontend/src/components/PatternLog.tsx

import React from 'react';

export interface PatternEvent {
  time: string;
  ticker: string;
  pattern: string;
  type: 'bullish' | 'bearish';
  price: number;
  desc: string;
}

interface PatternLogProps {
  patterns: PatternEvent[];
}

export const PatternLog: React.FC<PatternLogProps> = ({ patterns }) => {
  return (
    <div className="card" style={{ maxHeight: '350px', display: 'flex', flexDirection: 'column' }}>
      <h3 className="card-title" style={{ marginBottom: '10px' }}>K 线形态自动识别日志 (K-Line Pattern Recognition Log)</h3>
      
      <div style={{ 
        overflowY: 'auto', 
        flex: 1, 
        display: 'flex', 
        flexDirection: 'column', 
        gap: '8px', 
        paddingRight: '6px' 
      }}>
        {patterns.length === 0 ? (
          <p style={{ color: 'var(--color-text-secondary)', margin: '1rem 0 0 0', fontSize: '0.9rem' }}>
            回测时段内未识别到明显的标志性 K 线形态（如双底/双顶/锤子线等）。
          </p>
        ) : (
          patterns.map((item, idx) => {
            const isBullish = item.type === 'bullish';
            const badgeColor = isBullish ? 'var(--color-green)' : 'var(--color-red)';
            const bgBadgeColor = isBullish ? 'rgba(0, 200, 5, 0.12)' : 'rgba(255, 59, 48, 0.12)';
            
            return (
              <div 
                key={idx} 
                style={{
                  background: '#2c2c2e',
                  border: '1px solid var(--color-border)',
                  borderRadius: '6px',
                  padding: '8px 12px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ 
                      color: badgeColor, 
                      background: bgBadgeColor, 
                      padding: '2px 6px', 
                      borderRadius: '4px',
                      fontSize: '0.75rem',
                      fontWeight: 700 
                    }}>
                      {item.pattern}
                    </span>
                    <strong style={{ fontSize: '0.85rem' }}>{item.ticker} @ ${item.price.toFixed(2)}</strong>
                  </div>
                  <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>{item.time}</span>
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', lineHeight: '1.4' }}>
                  {item.desc}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
