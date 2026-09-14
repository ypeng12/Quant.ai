// frontend/src/components/InstitutionalQuantDashboard.tsx
import React, { useState } from 'react';
import { RealL1StatusPanel } from './RealL1StatusPanel';

interface LOBLevel {
  level: number;
  bidPrice: number;
  bidSize: number;
  askPrice: number;
  askSize: number;
}

export const InstitutionalQuantDashboard: React.FC = () => {
  const [ticker, setTicker] = useState<string>('TSLA');
  const lobLevels: LOBLevel[] = [];
  const featureWeights = [
    { name: 'Microprice Velocity (微观价格速度)', color: '#38bdf8' },
    { name: 'RVOL (相对成交量强弱)', color: '#22c55e' },
    { name: 'OFI (订单流买卖盘不平衡度)', color: '#f59e0b' },
    { name: 'Bid-Ask Spread Ratio (买卖价差比)', color: '#a855f7' },
    { name: 'VPIN (知情交易毒性指标)', color: '#ef4444' }
  ];

  return (
    <div style={{ background: '#0b0e14', color: '#e2e8f0', padding: '24px', borderRadius: '12px', fontFamily: 'Inter, system-ui, sans-serif' }}>
      {/* Header Banner */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '16px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.4rem', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span>🏛️ L2 DOM 盘口 & LightGBM 特征诊断 · 概念演示</span>
          </h2>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.85rem' }}>
            当前没有真实 L2 数据与经验证的 LightGBM 产物；下方保留真实 L1 采集状态
          </p>
        </div>

        {/* Ticker Selector */}
        <div style={{ display: 'flex', gap: '8px' }}>
          {['TSLA', 'NVDA', 'PLTR', 'SNDK'].map((t) => (
            <button
              key={t}
              onClick={() => setTicker(t)}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: 'none',
                fontWeight: 700,
                cursor: 'pointer',
                background: ticker === t ? 'linear-gradient(135deg, #0284c7, #0369a1)' : '#1e293b',
                color: '#fff'
              }}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Grid Layout: DOM (Left) + ML Feature Importance & C++ Profiler (Right) */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '20px' }}>
        {/* Left Column: L2 Order Book Depth of Market (DOM) */}
        <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(56, 189, 248, 0.2)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h3 style={{ margin: 0, fontSize: '1.05rem', color: '#f59e0b' }}>
              📊 L2 Order Book 深度买卖盘瀑布 (DOM)
            </h3>
            <span style={{ fontSize: '0.8rem', color: '#10b981', fontWeight: 700 }}>
              加权微观价 (Microprice): —
            </span>
          </div>

          {/* DOM Table */}
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
            <thead>
              <tr style={{ background: '#0f172a', color: '#94a3b8', textAlign: 'center' }}>
                <th style={{ padding: '8px' }}>买盘挂单量 (Bid Size)</th>
                <th style={{ padding: '8px' }}>买价 (Bid Price)</th>
                <th style={{ padding: '8px' }}>档位</th>
                <th style={{ padding: '8px' }}>卖价 (Ask Price)</th>
                <th style={{ padding: '8px' }}>卖盘挂单量 (Ask Size)</th>
              </tr>
            </thead>
            <tbody>
              {lobLevels.map((l) => (
                <tr key={l.level} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', textAlign: 'center' }}>
                  <td style={{ padding: '8px', color: '#22c55e', fontWeight: 700 }}>
                    <div style={{ background: `linear-gradient(90deg, rgba(34,197,94,0.15) ${Math.min(100, (l.bidSize/6000)*100)}%, transparent 0%)`, padding: '4px', borderRadius: '4px' }}>
                      {l.bidSize.toLocaleString()} 股
                    </div>
                  </td>
                  <td style={{ color: '#22c55e', fontWeight: 700 }}>${l.bidPrice.toFixed(2)}</td>
                  <td style={{ color: '#64748b', fontSize: '0.75rem' }}>L{l.level}</td>
                  <td style={{ color: '#ef4444', fontWeight: 700 }}>${l.askPrice.toFixed(2)}</td>
                  <td style={{ padding: '8px', color: '#ef4444', fontWeight: 700 }}>
                    <div style={{ background: `linear-gradient(270deg, rgba(239,68,68,0.15) ${Math.min(100, (l.askSize/6000)*100)}%, transparent 0%)`, padding: '4px', borderRadius: '4px' }}>
                      {l.askSize.toLocaleString()} 股
                    </div>
                  </td>
                </tr>
              ))}
              {!lobLevels.length && <tr><td colSpan={5} style={{ padding: '24px', color: '#94a3b8', textAlign: 'center' }}>未连接 L2 数据源，无法显示五档挂单。</td></tr>}
            </tbody>
          </table>

          {/* Volume Imbalance Bar */}
          <div style={{ marginTop: '16px', background: '#0f172a', padding: '12px', borderRadius: '6px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#cbd5e1', marginBottom: '6px' }}>
              <span>买盘总挂单: <strong>—</strong></span>
              <span>卖盘总挂单: <strong>—</strong></span>
            </div>
            <div style={{ height: '8px', background: '#ef4444', borderRadius: '4px', overflow: 'hidden', display: 'flex' }}>
              <div style={{ width: '0%', background: '#22c55e' }} />
            </div>
          </div>
        </div>

        {/* Right Column: LightGBM Feature Importance & C++ Low-Latency Profiler */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* LightGBM Feature Importance Ranking */}
          <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(56, 189, 248, 0.2)' }}>
            <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#38bdf8' }}>
              🤖 LightGBM 特征重要性排行榜 (Gain %)
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {featureWeights.map((f) => (
                <div key={f.name}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', color: '#cbd5e1', marginBottom: '4px' }}>
                    <span>{f.name}</span>
                    <strong style={{ color: f.color }}>—</strong>
                  </div>
                  <div style={{ height: '6px', background: '#0f172a', borderRadius: '3px', overflow: 'hidden' }}>
                    <div style={{ width: '0%', background: f.color, height: '100%', borderRadius: '3px' }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* C++ Native Low-Latency Profiler Diagnostics */}
          <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
            <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#10b981', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>⚡ C++ Native Low-Latency Profiler</span>
              <span style={{ fontSize: '0.75rem', background: '#334155', color: '#cbd5e1', padding: '2px 8px', borderRadius: '4px' }}>未运行基准测试</span>
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px', textAlign: 'center' }}>
              <div style={{ background: '#0f172a', padding: '10px', borderRadius: '6px' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.75rem' }}>ITCH Struct Parse</div>
                <div style={{ fontSize: '1.1rem', color: '#38bdf8', fontWeight: 800, marginTop: '2px' }}>—</div>
              </div>
              <div style={{ background: '#0f172a', padding: '10px', borderRadius: '6px' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.75rem' }}>SPSC RingBuffer</div>
                <div style={{ fontSize: '1.1rem', color: '#10b981', fontWeight: 800, marginTop: '2px' }}>—</div>
              </div>
              <div style={{ background: '#0f172a', padding: '10px', borderRadius: '6px' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.75rem' }}>SHM Zero-Copy IPC</div>
                <div style={{ fontSize: '1.1rem', color: '#f59e0b', fontWeight: 800, marginTop: '2px' }}>—</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div style={{ marginTop: 20 }}><RealL1StatusPanel /></div>
    </div>
  );
};
