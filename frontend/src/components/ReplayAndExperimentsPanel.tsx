import React, { useState } from 'react';
import { SameDayReplayPanel } from './SameDayReplayPanel';
import { ExperimentCompare } from './ExperimentCompare';

interface ReplayAndExperimentsPanelProps {
  watchlist: string[];
  activeTicker: string;
  onSelectTicker: (ticker: string) => void;
}

export const ReplayAndExperimentsPanel: React.FC<ReplayAndExperimentsPanelProps> = ({
  watchlist,
  activeTicker,
  onSelectTicker
}) => {
  const [subTab, setSubTab] = useState<'replay' | 'experiments'>('replay');

  return (
    <div>
      {/* Sub Header Navigation Bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: '#09090b',
        padding: '10px 16px',
        borderRadius: '12px',
        border: '1px solid var(--color-border)',
        marginBottom: '1.5rem'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            onClick={() => setSubTab('replay')}
            style={{
              padding: '8px 18px',
              fontSize: '0.88rem',
              fontWeight: 800,
              background: subTab === 'replay' ? 'var(--color-green)' : 'transparent',
              color: subTab === 'replay' ? '#000000' : '#ffffff',
              borderRadius: '8px',
              border: subTab === 'replay' ? 'none' : '1px solid rgba(255,255,255,0.12)',
              cursor: 'pointer',
              transition: 'all 0.2s ease'
            }}
          >
            🎬 同天秒级历史复盘 (Intraday Replay)
          </button>

          <button
            onClick={() => setSubTab('experiments')}
            style={{
              padding: '8px 18px',
              fontSize: '0.88rem',
              fontWeight: 800,
              background: subTab === 'experiments' ? 'linear-gradient(135deg, #3b82f6, #1d4ed8)' : 'transparent',
              color: '#ffffff',
              borderRadius: '8px',
              border: subTab === 'experiments' ? 'none' : '1px solid rgba(59, 130, 246, 0.4)',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
              boxShadow: subTab === 'experiments' ? '0 0 12px rgba(59, 130, 246, 0.4)' : 'none'
            }}
          >
            🧪 策略回填与回撤评估仪器 (Experiment Compare)
          </button>
        </div>

        <div style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>
          {subTab === 'replay' ? '🔴 逐秒驱动多因子与 Signal 历史复盘' : '📊 策略不同风控参数与回撤矩阵对比'}
        </div>
      </div>

      {/* Render selected view */}
      {subTab === 'replay' ? (
        <SameDayReplayPanel 
          watchlist={watchlist} 
          activeTicker={activeTicker} 
          onSelectTicker={onSelectTicker} 
        />
      ) : (
        <ExperimentCompare />
      )}
    </div>
  );
};
