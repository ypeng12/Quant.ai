import React, { useState, useEffect } from 'react';
import { API_BASE } from '../config';

export const MLDynamicVisualizationDashboard: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'two_stage' | 'overview'>('two_stage');
  const [ticker, setTicker] = useState<string>('PLTR');
  const [observed, setObserved] = useState<any>(null);
  const [source, setSource] = useState('正在读取历史行情…');
  useEffect(() => {
    let active = true;
    setObserved(null);
    setSource('正在读取历史行情…');
    fetch(`${API_BASE}/api/ml/predict?ticker=${ticker}`).then(r => r.json()).then(data => {
      if (active) {
        setObserved(data.observed ?? null);
        setSource(data.data_provenance?.label ?? data.error ?? '数据不可用');
      }
    }).catch(() => { if (active) setSource('数据请求失败'); });
    return () => { active = false; };
  }, [ticker]);
  const fmt = (value: number | undefined | null, suffix = '') =>
    typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) + suffix : '—';
  const pWin = 0, pChop = 0, pTrend = 0;
  const hmmProbs = { BULL: 0, RANGE: 0 };
  // Empty chart progress is not a probability of zero; labels stay unavailable.
  const features = [
    { name: 'Microprice Velocity (微观价格速度)', color: '#38bdf8' },
    { name: 'RVOL (相对成交量强弱)', color: '#22c55e' },
    { name: 'OFI (订单流买卖盘不平衡度)', color: '#f59e0b' },
    { name: 'Spread Ratio (买卖价差比)', color: '#a855f7' },
    { name: 'VPIN (知情交易毒性指标)', color: '#ef4444' }
  ];

  return (
    <div style={{ background: '#090d16', color: '#e2e8f0', padding: '24px', borderRadius: '12px', fontFamily: 'Inter, system-ui, sans-serif', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
      {/* Top Header & Architecture Selector Tabs */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '14px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.35rem', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span>🏛️ Quant.ai 两级自适应 ML 动态诊断大屏</span>
            <span style={{ fontSize: '0.75rem', background: '#0284c7', color: '#fff', padding: '3px 10px', borderRadius: '4px', fontWeight: 800 }}>
              Two-Stage Adaptive ML · 数据诊断
            </span>
          </h2>
          <p style={{ margin: '4px 0 0 0', color: '#94a3b8', fontSize: '0.85rem' }}>
            {source}
          </p>
        </div>

        {/* Tab Navigation & Ticker Buttons */}
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <div style={{ display: 'flex', background: '#0f172a', borderRadius: '8px', padding: '3px', border: '1px solid rgba(255,255,255,0.1)' }}>
            <button
              onClick={() => setActiveTab('two_stage')}
              style={{
                padding: '7px 14px',
                borderRadius: '6px',
                border: 'none',
                fontWeight: 700,
                fontSize: '0.8rem',
                cursor: 'pointer',
                background: activeTab === 'two_stage' ? 'linear-gradient(135deg, #7c3aed, #4c1d95)' : 'transparent',
                color: activeTab === 'two_stage' ? '#fff' : '#94a3b8'
              }}
            >
              🏛️ 两级自适应 ML 动态诊断 Tab
            </button>
            <button
              onClick={() => setActiveTab('overview')}
              style={{
                padding: '7px 14px',
                borderRadius: '6px',
                border: 'none',
                fontWeight: 700,
                fontSize: '0.8rem',
                cursor: 'pointer',
                background: activeTab === 'overview' ? 'linear-gradient(135deg, #0284c7, #0369a1)' : 'transparent',
                color: activeTab === 'overview' ? '#fff' : '#94a3b8'
              }}
            >
              🤖 全量 LightGBM 胜率与特征重要性
            </button>
          </div>

          <div style={{ display: 'flex', gap: '6px' }}>
            {['PLTR', 'SNDK', 'TSLA', 'NVDA'].map((t) => (
              <button
                key={t}
                onClick={() => setTicker(t)}
                style={{
                  padding: '6px 12px',
                  borderRadius: '6px',
                  border: 'none',
                  fontWeight: 700,
                  fontSize: '0.8rem',
                  cursor: 'pointer',
                  background: ticker === t ? '#38bdf8' : '#1e293b',
                  color: ticker === t ? '#090d16' : '#fff'
                }}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      {activeTab === 'two_stage' ? (
        /* TAB 1: Citadel & HRT Two-Stage Hierarchical ML Diagnostics */
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Active Mode Banner */}
          <div style={{ background: 'linear-gradient(90deg, #1e293b, #0f172a)', padding: '14px 20px', borderRadius: '10px', border: '1px solid #475569', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '1px', color: '#cbd5e1', fontWeight: 800 }}>
                ⚡ STAGE-2 自动切换执行模式 (Auto-Switched Execution Strategy)
              </span>
              <div style={{ fontSize: '1.2rem', fontWeight: 900, color: '#fff', marginTop: '2px' }}>
                模型模式：待验证
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>[{ticker}] 该历史交易日涨跌（开盘至收盘）</div>
              <div style={{ fontSize: '1.3rem', color: (observed?.day_return_pct ?? 0) >= 0 ? '#10b981' : '#ef4444', fontWeight: 900 }}>{fmt(observed?.day_return_pct, '%')}</div>
            </div>
          </div>

          {/* Grid Layout: Stage 1 ML Classifier + Stage 2 Execution & Microprice Acceleration */}
          <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1.2fr 1fr', gap: '20px' }}>
            {/* Box 1: Stage-1 Regime Classifier ML */}
            <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(99, 102, 241, 0.3)' }}>
              <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#818cf8', display: 'flex', justifyContent: 'space-between' }}>
                <span>🎯 Stage-1 Regime 分类器 ML</span>
                <span style={{ fontSize: '0.75rem', color: '#c7d2fe' }}>Hurst: —</span>
              </h3>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '14px' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#cbd5e1', marginBottom: '4px' }}>
                    <span>🦀 P(CHOP_RANGE 震荡箱体)</span>
                    <strong style={{ color: '#818cf8' }}>—</strong>
                  </div>
                  <div style={{ height: '10px', background: '#0f172a', borderRadius: '5px', overflow: 'hidden' }}>
                    <div style={{ width: `${pChop * 100}%`, background: 'linear-gradient(90deg, #6366f1, #818cf8)', height: '100%', transition: 'width 0.6s ease' }} />
                  </div>
                </div>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#cbd5e1', marginBottom: '4px' }}>
                    <span>🚀 P(TREND_BREAKOUT 单边趋势)</span>
                    <strong style={{ color: '#34d399' }}>—</strong>
                  </div>
                  <div style={{ height: '10px', background: '#0f172a', borderRadius: '5px', overflow: 'hidden' }}>
                    <div style={{ width: `${pTrend * 100}%`, background: 'linear-gradient(90deg, #059669, #34d399)', height: '100%', transition: 'width 0.6s ease' }} />
                  </div>
                </div>

                <div style={{ background: '#0f172a', padding: '10px', borderRadius: '6px', fontSize: '0.75rem', color: '#94a3b8', marginTop: '4px' }}>
                  缺少所选股票的有效模型产物，不能判定当前体制或自动执行模式。
                </div>
              </div>
            </div>

            {/* Box 2: Stage-2 Execution Parameters & Bounds */}
            <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
              <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#38bdf8' }}>
                ⚙️ Stage-2 自动挂单区间与信号线
              </h3>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '10px' }}>
                <div style={{ background: '#0f172a', padding: '12px', borderRadius: '8px', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
                  <div style={{ color: '#ef4444', fontSize: '0.75rem', fontWeight: 700 }}>箱体上轨挂空线 (Upper Sell)</div>
                  <div style={{ fontSize: '1.2rem', color: '#f87171', fontWeight: 800, marginTop: '4px' }}>待验证</div>
                  <div style={{ fontSize: '0.7rem', color: '#94a3b8', marginTop: '2px' }}>等待模型与执行记录</div>
                </div>

                <div style={{ background: '#0f172a', padding: '12px', borderRadius: '8px', border: '1px solid rgba(34, 197, 94, 0.3)' }}>
                  <div style={{ color: '#22c55e', fontSize: '0.75rem', fontWeight: 700 }}>箱体下轨托多线 (Lower Buy)</div>
                  <div style={{ fontSize: '1.2rem', color: '#4ade80', fontWeight: 800, marginTop: '4px' }}>待验证</div>
                  <div style={{ fontSize: '0.7rem', color: '#94a3b8', marginTop: '2px' }}>等待模型与执行记录</div>
                </div>
              </div>

              <div style={{ marginTop: '14px', fontSize: '0.8rem', color: '#cbd5e1', background: '#0f172a', padding: '10px', borderRadius: '6px' }}>
                <span>🎯 当前开仓胜率预测: </span>
                <strong style={{ color: '#38bdf8' }}>—</strong>
                <span style={{ margin: '0 8px' }}>|</span>
                <span>期望收益: </span>
                <strong style={{ color: '#22c55e' }}>—</strong>
              </div>
            </div>

            {/* Box 3: Physics Price Acceleration (d^2P / dt^2) */}
            <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(245, 158, 11, 0.3)', textAlign: 'center' }}>
              <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#f59e0b' }}>
                🚀 最近一根 5m 收益（历史观测）
              </h3>

              <div style={{ fontSize: '2.2rem', fontWeight: 900, color: (observed?.last_return_bps ?? 0) >= 0 ? '#22c55e' : '#ef4444', margin: '14px 0' }}>
                {fmt(observed?.last_return_bps, ' bps')}
              </div>

              <div style={{ fontSize: '0.8rem', color: '#94a3b8', fontWeight: 700 }}>
                {observed?.date ?? '等待行情'}
              </div>

              <div style={{ fontSize: '0.7rem', color: '#94a3b8', marginTop: '12px', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '8px' }}>
                相邻收盘价计算；是历史变化，不是未来收益预测。
              </div>
            </div>
          </div>

          {/* Box 4: ML Supervised Learning & Human-Readable Decision Attribution Chain */}
          <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(168, 85, 247, 0.3)' }}>
            <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#c084fc', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>🧠 ML 有监督学习 (Supervised Learning) 与 4 步决策推理全透明链条</span>
              <span style={{ fontSize: '0.75rem', background: '#581c87', color: '#e9d5ff', padding: '2px 8px', borderRadius: '4px', fontWeight: 700 }}>
                完全可解释性 (Full Interpretability)
              </span>
            </h3>

            {/* Grid for Supervision Info + Decision Steps */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2.5fr', gap: '16px', marginTop: '12px' }}>
              {/* Left Column: Supervision Dataset & Target */}
              <div style={{ background: '#0f172a', padding: '14px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
                <div style={{ color: '#a855f7', fontSize: '0.8rem', fontWeight: 800, marginBottom: '8px' }}>🎯 监督学习数据集与标签 (Y)</div>
                <div style={{ fontSize: '0.75rem', color: '#cbd5e1', lineHeight: '1.5' }}>
                  • <strong>监督数据</strong>: {observed?.bar_count ?? '—'} 根所选日历史 5m K 线<br/>
                  • <strong>监督目标 Y=1</strong>: 待模型产物声明<br/>
                  • <strong>监督目标 Y=0</strong>: 待模型产物声明<br/>
                  • <strong>概率校准</strong>: 待样本外校准
                </div>
              </div>

              {/* Right Column: 4-Step Decision Inference Chain */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '10px' }}>
                <div style={{ background: '#0f172a', padding: '10px', borderRadius: '6px', borderLeft: '3px solid #38bdf8' }}>
                  <div style={{ fontSize: '0.7rem', color: '#38bdf8', fontWeight: 800 }}>Step 1 特征抽取</div>
                  <div style={{ fontSize: '0.75rem', color: '#e2e8f0', marginTop: '4px', fontWeight: 700 }}>OFI = —</div>
                  <div style={{ fontSize: '0.68rem', color: '#94a3b8', marginTop: '2px' }}>等待真实报价事件</div>
                </div>

                <div style={{ background: '#0f172a', padding: '10px', borderRadius: '6px', borderLeft: '3px solid #818cf8' }}>
                  <div style={{ fontSize: '0.7rem', color: '#818cf8', fontWeight: 800 }}>Step 2 概率推理</div>
                  <div style={{ fontSize: '0.75rem', color: '#818cf8', marginTop: '4px', fontWeight: 700 }}>P_win = —</div>
                  <div style={{ fontSize: '0.68rem', color: '#94a3b8', marginTop: '2px' }}>等待校准结果</div>
                </div>

                <div style={{ background: '#0f172a', padding: '10px', borderRadius: '6px', borderLeft: '3px solid #22c55e' }}>
                  <div style={{ fontSize: '0.7rem', color: '#22c55e', fontWeight: 800 }}>Step 3 期望风控</div>
                  <div style={{ fontSize: '0.75rem', color: '#22c55e', marginTop: '4px', fontWeight: 700 }}>EV = —</div>
                  <div style={{ fontSize: '0.68rem', color: '#94a3b8', marginTop: '2px' }}>等待预测与成本核验</div>
                </div>

                <div style={{ background: '#0f172a', padding: '10px', borderRadius: '6px', borderLeft: '3px solid #f59e0b' }}>
                  <div style={{ fontSize: '0.7rem', color: '#f59e0b', fontWeight: 800 }}>Step 4 体制监督</div>
                  <div style={{ fontSize: '0.75rem', color: '#f59e0b', marginTop: '4px', fontWeight: 700 }}>体制 = —</div>
                  <div style={{ fontSize: '0.68rem', color: '#94a3b8', marginTop: '2px' }}>等待模型推断</div>
                </div>
              </div>
            </div>
          </div>

          {/* Box 5: Plain-Language Real-Time Situation Explainer (大白话当前盘面局势全息解读) */}
          <div style={{ background: '#111827', padding: '18px', borderRadius: '10px', border: '1px solid rgba(16, 185, 129, 0.4)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <h3 style={{ margin: 0, fontSize: '1.05rem', color: '#34d399', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>💬 当前盘面局势大白话解读器 (历史数据解读)</span>
              </h3>
              <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                标的: <strong style={{ color: '#38bdf8' }}>{ticker}</strong> | 状态: 历史行情
              </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginTop: '12px' }}>
              <div style={{ background: '#0f172a', padding: '12px', borderRadius: '8px', borderLeft: '4px solid #38bdf8' }}>
                <div style={{ fontSize: '0.8rem', color: '#38bdf8', fontWeight: 800 }}>1. 当前是什么局势形态？</div>
                <div style={{ fontSize: '0.8rem', color: '#e2e8f0', marginTop: '4px', lineHeight: '1.4' }}>
                  <span>[{ticker}] 在 {observed?.date ?? '—'} 的开收盘变化为 {fmt(observed?.day_return_pct, '%')}，5m 收益波动为 {fmt(observed?.volatility_bps, ' bps')}。这些是已发生的行情。</span>
                </div>
              </div>

              <div style={{ background: '#0f172a', padding: '12px', borderRadius: '8px', borderLeft: '4px solid #f59e0b' }}>
                <div style={{ fontSize: '0.8rem', color: '#f59e0b', fontWeight: 800 }}>2. 盘口买卖力量谁占优？</div>
                <div style={{ fontSize: '0.8rem', color: '#e2e8f0', marginTop: '4px', lineHeight: '1.4' }}>
                  <span>真实盘口事件未接入此面板，无法据 K 线判断挂单、撤单或买卖力量。</span>
                </div>
              </div>

              <div style={{ background: '#0f172a', padding: '12px', borderRadius: '8px', borderLeft: '4px solid #a855f7' }}>
                <div style={{ fontSize: '0.8rem', color: '#a855f7', fontWeight: 800 }}>3. ML 为什么这样操作？</div>
                <div style={{ fontSize: '0.8rem', color: '#e2e8f0', marginTop: '4px', lineHeight: '1.4' }}>
                  <span>本面板尚未取得对应模型版本和推断记录，不能声称模型批准开仓。</span>
                </div>
              </div>

              <div style={{ background: '#0f172a', padding: '12px', borderRadius: '8px', borderLeft: '4px solid #22c55e' }}>
                <div style={{ fontSize: '0.8rem', color: '#22c55e', fontWeight: 800 }}>4. 当前防守与风控策略</div>
                <div style={{ fontSize: '0.8rem', color: '#e2e8f0', marginTop: '4px', lineHeight: '1.4' }}>
                  <span>交易执行状态以账户持仓、订单及运行器日志为准；此历史视图不产生交易指令。</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* TAB 2: LightGBM & Lead-Lag Overview (Previous UI) */
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: '20px' }}>
            <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(56, 189, 248, 0.2)', textAlign: 'center' }}>
              <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#38bdf8' }}>
                🤖 LightGBM 条件胜率预测 (P_win)
              </h3>
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
                    —
                  </div>
                  <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>阈值：待验证</div>
                </div>
              </div>
              <div style={{ marginTop: '12px', fontSize: '0.85rem', color: pWin >= 0.5239 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
                模型与校准记录待验证
              </div>
            </div>

            <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <h3 style={{ margin: 0, fontSize: '1.05rem', color: '#f59e0b' }}>
                  🔮 HMM 隐马尔可夫 4 阶段体制识别
                </h3>
                <span style={{ fontSize: '0.75rem', background: '#78350f', color: '#fbbf24', padding: '2px 8px', borderRadius: '4px', fontWeight: 700 }}>
                  当前体制: 待验证
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '12px' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#cbd5e1', marginBottom: '4px' }}>
                    <span>🐂 BULL_TREND (牛市状态)</span>
                    <strong style={{ color: '#22c55e' }}>—</strong>
                  </div>
                  <div style={{ height: '8px', background: '#0f172a', borderRadius: '4px', overflow: 'hidden' }}>
                    <div style={{ width: `${hmmProbs.BULL * 100}%`, background: '#22c55e', height: '100%', transition: 'width 0.6s ease' }} />
                  </div>
                </div>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#cbd5e1', marginBottom: '4px' }}>
                    <span>🦀 RANGE_SIDEWAYS (震荡状态)</span>
                    <strong style={{ color: '#f59e0b' }}>—</strong>
                  </div>
                  <div style={{ height: '8px', background: '#0f172a', borderRadius: '4px', overflow: 'hidden' }}>
                    <div style={{ width: `${hmmProbs.RANGE * 100}%`, background: '#f59e0b', height: '100%', transition: 'width 0.6s ease' }} />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '20px' }}>
            <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
              <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#10b981', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>⚡ 跨标的 Lead-Lag 领涨领跌套利热力脉冲</span>
                <span style={{ fontSize: '0.75rem', color: '#34d399' }}>领头羊: 待研究</span>
              </h3>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '10px' }}>
                <div style={{ background: '#0f172a', padding: '12px', borderRadius: '6px', textAlign: 'center' }}>
                  <div style={{ color: '#94a3b8', fontSize: '0.75rem' }}>NVDA 领头羊脉冲</div>
                  <div style={{ fontSize: '1.3rem', color: '#22c55e', fontWeight: 800, marginTop: '4px' }}>—</div>
                </div>

                <div style={{ background: '#0f172a', padding: '12px', borderRadius: '6px', textAlign: 'center' }}>
                  <div style={{ color: '#94a3b8', fontSize: '0.75rem' }}>[{ticker}] 滞后补涨差价</div>
                  <div style={{ fontSize: '1.3rem', color: '#38bdf8', fontWeight: 800, marginTop: '4px' }}>—</div>
                </div>
              </div>
            </div>

            <div style={{ background: '#131b2e', padding: '18px', borderRadius: '10px', border: '1px solid rgba(168, 85, 247, 0.3)' }}>
              <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#a855f7' }}>
                📊 LightGBM 5 大微观特征贡献度 (Gain %)
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {features.map((f) => (
                  <div key={f.name}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#cbd5e1', marginBottom: '2px' }}>
                      <span>{f.name}</span>
                      <strong style={{ color: f.color }}>—</strong>
                    </div>
                    <div style={{ height: '6px', background: '#0f172a', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{ width: '0%', background: f.color, height: '100%', transition: 'width 0.4s ease' }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
