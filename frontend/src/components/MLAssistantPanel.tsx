// frontend/src/components/MLAssistantPanel.tsx

import React, { useState, useEffect, useRef } from 'react';
import { API_BASE } from '../config';
import { InstitutionalQuantDashboard } from './InstitutionalQuantDashboard';
import { MLDynamicVisualizationDashboard } from './MLDynamicVisualizationDashboard';
import { IntradayKlineChart } from './IntradayKlineChart';

// Only calibrated, versioned predictions may populate model cards.
const metric = (v: number | null | undefined, digits = 1, suffix = '') =>
  typeof v === 'number' && Number.isFinite(v) ? `${v.toFixed(digits)}${suffix}` : '—';

export const MLAssistantPanel: React.FC<{ activeTicker: string }> = ({ activeTicker }) => {
  const [ticker, setTicker] = useState<string>(activeTicker || "TSLA");
  const [horizonMode, setHorizonMode] = useState<'daytrade' | 'swing'>('daytrade');
  const [loading, setLoading] = useState<boolean>(false);
  const [mlData, setMlData] = useState<any>(null);

  const [sourceLabel, setSourceLabel] = useState('正在读取数据来源…');
  const requestId = useRef(0);
  const [demoOfi, setDemoOfi] = useState(0.45);
  const [demoSpeed, setDemoSpeed] = useState(0.12);
  const fetchMLInference = async (selectedTicker: string) => {
    const id = ++requestId.current;
    setLoading(true);
    setMlData(null);
    try {
      const res = await fetch(`${API_BASE}/api/ml/predict?ticker=${encodeURIComponent(selectedTicker)}`);
      if (!res.ok) throw new Error('Snapshot request failed');
      const json = await res.json();
      if (id !== requestId.current) return;
      setMlData(json.status === 'validated_prediction' ? json.result : null);
      setSourceLabel(json.data_provenance?.label || json.error || '模型指标尚不可用');
    } catch {
      if (id === requestId.current) {
        setMlData(null);
        setSourceLabel('数据请求失败 · 请重试');
      }
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  };

  useEffect(() => {
    if (activeTicker) {
      setTicker(activeTicker);
    }
  }, [activeTicker]);

  useEffect(() => {
    fetchMLInference(ticker);
  }, [ticker]);

  const currentWinRatePct = horizonMode === 'daytrade' ? mlData?.win_rate_daytrade_pct : mlData?.win_rate_pct;
  const currentEPnlR = horizonMode === 'daytrade' ? mlData?.e_pnl_daytrade_r : mlData?.expected_value_r;
  const currentEvStatus = currentEPnlR == null ? '待验证' : (currentEPnlR > 0 ? '正期望' : '非正期望');

  return (
    <div style={{ padding: '20px', background: '#0a0a0c', color: '#fff', borderRadius: '12px' }}>
      {/* Header Banner */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '15px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 800, color: '#38bdf8' }}>
              🤖 ML 决策 AI 助手 & 实时诊断仪表盘
            </h2>
            {/* Horizon Mode Toggle */}
            <div style={{ display: 'flex', background: '#1e293b', borderRadius: '8px', padding: '3px', border: '1px solid rgba(255,255,255,0.1)' }}>
              <button
                onClick={() => setHorizonMode('daytrade')}
                style={{
                  padding: '5px 12px',
                  fontSize: '0.8rem',
                  fontWeight: 800,
                  borderRadius: '6px',
                  border: 'none',
                  cursor: 'pointer',
                  background: horizonMode === 'daytrade' ? 'linear-gradient(135deg, #0284c7, #0369a1)' : 'transparent',
                  color: '#fff'
                }}
              >
                ⚡ Day Trading 模式 (15m)
              </button>
              <button
                onClick={() => setHorizonMode('swing')}
                style={{
                  padding: '5px 12px',
                  fontSize: '0.8rem',
                  fontWeight: 800,
                  borderRadius: '6px',
                  border: 'none',
                  cursor: 'pointer',
                  background: horizonMode === 'swing' ? 'linear-gradient(135deg, #8b5cf6, #6d28d9)' : 'transparent',
                  color: '#fff'
                }}
              >
                📈 趋势投资模式 (1日)
              </button>
            </div>
          </div>
          <p style={{ margin: '6px 0 0 0', color: '#94a3b8', fontSize: '0.85rem' }}>
            {horizonMode === 'daytrade'
              ? '⚡ Day Trading 模式：5分钟 K 线、量价特征与 15 分钟方向分数展示'
              : '📈 趋势投资模式：日线特征、相对强弱与跨日方向分数展示'}
          </p>
        </div>

        {/* Ticker Switcher */}
        <div style={{ display: 'flex', gap: '8px' }}>
          {["TSLA", "NVDA", "AAPL", "AMD", "MSFT", "SNDK", "MU"].map(t => (
            <button
              key={t}
              onClick={() => { setTicker(t); }}
              style={{
                padding: '6px 12px',
                borderRadius: '6px',
                border: 'none',
                fontWeight: 700,
                cursor: 'pointer',
                background: ticker === t ? '#0284c7' : '#1e293b',
                color: '#fff'
              }}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <div role="status" style={{ fontSize: '0.8rem', color: '#94a3b8', marginBottom: '16px' }}>{sourceLabel} · — 表示缺少已验证结果</div>
      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: '#38bdf8' }}>
          🔄 正在读取 [{ticker}] 的数据...
        </div>
      ) : (
        <div>
          {/* Dynamic Animated ML Models Visualization Dashboard */}
          <div style={{ marginBottom: '24px' }}>
            <MLDynamicVisualizationDashboard />
          </div>

          {/* Intraday K-Line Chart Component */}
          <div style={{ marginBottom: '24px' }}>
            <IntradayKlineChart ticker={ticker} />
          </div>

          {/* Main 4 ML Models Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px', marginBottom: '20px' }}>
            {/* Card 1: Probability Calibration */}
            <div style={{ background: '#1e293b', padding: '16px', borderRadius: '8px', borderLeft: '4px solid #38bdf8' }}>
              <div style={{ fontSize: '0.8rem', color: '#94a3b8', fontWeight: 700 }}>
                1. 校准胜率 (P_win - {horizonMode === 'daytrade' ? '15m' : '1d'})
              </div>
              <div style={{ fontSize: '1.8rem', fontWeight: 800, color: '#38bdf8', margin: '6px 0' }}>
                {metric(currentWinRatePct, 1, '%')}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>
                Brier Score: <strong>—</strong>（待校准）<br/>
                预测标准差 σ: <strong>±{metric(mlData?.p_std == null ? null : mlData.p_std * 100, 1, '%')}</strong>
              </div>
            </div>

            {/* Card 2: LGBMRanker Score */}
            <div style={{ background: '#1e293b', padding: '16px', borderRadius: '8px', borderLeft: '4px solid #a855f7' }}>
              <div style={{ fontSize: '0.8rem', color: '#94a3b8', fontWeight: 700 }}>2. LambdaMART 选股得分</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 800, color: '#c084fc', margin: '6px 0' }}>
                {metric(mlData?.rank_score, 3)}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>
                横截面排序结果展示<br/>
                模型版本: <strong>待验证</strong>
              </div>
            </div>

            {/* Card 3: HMM Market Regime */}
            <div style={{ background: '#1e293b', padding: '16px', borderRadius: '8px', borderLeft: '4px solid #22c55e' }}>
              <div style={{ fontSize: '0.8rem', color: '#94a3b8', fontWeight: 700 }}>3. HMM 隐状态市场体制</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#4ade80', margin: '6px 0' }}>
                {mlData?.hmm_regime ?? '待验证'}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>
                风险打折系数: <strong>{metric(mlData?.volatility_penalty, 2, 'x')}</strong><br/>
                状态展示: <strong>{mlData?.hmm_regime ?? '待验证'}</strong>
              </div>
            </div>

            {/* Card 4: Mathematical Expectation */}
            <div style={{ background: '#1e293b', padding: '16px', borderRadius: '8px', borderLeft: '4px solid #f59e0b' }}>
              <div style={{ fontSize: '0.8rem', color: '#94a3b8', fontWeight: 700 }}>4. 期望 E[R] & 仓位估计</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 800, color: currentEPnlR >= 0.05 ? '#4ade80' : '#ef4444', margin: '6px 0' }}>
                {metric(currentEPnlR, 3, ' R')}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>
                Kelly 仓位: <strong>{metric(mlData?.kelly_fraction == null ? null : mlData.kelly_fraction * 100, 1, '%')}</strong><br/>
                验证状态: <span style={{ color: currentEPnlR >= 0.05 ? '#4ade80' : '#ef4444', fontWeight: 800 }}>{currentEvStatus}</span>
              </div>
            </div>
          </div>

          {/* Section: Reliability Calibration Binning Table */}
          <div style={{ background: '#1e293b', padding: '16px', borderRadius: '8px', marginBottom: '20px' }}>
            <h3 style={{ margin: '0 0 12px 0', fontSize: '1rem', color: '#38bdf8' }}>
              📊 概率校准分箱 (Reliability Bin Table - Platt Scaling)
            </h3>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ background: '#0f172a', textAlign: 'left', color: '#94a3b8' }}>
                  <th style={{ padding: '8px' }}>预测概率 Bin</th>
                  <th style={{ padding: '8px' }}>模型预测胜率 P_pred</th>
                  <th style={{ padding: '8px' }}>实际发生频数 P_true</th>
                  <th style={{ padding: '8px' }}>校准误差 Error</th>
                  <th style={{ padding: '8px' }}>对齐状态图形</th>
                </tr>
              </thead>
              <tbody>
                <tr><td colSpan={5} style={{ padding: '16px', color: '#94a3b8' }}>尚无可核验的样本外校准记录；不显示示例胜率或“吻合”结果。</td></tr>
              </tbody>
            </table>
          </div>

          {/* Section: Smart Order Router Decision */}
          <div style={{ background: '#1e293b', padding: '16px', borderRadius: '8px' }}>
            <h3 style={{ margin: '0 0 12px 0', fontSize: '1rem', color: '#f59e0b', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>⚡ Smart Order Router (SOR) 微观结构报单诊断</span>
              <span style={{ fontSize: '0.75rem', color: '#10b981', fontWeight: 700 }}>等待成交与报价校验</span>
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <div style={{ background: '#0f172a', padding: '12px', borderRadius: '6px', border: '1px solid rgba(34, 197, 94, 0.3)' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.8rem' }}>限价被动挂单 Expected Value (EV_maker)</div>
                <div style={{ fontSize: '1.2rem', color: '#22c55e', fontWeight: 700 }}>
                  {metric(mlData?.sor_decision?.ev_maker_bps, 1, ' bps')}
                </div>
                <div style={{ fontSize: '0.75rem', color: '#cbd5e1', marginTop: '4px' }}>
                  挂单 500ms 成交率 P(Fill): <strong>{metric(mlData?.sor_decision?.p_fill_500ms == null ? null : mlData.sor_decision.p_fill_500ms * 100, 1, '%')}</strong><br/>
                  毒性杀跌风险 P(Adverse): <strong style={{ color: '#ef4444' }}>{metric(mlData?.sor_decision?.p_adverse_selection == null ? null : mlData.sor_decision.p_adverse_selection * 100, 1, '%')}</strong>
                </div>
              </div>

              <div style={{ background: '#0f172a', padding: '12px', borderRadius: '6px', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
                <div style={{ color: '#94a3b8', fontSize: '0.8rem' }}>市价主动吃单 Expected Value (EV_taker)</div>
                <div style={{ fontSize: '1.2rem', color: '#38bdf8', fontWeight: 700 }}>
                  {metric(mlData?.sor_decision?.ev_taker_bps, 1, ' bps')}
                </div>
                <div style={{ fontSize: '0.75rem', color: '#cbd5e1', marginTop: '4px' }}>
                  预测未来 500ms 微观涨幅: <strong>{metric(mlData?.sor_decision?.expected_return_bps, 1, ' bps')}</strong><br/>
                  自动报单建议: <strong style={{ color: '#10b981' }}>{mlData?.sor_decision?.recommended_order_type ?? '待验证'}</strong>
                </div>
              </div>
            </div>
          </div>

          {/* Section: HRT ML Interactive Microstructure Control Sandbox */}
          <div style={{ background: '#1e293b', padding: '18px', borderRadius: '8px', marginTop: '20px', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h3 style={{ margin: 0, fontSize: '1.05rem', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '8px' }}>
                🎛️ 微观结构 ML 交互操盘沙盒 (ML Feature Interactive Sandbox)
              </h3>
              <span style={{ fontSize: '0.75rem', background: '#0284c7', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontWeight: 700 }}>
                手动输入 · 非实时盘口
              </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px', marginBottom: '16px' }}>
              {/* Slider 1: OFI */}
              <div style={{ background: '#0f172a', padding: '12px', borderRadius: '6px' }}>
                <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginBottom: '6px' }}>Order Flow Imbalance (OFI) 盘口流入不平衡度</div>
                <input
                  type="range"
                  min="-1.0"
                  max="1.0"
                  step="0.05"
                  value={demoOfi}
                  style={{ width: '100%', cursor: 'pointer' }}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value);
                    setDemoOfi(v);

                  }}
                />
                <div style={{ fontSize: '0.75rem', color: '#38bdf8', marginTop: '4px', textAlign: 'right', fontWeight: 700 }}>
                  输入 OFI: {demoOfi.toFixed(2)}
                </div>
              </div>

              {/* Slider 2: Microprice Drift */}
              <div style={{ background: '#0f172a', padding: '12px', borderRadius: '6px' }}>
                <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginBottom: '6px' }}>Microprice Velocity 微观价格速动量</div>
                <input
                  type="range"
                  min="-0.5"
                  max="0.5"
                  step="0.02"
                  value={demoSpeed}
                  style={{ width: '100%', cursor: 'pointer' }}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value);
                    setDemoSpeed(v);

                  }}
                />
                <div style={{ fontSize: '0.75rem', color: '#a855f7', marginTop: '4px', textAlign: 'right', fontWeight: 700 }}>
                  速度: {demoSpeed >= 0 ? '+' : ''}{demoSpeed.toFixed(2)}% / 500ms（情景）
                </div>
              </div>

              {/* Action Button: Manual ML Trigger */}
              <div style={{ background: '#0f172a', padding: '12px', borderRadius: '6px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                <button
                  onClick={async () => {
                    alert(`🚀 已基于当前演示参数为 [${ticker}] 手动触发一次模拟买卖评估！\n方向分数 P_win: ${metric(currentWinRatePct, 1, '%')}\n数学期望 E[R]: +${currentEPnlR}R\n最佳智能报单: ${mlData?.sor_decision.recommended_order_type}`);
                  }}
                  style={{
                    background: 'linear-gradient(135deg, #10b981, #059669)',
                    border: 'none',
                    color: '#fff',
                    padding: '10px 14px',
                    borderRadius: '6px',
                    fontWeight: 800,
                    fontSize: '0.85rem',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease'
                  }}
                >
                  ⚡ 手动触发 ML 情景评估
                </button>
              </div>
            </div>
          </div>

          {/* Section: Jane Street / HRT L2 DOM Order Book & Low-Latency Profiler */}
          <div style={{ marginTop: '24px' }}>
            <InstitutionalQuantDashboard />
          </div>
        </div>
      )}
    </div>
  );
};
