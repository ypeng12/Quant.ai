// frontend/src/components/StrategySettings.tsx

import React from 'react';

export interface StrategyParams {
  strategy_mode: 'consensus' | 'ema_cross' | 'breakout' | 'patterns';
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
}

interface StrategySettingsProps {
  params: StrategyParams;
  onChange: (newParams: StrategyParams) => void;
  onReset: () => void;
}

export const StrategySettings: React.FC<StrategySettingsProps> = ({ params, onChange, onReset }) => {
  const handleChange = (key: keyof StrategyParams, value: any) => {
    onChange({
      ...params,
      [key]: value
    });
  };

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h3 className="card-title" style={{ margin: 0 }}>量化风控设置 (Strategy & Risk Settings)</h3>
        <button 
          onClick={onReset}
          style={{
            background: '#2c2c2e',
            border: 'none',
            color: '#ffffff',
            padding: '4px 10px',
            borderRadius: '4px',
            fontSize: '0.8rem',
            cursor: 'pointer',
            fontWeight: 600
          }}
        >
          重置默认
        </button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        
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
            <option value="consensus">Combo Consensus (共振共识策略 - 推荐)</option>
            <option value="ema_cross">EMA Golden/Dead Cross (日内均线交叉)</option>
            <option value="breakout">Intraday Breakout (盘前/昨日阻力突破)</option>
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
