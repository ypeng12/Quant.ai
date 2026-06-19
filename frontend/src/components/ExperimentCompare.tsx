// frontend/src/components/ExperimentCompare.tsx

import React, { useEffect, useState } from 'react';

interface Experiment {
  id: number;
  name: string;
  timestamp: string;
  ticker: string;
  interval: string;
  strategy_mode: string;
  metrics: {
    initial_cash: number;
    final_equity: number;
    net_pnl: number;
    pnl_pct: number;
    total_trades: number;
    round_trips: number;
    win_rate: number;
    commission: number;
    max_drawdown: number;
    sharpe: number;
    calmar: number;
    cagr: number;
    profit_factor: number;
    gross_profit: number;
    gross_loss: number;
  };
  config: {
    ticker: string;
    interval: string;
    strategy_mode: string;
    stop_loss_pct: number;
    profit_target_pct: number;
    trailing_stop_mode: string;
    trailing_stop_atr_mult: number;
    rsi_threshold_buy: number;
    risk_per_trade_pct: number;
    max_position_size_pct: number;
    position_sizing_mode: string;
    commission_per_share: number;
    slippage_rate: number;
  };
}

export const ExperimentCompare: React.FC = () => {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [comparedExperiments, setComparedExperiments] = useState<Experiment[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const fetchExperiments = async () => {
    setIsLoading(true);
    setErrorMsg('');
    try {
      const res = await fetch('http://127.0.0.1:8000/api/experiments');
      const data = await res.json();
      if (data.success) {
        setExperiments(data.experiments);
      } else {
        setErrorMsg(data.error || '获取实验列表失败');
      }
    } catch (err) {
      setErrorMsg('无法获取实验列表，请检查后端 API 是否已启动于 127.0.0.1:8000');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchExperiments();
  }, []);

  const handleCheckboxChange = (id: number) => {
    if (selectedIds.includes(id)) {
      setSelectedIds(selectedIds.filter((x) => x !== id));
    } else {
      if (selectedIds.length >= 4) {
        alert('最多只能选择 4 个实验进行对比！');
        return;
      }
      setSelectedIds([...selectedIds, id]);
    }
  };

  const handleCompare = async () => {
    if (selectedIds.length === 0) {
      alert('请先选择至少 1 个实验进行对比！');
      return;
    }
    
    setIsLoading(true);
    try {
      const res = await fetch('http://127.0.0.1:8000/api/experiments/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: selectedIds }),
      });
      const data = await res.json();
      if (data.success) {
        // 由于返回的数据中 metrics 和 config 在后端的 compare_experiments 已经是 dict 了，我们可以直接用
        setComparedExperiments(data.results);
      } else {
        alert(data.error || '实验对比失败');
      }
    } catch (err) {
      alert('对比请求失败，请稍后重试');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('您确定要删除这个实验记录吗？')) {
      return;
    }

    try {
      const res = await fetch(`http://127.0.0.1:8000/api/experiments/${id}`, {
        method: 'DELETE',
      });
      const data = await res.json();
      if (data.success) {
        setExperiments(experiments.filter((x) => x.id !== id));
        setSelectedIds(selectedIds.filter((x) => x !== id));
        setComparedExperiments(comparedExperiments.filter((x) => x.id !== id));
      } else {
        alert('删除实验失败');
      }
    } catch (err) {
      alert('删除请求失败');
    }
  };

  const handleClearCompare = () => {
    setComparedExperiments([]);
    setSelectedIds([]);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      {/* 对比展示区 */}
      {comparedExperiments.length > 0 && (
        <div className="card" style={{ position: 'relative' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
            <h3 className="card-title" style={{ margin: 0, color: 'var(--color-green)' }}>🧪 实验多维对比视图</h3>
            <button
              onClick={handleClearCompare}
              style={{
                background: 'transparent',
                border: '1px solid var(--color-border)',
                color: '#ffffff',
                padding: '6px 12px',
                borderRadius: '4px',
                cursor: 'pointer',
              }}
            >
              关闭对比
            </button>
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table className="ledger-table" style={{ borderCollapse: 'collapse', width: '100%' }}>
              <thead>
                <tr>
                  <th style={{ minWidth: '150px' }}>对比指标 / 参数</th>
                  {comparedExperiments.map((exp) => (
                    <th key={exp.id} style={{ textAlign: 'center', borderLeft: '1px solid var(--color-border)' }}>
                      <div style={{ fontWeight: 800 }}>{exp.name}</div>
                      <div style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', fontWeight: 400 }}>
                        {exp.ticker} ({exp.interval}) | {exp.timestamp}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {/* 核心指标 */}
                <tr style={{ backgroundColor: 'rgba(255,255,255,0.02)' }}>
                  <td style={{ fontWeight: 800, color: 'var(--color-green)' }}>核心表现指标 (Metrics)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ borderLeft: '1px solid var(--color-border)' }}></td>
                  ))}
                </tr>
                <tr>
                  <td>净盈亏 (Net PnL)</td>
                  {comparedExperiments.map((exp) => {
                    const val = exp.metrics.net_pnl;
                    return (
                      <td key={exp.id} style={{ textAlign: 'center', fontWeight: 700, color: val >= 0 ? 'var(--color-green)' : 'var(--color-red)', borderLeft: '1px solid var(--color-border)' }}>
                        ${val.toLocaleString(undefined, { minimumFractionDigits: 2 })} ({exp.metrics.pnl_pct.toFixed(2)}%)
                      </td>
                    );
                  })}
                </tr>
                <tr>
                  <td>夏普比率 (Sharpe Ratio)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', fontWeight: 700, color: exp.metrics.sharpe >= 1 ? 'var(--color-green)' : 'inherit', borderLeft: '1px solid var(--color-border)' }}>
                      {exp.metrics.sharpe.toFixed(2)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>卡尔玛比率 (Calmar Ratio)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', borderLeft: '1px solid var(--color-border)' }}>
                      {exp.metrics.calmar.toFixed(2)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>最大回撤 (Max Drawdown)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', color: 'var(--color-red)', fontWeight: 700, borderLeft: '1px solid var(--color-border)' }}>
                      {(exp.metrics.max_drawdown * 100).toFixed(2)}%
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>交易胜率 (Win Rate)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', borderLeft: '1px solid var(--color-border)' }}>
                      {exp.metrics.win_rate.toFixed(1)}%
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>盈亏比 (Profit Factor)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', borderLeft: '1px solid var(--color-border)' }}>
                      {exp.metrics.profit_factor.toFixed(2)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>总交易次数 (Total Trades)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', borderLeft: '1px solid var(--color-border)' }}>
                      {exp.metrics.round_trips} 笔
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>交易手续费 (Commission)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', color: 'var(--color-red)', borderLeft: '1px solid var(--color-border)' }}>
                      ${exp.metrics.commission.toFixed(2)}
                    </td>
                  ))}
                </tr>

                {/* 策略参数对比 */}
                <tr style={{ backgroundColor: 'rgba(255,255,255,0.02)' }}>
                  <td style={{ fontWeight: 800, color: '#4da6ff' }}>策略回测参数 (Parameters)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ borderLeft: '1px solid var(--color-border)' }}></td>
                  ))}
                </tr>
                <tr>
                  <td>策略模式 (Strategy Mode)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', borderLeft: '1px solid var(--color-border)', fontWeight: 700 }}>
                      {exp.strategy_mode}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>固定止损比例 (Stop Loss)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', borderLeft: '1px solid var(--color-border)' }}>
                      {(exp.config.stop_loss_pct * 100).toFixed(2)}%
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>固定止盈目标 (Profit Target)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', borderLeft: '1px solid var(--color-border)' }}>
                      {(exp.config.profit_target_pct * 100).toFixed(2)}%
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>追踪止损 ATR 倍数</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', borderLeft: '1px solid var(--color-border)' }}>
                      {exp.config.trailing_stop_atr_mult}x
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>RSI 买入阀值 (Buy Threshold)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', borderLeft: '1px solid var(--color-border)' }}>
                      {exp.config.rsi_threshold_buy}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>单笔最大风险 (Risk Per Trade)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', borderLeft: '1px solid var(--color-border)' }}>
                      {(exp.config.risk_per_trade_pct * 100).toFixed(2)}%
                    </td>
                  ))}
                </tr>
                <tr>
                  <td>最大仓位上限 (Max Pos Size)</td>
                  {comparedExperiments.map((exp) => (
                    <td key={exp.id} style={{ textAlign: 'center', borderLeft: '1px solid var(--color-border)' }}>
                      {(exp.config.max_position_size_pct * 100).toFixed(2)}%
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 实验列表 */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h3 className="card-title" style={{ margin: 0 }}>🧪 历史回测实验仓</h3>
          <div style={{ display: 'flex', gap: '1rem' }}>
            <button
              className="run-btn"
              style={{ padding: '6px 16px', fontSize: '0.85rem' }}
              onClick={fetchExperiments}
            >
              🔄 刷新列表
            </button>
            <button
              className="run-btn"
              style={{
                padding: '6px 16px',
                fontSize: '0.85rem',
                backgroundColor: selectedIds.length === 0 ? '#555555' : 'var(--color-green)',
                cursor: selectedIds.length === 0 ? 'not-allowed' : 'pointer',
              }}
              disabled={selectedIds.length === 0 || isLoading}
              onClick={handleCompare}
            >
              📊 对比选中实验 ({selectedIds.length})
            </button>
          </div>
        </div>

        {errorMsg && (
          <div style={{ padding: '10px', backgroundColor: 'rgba(255, 59, 48, 0.1)', border: '1px solid var(--color-red)', color: 'var(--color-red)', borderRadius: '4px', marginBottom: '1rem' }}>
            {errorMsg}
          </div>
        )}

        {experiments.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--color-text-secondary)' }}>
            <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>🧪</div>
            <p style={{ margin: 0 }}>暂无保存的实验。请在 Dashboard 中运行策略回测，系统将自动记录，或点击右上角保存。</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="ledger-table">
              <thead>
                <tr>
                  <th style={{ width: '40px', textAlign: 'center' }}>选择</th>
                  <th>实验 ID</th>
                  <th>实验名称</th>
                  <th>时间戳</th>
                  <th>股票代码</th>
                  <th>K线周期</th>
                  <th>策略路由模式</th>
                  <th>回测收益 PnL</th>
                  <th>最大回撤</th>
                  <th>夏普比率</th>
                  <th style={{ textAlign: 'right' }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {experiments.map((exp) => (
                  <tr key={exp.id}>
                    <td style={{ textAlign: 'center' }}>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(exp.id)}
                        onChange={() => handleCheckboxChange(exp.id)}
                        style={{ width: '18px', height: '18px', cursor: 'pointer' }}
                      />
                    </td>
                    <td>#{exp.id}</td>
                    <td style={{ fontWeight: 700 }}>{exp.name}</td>
                    <td style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>{exp.timestamp}</td>
                    <td style={{ fontWeight: 800 }}>{exp.ticker}</td>
                    <td>{exp.interval}</td>
                    <td>
                      <span style={{ fontSize: '0.85rem', backgroundColor: '#2c2c2e', padding: '2px 8px', borderRadius: '4px' }}>
                        {exp.strategy_mode}
                      </span>
                    </td>
                    <td style={{ fontWeight: 700, color: exp.metrics.net_pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
                      ${exp.metrics.net_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })} ({exp.metrics.pnl_pct.toFixed(2)}%)
                    </td>
                    <td style={{ color: 'var(--color-red)' }}>{(exp.metrics.max_drawdown * 100).toFixed(2)}%</td>
                    <td style={{ fontWeight: 700 }}>{exp.metrics.sharpe.toFixed(2)}</td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        onClick={() => handleDelete(exp.id)}
                        style={{
                          background: 'transparent',
                          border: 'none',
                          color: 'var(--color-red)',
                          cursor: 'pointer',
                          fontWeight: 'bold',
                        }}
                      >
                        删除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
