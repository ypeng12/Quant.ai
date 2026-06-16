// frontend/src/components/ScannerPanel.tsx

import React, { useState, useEffect } from 'react';

export interface ScanResult {
  ticker: string;
  name: string;
  sector: string;
  price: number;
  rvol: number;
  atr_pct: number;
  gap_pct: number;
  volume_m: number;
  recommended: boolean;
  reason: string;
}

interface ScannerPanelProps {
  customTickers: string[];
  onSelectTicker: (ticker: string) => void;
}

export const ScannerPanel: React.FC<ScannerPanelProps> = ({ customTickers, onSelectTicker }) => {
  const [loading, setLoading] = useState<boolean>(false);
  const [results, setResults] = useState<ScanResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  const runScan = async () => {
    setLoading(true);
    setError(null);
    try {
      const symbolsParam = customTickers.join(',');
      const res = await fetch(`http://127.0.0.1:8000/api/scan?tickers=${symbolsParam}`);
      const json = await res.json();
      if (json.success) {
        setResults(json.results);
      } else {
        setError(json.error || '扫描出错');
      }
    } catch (e) {
      setError('无法连接量化扫描服务器');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    runScan();
  }, [customTickers]);

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <div>
          <h3 className="card-title" style={{ margin: 0 }}>AI 盘前交易选股器 (Pre-Market Day Trader Scanner)</h3>
          <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.8rem', margin: '4px 0 0 0' }}>
            根据相对成交量 (RVol &gt; 1.2)、波动率 (ATR% &gt; 1.5%) 筛选高确定性日内交易候选者
          </p>
        </div>
        <button 
          onClick={runScan}
          disabled={loading}
          style={{
            background: 'var(--color-green)',
            color: '#000000',
            border: 'none',
            padding: '8px 16px',
            borderRadius: '6px',
            fontWeight: 700,
            fontSize: '0.85rem',
            cursor: loading ? 'not-allowed' : 'pointer',
            opacity: loading ? 0.7 : 1,
            transition: 'all 0.2s'
          }}
        >
          {loading ? '正在扫描行情...' : '立即运行全市场扫描'}
        </button>
      </div>

      {error && (
        <div style={{ color: 'var(--color-red)', fontSize: '0.9rem', marginBottom: '1rem', background: 'rgba(255,59,48,0.1)', padding: '8px', borderRadius: '4px' }}>
          {error}
        </div>
      )}

      {loading && results.length === 0 ? (
        <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--color-text-secondary)' }}>
          正在调取 Yahoo Finance 日线指标并运行 ATR/RVol 选股公式，请稍候...
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="ledger-table" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th>代码</th>
                <th>公司名</th>
                <th>板块</th>
                <th>当前价</th>
                <th>相对量 (RVol)</th>
                <th>日波动率 (ATR%)</th>
                <th>跳空 (Gap%)</th>
                <th>日成交量</th>
                <th>AI 研判</th>
                <th style={{ textAlign: 'right' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row) => {
                const badgeColor = row.recommended ? 'var(--color-green)' : 'var(--color-text-secondary)';
                const badgeBg = row.recommended ? 'rgba(0, 200, 5, 0.12)' : 'rgba(255,255,255,0.05)';
                const borderHighlight = row.recommended ? '1px solid rgba(0, 200, 5, 0.2)' : 'none';

                return (
                  <tr key={row.ticker} style={{ background: row.recommended ? 'rgba(0, 200, 5, 0.02)' : 'transparent' }}>
                    <td style={{ fontWeight: 800, color: row.recommended ? 'var(--color-green)' : '#ffffff' }}>
                      {row.ticker}
                    </td>
                    <td>{row.name}</td>
                    <td style={{ color: 'var(--color-text-secondary)', fontSize: '0.85rem' }}>{row.sector.split(' ')[0]}</td>
                    <td>${row.price.toFixed(2)}</td>
                    <td style={{ fontWeight: 700, color: row.rvol > 1.5 ? 'var(--color-green)' : '#ffffff' }}>
                      {row.rvol.toFixed(2)}x
                    </td>
                    <td style={{ fontWeight: 700, color: row.atr_pct > 2.0 ? 'var(--color-green)' : '#ffffff' }}>
                      {row.atr_pct.toFixed(2)}%
                    </td>
                    <td style={{ 
                      color: row.gap_pct > 0 ? 'var(--color-green)' : row.gap_pct < 0 ? 'var(--color-red)' : 'inherit',
                      fontWeight: 600
                    }}>
                      {row.gap_pct > 0 ? '+' : ''}{row.gap_pct.toFixed(2)}%
                    </td>
                    <td>{row.volume_m.toFixed(1)}M 股</td>
                    <td>
                      <span style={{ 
                        color: badgeColor, 
                        background: badgeBg, 
                        padding: '2px 8px', 
                        borderRadius: '4px',
                        fontSize: '0.75rem',
                        fontWeight: 700,
                        border: borderHighlight
                      }}>
                        {row.recommended ? '★ 强烈推荐交易' : '不推荐交易'}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        onClick={() => onSelectTicker(row.ticker)}
                        style={{
                          background: '#1c1c1e',
                          color: '#ffffff',
                          border: '1px solid var(--color-border)',
                          padding: '4px 10px',
                          borderRadius: '4px',
                          fontSize: '0.8rem',
                          cursor: 'pointer',
                          fontWeight: 600,
                          transition: 'all 0.2s'
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.borderColor = 'var(--color-green)';
                          e.currentTarget.style.color = 'var(--color-green)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.borderColor = 'var(--color-border)';
                          e.currentTarget.style.color = '#ffffff';
                        }}
                      >
                        回测此股票
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
