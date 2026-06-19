// frontend/src/components/WalkForwardPanel.tsx

import React, { useState } from 'react';

interface WalkForwardPanelProps {
  activeTicker: string;
}

interface OOSResult {
  window: number;
  train_period: string;
  test_period: string;
  best_params: {
    strategy_mode: string;
    trailing_stop_atr_mult: number;
    rsi_threshold_buy: number;
    stop_loss_pct: number;
    profit_target_pct: number;
  };
  is_sharpe: number;
  oos_sharpe: number;
  net_pnl: number;
  max_drawdown: number;
  round_trips: number;
  win_rate: number;
  commission: number;
}

interface WFResult {
  success: boolean;
  ticker: string;
  interval: string;
  period: string;
  oos_results: OOSResult[];
  correlation: number;
  is_overfitted: boolean;
  static_control: {
    net_pnl: number;
    pnl_pct: number;
    round_trips: number;
    commission: number;
    max_drawdown: number;
    sharpe: number;
  };
  summary: {
    total_wf_pnl: number;
    total_wf_commission: number;
    avg_wf_drawdown: number;
    total_wf_trades: number;
    avg_is_sharpe: number;
    avg_oos_sharpe: number;
  };
}

export const WalkForwardPanel: React.FC<WalkForwardPanelProps> = ({ activeTicker }) => {
  const [ticker, setTicker] = useState(activeTicker.toUpperCase());
  const [interval, setIntervalVal] = useState('1d');
  const [period, setPeriod] = useState('1y');
  const [trainSize, setTrainSize] = useState(120);
  const [testSize, setTestSize] = useState(40);
  
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [result, setResult] = useState<WFResult | null>(null);

  const handleRunWF = async () => {
    setIsLoading(true);
    setErrorMsg('');
    setResult(null);

    try {
      const response = await fetch('http://127.0.0.1:8000/api/walk_forward', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker: ticker.toUpperCase().trim(),
          interval,
          period,
          train_size: trainSize,
          test_size: testSize,
        }),
      });

      const data = await response.json();
      if (data.success) {
        setResult(data);
      } else {
        setErrorMsg(data.error || '运行 Walk-Forward 优化失败');
      }
    } catch (err) {
      setErrorMsg('无法连接到后端服务器，请检查 FastAPI 服务是否在 127.0.0.1:8000 启动。');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      {/* 顶部配置卡片 */}
      <div className="card">
        <h3 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          🔄 Walk-Forward 滚动参数优化
        </h3>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem', margin: '-0.5rem 0 1.5rem 0' }}>
          样本外滚动优化 (Walk-Forward Optimization) 可以避免回测的“后视镜”偏差。系统使用历史的一段区间寻找最佳参数，并在接下来的区间进行真实样本外检验。
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1.2rem', marginBottom: '1.5rem' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>股票代码 (Ticker)</label>
            <input
              type="text"
              className="strategy-input"
              style={{ width: '100%', boxSizing: 'border-box' }}
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
            />
          </div>
          <div>
            <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>K线周期 (Interval)</label>
            <select
              className="strategy-input"
              style={{ width: '100%' }}
              value={interval}
              onChange={(e) => setIntervalVal(e.target.value)}
            >
              <option value="1m">1分钟 (1m)</option>
              <option value="5m">5分钟 (5m)</option>
              <option value="15m">15分钟 (15m)</option>
              <option value="30m">30分钟 (30m)</option>
              <option value="1h">1小时 (1h)</option>
              <option value="1d">日线 (1d)</option>
            </select>
          </div>
          <div>
            <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>历史区间 (Period)</label>
            <select
              className="strategy-input"
              style={{ width: '100%' }}
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
            >
              <option value="5d">5天 (5d)</option>
              <option value="1mo">1个月 (1mo)</option>
              <option value="3mo">3个月 (3mo)</option>
              <option value="6mo">6个月 (6mo)</option>
              <option value="1y">1年 (1y)</option>
              <option value="2y">2年 (2y)</option>
            </select>
          </div>
          <div>
            <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>训练集根数 (Train Size)</label>
            <input
              type="number"
              className="strategy-input"
              style={{ width: '100%', boxSizing: 'border-box' }}
              value={trainSize}
              onChange={(e) => setTrainSize(Number(e.target.value))}
            />
          </div>
          <div>
            <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>测试集根数 (Test Size)</label>
            <input
              type="number"
              className="strategy-input"
              style={{ width: '100%', boxSizing: 'border-box' }}
              value={testSize}
              onChange={(e) => setTestSize(Number(e.target.value))}
            />
          </div>
        </div>

        <button
          className="run-btn"
          style={{ width: '100%', padding: '12px', fontSize: '1rem', fontWeight: 'bold' }}
          disabled={isLoading}
          onClick={handleRunWF}
        >
          {isLoading ? '正在滚动优化参数中 (可能需要 10-30 秒)...' : '🚀 运行 Walk-Forward 滚动参数优化'}
        </button>

        {errorMsg && (
          <div style={{ padding: '12px', backgroundColor: 'rgba(255, 59, 48, 0.15)', border: '1px solid var(--color-red)', borderRadius: '6px', color: 'var(--color-red)', marginTop: '1rem', fontSize: '0.9rem' }}>
            ⚠️ {errorMsg}
          </div>
        )}
      </div>

      {/* 结果显示 */}
      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
          {/* 过拟合警告 */}
          {result.is_overfitted && (
            <div style={{ padding: '1rem', backgroundColor: 'rgba(255, 59, 48, 0.15)', border: '1px solid var(--color-red)', borderRadius: '8px', color: '#ff817d' }}>
              <h4 style={{ margin: '0 0 0.5rem 0', fontWeight: 'bold' }}>⚠️ 参数过拟合警报 (Overfitting Risk Alert)</h4>
              <p style={{ margin: 0, fontSize: '0.9rem' }}>
                优化算法检测到训练集平均 Sharpe ({result.summary.avg_is_sharpe}) 表现优秀，但在样本外测试集中表现急剧退化 (平均 Sharpe: {result.summary.avg_oos_sharpe})。
                且 IS 与 OOS Sharpe 的相关性为 {result.correlation}。这高度说明当前优化的策略参数在过度拟合历史噪声，建议增加过滤器、减少网格参数或放宽滑点控制。
              </p>
            </div>
          )}

          {/* 并排对比卡片 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
            {/* Walk Forward Summary */}
            <div className="card">
              <h3 className="card-title" style={{ color: 'var(--color-green)' }}>🧪 Walk-Forward 滚动外表现</h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginTop: '1rem' }}>
                <div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>样本外总盈亏</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: 800, color: result.summary.total_wf_pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
                    ${result.summary.total_wf_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>平均滚动最大回撤</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: 800, color: 'var(--color-red)' }}>
                    {(result.summary.avg_wf_drawdown * 100).toFixed(2)}%
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>总交易笔数</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 700 }}>{result.summary.total_wf_trades} 笔</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>平均 OOS Sharpe</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 700, color: result.summary.avg_oos_sharpe >= 0.5 ? 'var(--color-green)' : 'inherit' }}>
                    {result.summary.avg_oos_sharpe.toFixed(2)}
                  </div>
                </div>
              </div>
            </div>

            {/* Static Control */}
            <div className="card">
              <h3 className="card-title">📉 静态默认参数 (全历史对照组)</h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginTop: '1rem' }}>
                <div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>累计净利润</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: 800, color: result.static_control.net_pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
                    ${result.static_control.net_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>全历史最大回撤</div>
                  <div style={{ fontSize: '1.8rem', fontWeight: 800, color: 'var(--color-red)' }}>
                    {(result.static_control.max_drawdown * 100).toFixed(2)}%
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>总交易笔数</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 700 }}>{result.static_control.round_trips} 笔</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>静态 Sharpe 比率</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 700 }}>{result.static_control.sharpe.toFixed(2)}</div>
                </div>
              </div>
            </div>
          </div>

          {/* 表格 */}
          <div className="card" style={{ overflowX: 'auto' }}>
            <h3 className="card-title">滚动时间窗口明细 (Rolling Windows Details)</h3>
            <table className="ledger-table">
              <thead>
                <tr>
                  <th>窗口</th>
                  <th>训练时间段 (In-Sample)</th>
                  <th>测试时间段 (Out-of-Sample)</th>
                  <th>最佳优化参数</th>
                  <th>IS Sharpe</th>
                  <th>OOS Sharpe</th>
                  <th>样本外盈亏</th>
                  <th style={{ textAlign: 'right' }}>样本外最大回撤</th>
                </tr>
              </thead>
              <tbody>
                {result.oos_results.map((row) => (
                  <tr key={row.window}>
                    <td>#{row.window}</td>
                    <td style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>{row.train_period}</td>
                    <td style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>{row.test_period}</td>
                    <td style={{ fontSize: '0.85rem', fontWeight: 700 }}>
                      {row.best_params.strategy_mode} (ATR:{row.best_params.trailing_stop_atr_mult}x, RSI:{row.best_params.rsi_threshold_buy})
                    </td>
                    <td style={{ color: 'var(--color-green)' }}>{row.is_sharpe.toFixed(2)}</td>
                    <td style={{ color: row.oos_sharpe >= 0.5 ? 'var(--color-green)' : (row.oos_sharpe < 0 ? 'var(--color-red)' : 'inherit'), fontWeight: 700 }}>
                      {row.oos_sharpe.toFixed(2)}
                    </td>
                    <td style={{ color: row.net_pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
                      ${row.net_pnl.toFixed(2)}
                    </td>
                    <td style={{ textAlign: 'right', color: 'var(--color-red)' }}>
                      {(row.max_drawdown * 100).toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
