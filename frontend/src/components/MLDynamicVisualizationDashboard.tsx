// frontend/src/components/MLDynamicVisualizationDashboard.tsx
import React, { useState, useEffect } from 'react';

interface MLFeature {
  name: string;
  weight: number;
  color: string;
  val: number;
}

export const MLDynamicVisualizationDashboard: React.FC = () => {
  const [ticker, setTicker] = useState<string>('TSLA');
  const [pWin, setPWin] = useState<number>(0.684);
  const [hmmState, setHmmState] = useState<string>('BULL_TREND');
  const [hmmProbs, setHmmProbs] = useState({ BULL: 0.72, RANGE: 0.18, PANIC: 0.05, BEAR: 0.05 });
  const [leadLagCorr, setLeadLagCorr] = useState<number>(0.84);
  const [leadLagDelta, setLeadLagDelta] = useState<number>(4.8);

  // Dynamic animation updates every 1000ms
  useEffect(() => {
    const interval = setInterval(() => {
      // Simulate live LightGBM predicted probability updates
      const deltaP = (Math.random() - 0.48) * 0.03;
      setPWin((prev) => Math.min(0.95, Math.max(0.20, Number((prev + deltaP).toFixed(3)))));

      // Simulate HMM State Regime probabilities
      const bull = Math.min(0.90, Math.max(0.10, Number((0.65 + (Math.random() - 0.5) * 0.15).toFixed(2))));
      const range = Number((1.0 - bull - 0.10).toFixed(2));
      setHmmProbs({ BULL: bull, RANGE: Math.max(0.05, range), PANIC: 0.05, BEAR: 0.05 });

      // Lead-Lag Arbitrage pulse update
      setLeadLagCorr(Number((0.80 + Math.random() * 0.15).toFixed(2)));
      setLeadLagDelta(Number((3.0 + Math.random() * 4.0).toFixed(1)));
    }, 1200);

    return () => clearInterval(interval);
  }, []);

  const features: MLFeature[] = [
    { name: 'Microprice Velocity (微观价格速度)', weight: 33.67, color: '#38bdf8', val: 0.14 },
    { name: 'RVOL (相对成交量强弱)', weight: 30.97, color: '#22c55e', val: 2.45 },
    { name: 'OFI (订单流买卖盘不平衡度)', weight: 28.41, color: '#f59e0b', val: 1.25 },
    { name: 'Spread Ratio (买卖价差比)', weight: 5.75, color: '#a855f7', val: 0.0004 },
    { name: 'VPIN (知情交易毒性指标)', weight: 1.19, color: '#ef4444', val: 0.12 }
  ];

  return (
    <div style={{ background: '#090d16', color: '#e2e8f0', padding: '24px', borderRadius: '12px', fontFamily: 'Inter, system-ui, sans-serif', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
      {/* Dashboard Title & Ticker Switcher */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '16px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.4rem', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span>🎬 Quant.ai 全量 ML 模型动态实时诊断大屏</span>
            <span style={{ fontSize: '0.75rem', background: '#0284c7', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontWeight: 800 }}>LIVE SIMULATION</span>
          </h2>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.85rem' }}>
            LightGBM 概率引擎 + HMM 隐马尔可夫体制识别 + 跨标的 Lead-Lag 动态热力图
          </p>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          {['TSLA', 'NVDA', 'MSTR', 'SNDK'].map((t) => (
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

      {/* Grid Layout: Top Row (LightGBM Probability Gauge + HMM State Transition) */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: '20px', marginBottom: '20px' }}>
        {/* Module 1: LightGBM Predicted Probability Radial Gauge */}
        <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(56, 189, 248, 0.2)', textAlign: 'center' }}>
          <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#38bdf8' }}>
            🤖 LightGBM 条件胜率预测 ($P_{'{win}'}$)
          </h3>
          
          {/* Animated Radial Gauge SVG */}
          <div style={{ position: 'relative', width: '160px', height: '160px', margin: '0 auto' }}>
            <svg width="160" height="160" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="42" fill="none" stroke="#1e293b" strokeWidth="10" />
              <circle
                cx="50"
                cy="50"
                r="42"
                fill="none"
                stroke={pWin >= 0.5239 ? '#22c55e' : '#ef4444'}
                strokeWidth="10"
                strokeDasharray="263.89"
                strokeDashoffset={263.89 * (1 - pWin)}
                strokeLinecap="round"
                style={{ transition: 'stroke-dashoffset 0.8s ease, stroke 0.5s ease' }}
              />
            </svg>
            <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', textAlign: 'center' }}>
              <div style={{ fontSize: '1.8rem', fontWeight: 800, color: pWin >= 0.5239 ? '#22c55e' : '#ef4444' }}>
                {(pWin * 100).toFixed(1)}%
              </div>
              <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>最优门槛 P*: 52.4%</div>
            </div>
          </div>

          <div style={{ marginTop: '12px', fontSize: '0.85rem', color: pWin >= 0.5239 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
            {pWin >= 0.5239 ? '🟢 ML 开仓指令：条件期望 EV > Cost (强烈推荐买入)' : '🔴 ML 观望指令：条件期望 EV <= 0 (放弃开仓)'}
          </div>
        </div>

        {/* Module 2: HMM (Hidden Markov Model) State Transition Diagram */}
        <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h3 style={{ margin: 0, fontSize: '1.05rem', color: '#f59e0b' }}>
              🔮 HMM 隐马尔可夫 4 阶段体制识别
            </h3>
            <span style={{ fontSize: '0.75rem', background: '#78350f', color: '#fbbf24', padding: '2px 8px', borderRadius: '4px', fontWeight: 700 }}>
              当前体制: BULL_TREND
            </span>
          </div>

          {/* HMM State Probability Bars */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '12px' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#cbd5e1', marginBottom: '4px' }}>
                <span>🐂 BULL_TREND (牛市主升浪 - 仓位 100%)</span>
                <strong style={{ color: '#22c55e' }}>{(hmmProbs.BULL * 100).toFixed(0)}%</strong>
              </div>
              <div style={{ height: '8px', background: '#0f172a', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{ width: `${hmmProbs.BULL * 100}%`, background: '#22c55e', height: '100%', transition: 'width 0.6s ease' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#cbd5e1', marginBottom: '4px' }}>
                <span>🦀 RANGE_SIDEWAYS (震荡洗盘 - 仓位 50%)</span>
                <strong style={{ color: '#f59e0b' }}>{(hmmProbs.RANGE * 100).toFixed(0)}%</strong>
              </div>
              <div style={{ height: '8px', background: '#0f172a', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{ width: `${hmmProbs.RANGE * 100}%`, background: '#f59e0b', height: '100%', transition: 'width 0.6s ease' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#cbd5e1', marginBottom: '4px' }}>
                <span>🐻 BEAR_TREND / PANIC (高波恐慌 - 触发避险)</span>
                <strong style={{ color: '#ef4444' }}>{((hmmProbs.PANIC + hmmProbs.BEAR) * 100).toFixed(0)}%</strong>
              </div>
              <div style={{ height: '8px', background: '#0f172a', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{ width: `${(hmmProbs.PANIC + hmmProbs.BEAR) * 100}%`, background: '#ef4444', height: '100%', transition: 'width 0.6s ease' }} />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Grid Layout: Bottom Row (Lead-Lag Arbitrage Dynamic Pulse + Feature Weights) */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '20px' }}>
        {/* Module 3: Cross-Sectional Lead-Lag Dynamic Correlation Pulse */}
        <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
          <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#10b981', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>⚡ 跨标的 Lead-Lag 领涨领跌套利热力脉冲</span>
            <span style={{ fontSize: '0.75rem', color: '#34d399' }}>领头羊: NVDA (相关系数 C_ij={leadLagCorr})</span>
          </h3>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '10px' }}>
            <div style={{ background: '#0f172a', padding: '12px', borderRadius: '6px', textAlign: 'center' }}>
              <div style={{ color: '#94a3b8', fontSize: '0.75rem' }}>NVDA 领头羊脉冲</div>
              <div style={{ fontSize: '1.3rem', color: '#22c55e', fontWeight: 800, marginTop: '4px' }}>+3.2 σ</div>
              <div style={{ fontSize: '0.7rem', color: '#cbd5e1', marginTop: '2px' }}>突破 500ms 脉冲已触发</div>
            </div>

            <div style={{ background: '#0f172a', padding: '12px', borderRadius: '6px', textAlign: 'center' }}>
              <div style={{ color: '#94a3b8', fontSize: '0.75rem' }}>[{ticker}] 500ms 滞后补涨差价</div>
              <div style={{ fontSize: '1.3rem', color: '#38bdf8', fontWeight: 800, marginTop: '4px' }}>+{leadLagDelta} bps</div>
              <div style={{ fontSize: '0.7rem', color: '#cbd5e1', marginTop: '2px' }}>自动捕抓滞后套利开仓</div>
            </div>
          </div>
        </div>

        {/* Module 4: LightGBM Feature Importance Live Bars */}
        <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(168, 85, 247, 0.3)' }}>
          <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#a855f7' }}>
            📊 LightGBM 5 大微观特征贡献度 (Gain %)
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {features.map((f) => (
              <div key={f.name}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#cbd5e1', marginBottom: '2px' }}>
                  <span>{f.name}</span>
                  <strong style={{ color: f.color }}>{f.weight.toFixed(2)}%</strong>
                </div>
                <div style={{ height: '6px', background: '#0f172a', borderRadius: '3px', overflow: 'hidden' }}>
                  <div style={{ width: `${f.weight}%`, background: f.color, height: '100%', borderRadius: '3px', transition: 'width 0.4s ease' }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
