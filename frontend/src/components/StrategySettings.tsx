// frontend/src/components/StrategySettings.tsx

import React from 'react';

export interface StrategyParams {
  strategy_mode: 'consensus' | 'ema_cross' | 'breakout' | 'patterns' | 'opening_breakout' | 'dynamic';
  stop_loss_pct: number;
  profit_target_pct: number;
  trailing_stop_mode: 'atr' | 'flat' | 'none';
  trailing_stop_atr_mult: number;
  rsi_threshold_buy: number;
  risk_per_trade_pct: number;
  max_position_size_pct: number;
  position_sizing_mode: 'atr' | 'flat';
  commission_per_share: number;
  slippage_rate: number;
  market_open_focus: boolean;
}

interface StrategySettingsProps {
  params: StrategyParams;
  onChange: (newParams: StrategyParams) => void;
  onReset: () => void;
  aiAutoPilot: boolean;
  onToggleAutoPilot: (val: boolean) => void;
}

export const StrategySettings: React.FC<StrategySettingsProps> = ({ params, onChange, onReset, aiAutoPilot, onToggleAutoPilot }) => {
  const handleChange = (key: keyof StrategyParams, value: any) => {
    onChange({
      ...params,
      [key]: value
    });
  };

  return (
    <div className="card" style={{ position: 'relative' }}>
      
      {/* AI Auto-Pilot Card */}
      <div style={{
        background: aiAutoPilot ? 'linear-gradient(135deg, rgba(0, 200, 5, 0.12), rgba(0, 150, 5, 0.04))' : 'rgba(255, 255, 255, 0.02)',
        border: aiAutoPilot ? '1px dashed rgba(0, 200, 5, 0.4)' : '1px solid var(--color-border)',
        borderRadius: '8px',
        padding: '12px 16px',
        marginBottom: '1.25rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        transition: 'all 0.3s ease'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '1.2rem' }}>🤖</span>
            <span style={{ fontWeight: 700, fontSize: '0.9rem', color: '#ffffff' }}>AI 智能托管 / 自动调参</span>
            {aiAutoPilot && (
              <span style={{
                background: 'rgba(0, 200, 5, 0.15)',
                color: 'var(--color-green)',
                padding: '2px 8px',
                borderRadius: '12px',
                fontSize: '0.75rem',
                fontWeight: 700,
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px'
              }}>
                <span style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  backgroundColor: 'var(--color-green)',
                  animation: 'pulse 1.5s infinite',
                  display: 'inline-block'
                }}></span>
                已激活
              </span>
            )}
          </div>
          
          {/* Switch Switch */}
          <label style={{ display: 'inline-flex', alignItems: 'center', cursor: 'pointer' }}>
            <input 
              type="checkbox"
              checked={aiAutoPilot}
              onChange={(e) => onToggleAutoPilot(e.target.checked)}
              style={{ display: 'none' }}
            />
            <div style={{
              width: '40px',
              height: '20px',
              backgroundColor: aiAutoPilot ? 'var(--color-green)' : '#2c2c2e',
              borderRadius: '10px',
              position: 'relative',
              transition: 'background-color 0.2s',
              border: '1px solid var(--color-border)'
            }}>
              <div style={{
                width: '16px',
                height: '16px',
                backgroundColor: aiAutoPilot ? '#000000' : '#ffffff',
                borderRadius: '50%',
                position: 'absolute',
                top: '1px',
                left: aiAutoPilot ? '21px' : '1px',
                transition: 'left 0.2s'
              }}></div>
            </div>
          </label>
        </div>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.75rem', margin: 0, lineHeight: 1.4 }}>
          {aiAutoPilot 
            ? "机器学习调优中。算法自动分析开盘高频阻力与相对成交量，调配仓位与止损，保护本金并稳健止盈。"
            : "开启后，系统将自动基于近期历史特征运行微型 Walk-Forward 调优，代替手动参数设置。"
          }
        </p>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
        <h3 className="card-title" style={{ margin: 0 }}>手动参数与风控 (Strategy Parameters)</h3>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {/* 开盘突击模式 Checkbox */}
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem', color: '#ffffff', cursor: aiAutoPilot ? 'not-allowed' : 'pointer', userSelect: 'none' }}>
            <input 
              type="checkbox"
              checked={params.market_open_focus}
              disabled={aiAutoPilot}
              onChange={(e) => handleChange('market_open_focus', e.target.checked)}
              style={{
                accentColor: 'var(--color-green)',
                width: '14px',
                height: '14px',
                cursor: aiAutoPilot ? 'not-allowed' : 'pointer'
              }}
            />
            🌅 开盘突击
          </label>

          <button 
            onClick={onReset}
            disabled={aiAutoPilot}
            style={{
              background: '#2c2c2e',
              border: 'none',
              color: '#ffffff',
              padding: '4px 10px',
              borderRadius: '4px',
              fontSize: '0.8rem',
              cursor: aiAutoPilot ? 'not-allowed' : 'pointer',
              fontWeight: 600,
              opacity: aiAutoPilot ? 0.5 : 1
            }}
          >
            重置
          </button>
        </div>
      </div>

      <div style={{ 
        display: 'flex', 
        flexDirection: 'column', 
        gap: '1rem',
        opacity: aiAutoPilot ? 0.35 : 1,
        pointerEvents: aiAutoPilot ? 'none' : 'auto',
        transition: 'all 0.3s ease',
        position: 'relative'
      }}>
        {aiAutoPilot && (
          <div style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 10,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'transparent'
          }}>
            <div style={{
              background: 'rgba(0, 0, 0, 0.8)',
              border: '1px solid rgba(0, 200, 5, 0.3)',
              borderRadius: '8px',
              padding: '8px 16px',
              fontSize: '0.8rem',
              fontWeight: 700,
              color: 'var(--color-green)',
              boxShadow: '0 4px 12px rgba(0,0,0,0.5)'
            }}>
              🔒 AI 智能托管进行中
            </div>
          </div>
        )}
        
        {/* 策略选择 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', fontWeight: 600 }}>策略运行模式 (Strategy Mode)</label>
          <select 
            value={params.strategy_mode}
            onChange={(e) => handleChange('strategy_mode', e.target.value)}
            style={{
              background: '#2c2c2e',
              color: '#ffffff',
              border: '1px solid var(--color-border)',
              borderRadius: '6px',
              padding: '8px',
              fontWeight: 600
            }}
          >
            <option value="opening_breakout">🌅 Market Open Breakout (开盘突击区间突破 - 推荐)</option>
            <option value="consensus">Combo Consensus (共振共识策略)</option>
            <option value="dynamic">Regime Dynamic Router (自适应市场路由)</option>
            <option value="ema_cross">EMA Golden/Dead Cross (日内均线交叉)</option>
            <option value="breakout">Intraday Levels Breakout (阻力位突破)</option>
            <option value="patterns">K-Line Patterns (M顶/W底形态反转)</option>
          </select>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
          {/* 左列：止损止盈 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            
            {/* 止损设置 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                <span style={{ color: 'var(--color-text-secondary)', fontWeight: 600 }}>最大硬止损比例</span>
                <span style={{ color: 'var(--color-red)', fontWeight: 700 }}>{(params.stop_loss_pct * 100).toFixed(1)}%</span>
              </div>
              <input 
                type="range" 
                min="0.005" 
                max="0.05" 
                step="0.005"
                value={params.stop_loss_pct}
                onChange={(e) => handleChange('stop_loss_pct', parseFloat(e.target.value))}
                style={{ accentColor: 'var(--color-green)' }}
              />
            </div>

            {/* 止盈设置 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                <span style={{ color: 'var(--color-text-secondary)', fontWeight: 600 }}>硬性止盈目标</span>
                <span style={{ color: 'var(--color-green)', fontWeight: 700 }}>{(params.profit_target_pct * 100).toFixed(1)}%</span>
              </div>
              <input 
                type="range" 
                min="0.005" 
                max="0.10" 
                step="0.005"
                value={params.profit_target_pct}
                onChange={(e) => handleChange('profit_target_pct', parseFloat(e.target.value))}
                style={{ accentColor: 'var(--color-green)' }}
              />
            </div>

            {/* RSI 阈值 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                <span style={{ color: 'var(--color-text-secondary)', fontWeight: 600 }}>买入超买 RSI 过滤</span>
                <span style={{ fontWeight: 700 }}>RSI &lt; {params.rsi_threshold_buy}</span>
              </div>
              <input 
                type="range" 
                min="50" 
                max="80" 
                step="1"
                value={params.rsi_threshold_buy}
                onChange={(e) => handleChange('rsi_threshold_buy', parseInt(e.target.value))}
                style={{ accentColor: 'var(--color-green)' }}
              />
            </div>

          </div>

          {/* 右列：追踪止损与仓位控制 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            
            {/* 追踪止损模式 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', fontWeight: 600 }}>移动追踪止损模式 (Trailing Stop)</label>
              <select 
                value={params.trailing_stop_mode}
                onChange={(e) => handleChange('trailing_stop_mode', e.target.value)}
                style={{
                  background: '#2c2c2e',
                  color: '#ffffff',
                  border: '1px solid var(--color-border)',
                  borderRadius: '6px',
                  padding: '6px',
                  fontWeight: 600
                }}
              >
                <option value="atr">ATR 动态波幅追踪 (推荐)</option>
                <option value="flat">最高点固定百分比回撤</option>
                <option value="none">无追踪止损 (只用硬止损)</option>
              </select>
            </div>

            {/* ATR 乘数 */}
            {params.trailing_stop_mode === 'atr' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                  <span style={{ color: 'var(--color-text-secondary)', fontWeight: 600 }}>ATR 追踪宽度乘数</span>
                  <span style={{ color: '#ff9800', fontWeight: 700 }}>{params.trailing_stop_atr_mult.toFixed(1)} * ATR</span>
                </div>
                <input 
                  type="range" 
                  min="1.0" 
                  max="5.0" 
                  step="0.1"
                  value={params.trailing_stop_atr_mult}
                  onChange={(e) => handleChange('trailing_stop_atr_mult', parseFloat(e.target.value))}
                  style={{ accentColor: 'var(--color-green)' }}
                />
              </div>
            )}

            {/* 仓位管理模式 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', fontWeight: 600 }}>仓位大小控制 (Sizing Mode)</label>
              <select 
                value={params.position_sizing_mode}
                onChange={(e) => handleChange('position_sizing_mode', e.target.value)}
                style={{
                  background: '#2c2c2e',
                  color: '#ffffff',
                  border: '1px solid var(--color-border)',
                  borderRadius: '6px',
                  padding: '6px',
                  fontWeight: 600
                }}
              >
                <option value="atr">ATR 波动率风险对齐仓位 (专业级)</option>
                <option value="flat">固定单只上限比例 (默认 50%)</option>
              </select>
            </div>

            {/* 风险占比 (只在 ATR 模式展示) */}
            {params.position_sizing_mode === 'atr' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                  <span style={{ color: 'var(--color-text-secondary)', fontWeight: 600 }}>单笔交易允许最大亏损比例</span>
                  <span style={{ color: 'var(--color-red)', fontWeight: 700 }}>{(params.risk_per_trade_pct * 100).toFixed(1)}%</span>
                </div>
                <input 
                  type="range" 
                  min="0.005" 
                  max="0.03" 
                  step="0.005"
                  value={params.risk_per_trade_pct}
                  onChange={(e) => handleChange('risk_per_trade_pct', parseFloat(e.target.value))}
                  style={{ accentColor: 'var(--color-green)' }}
                />
              </div>
            )}

            {/* 最大持仓比例上限 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                <span style={{ color: 'var(--color-text-secondary)', fontWeight: 600 }}>单只股票最大持仓资金比</span>
                <span style={{ fontWeight: 700 }}>{(params.max_position_size_pct * 100).toFixed(0)}%</span>
              </div>
              <input 
                type="range" 
                min="0.10" 
                max="1.00" 
                step="0.05"
                value={params.max_position_size_pct}
                onChange={(e) => handleChange('max_position_size_pct', parseFloat(e.target.value))}
                style={{ accentColor: 'var(--color-green)' }}
              />
            </div>

          </div>
        </div>

        {/* 交易摩擦与费用设置 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', borderTop: '1px solid var(--color-border)', paddingTop: '1rem', marginTop: '0.5rem' }}>
          
          {/* 左列：佣金费率 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
              <span style={{ color: 'var(--color-text-secondary)', fontWeight: 600 }}>每股交易佣金 (Commission per Share)</span>
              <span style={{ color: params.commission_per_share === 0 ? 'var(--color-green)' : '#ffffff', fontWeight: 700 }}>
                {params.commission_per_share === 0 ? '免佣金 ($0.00)' : `$${params.commission_per_share.toFixed(3)}`}
              </span>
            </div>
            <input 
              type="range" 
              min="0.00" 
              max="0.015" 
              step="0.001"
              value={params.commission_per_share}
              onChange={(e) => handleChange('commission_per_share', parseFloat(e.target.value))}
              style={{ accentColor: 'var(--color-green)' }}
            />
          </div>

          {/* 右列：滑点损耗 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
              <span style={{ color: 'var(--color-text-secondary)', fontWeight: 600 }}>滑点损耗比例 (Slippage Rate)</span>
              <span style={{ color: params.slippage_rate === 0 ? 'var(--color-green)' : '#ffffff', fontWeight: 700 }}>
                {params.slippage_rate === 0 ? '无滑点损耗 (0%)' : `${(params.slippage_rate * 100).toFixed(2)}%`}
              </span>
            </div>
            <input 
              type="range" 
              min="0.00" 
              max="0.0010" 
              step="0.0001"
              value={params.slippage_rate}
              onChange={(e) => handleChange('slippage_rate', parseFloat(e.target.value))}
              style={{ accentColor: 'var(--color-green)' }}
            />
          </div>

        </div>

      </div>
    </div>
  );
};
