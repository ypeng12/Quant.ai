// frontend/src/components/BrokerPanel.tsx

import React, { useState, useEffect } from 'react';

interface AccountSummary {
  success: boolean;
  account_number: string;
  status: string;
  cash: number;
  portfolio_value: number;
  buying_power: number;
  equity: number;
}

interface BrokerPosition {
  ticker: string;
  shares: number;
  avg_entry_price: number;
  market_value: number;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
}

export function BrokerPanel() {
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [positions, setPositions] = useState<BrokerPosition[]>([]);
  const [isBotRunning, setIsBotRunning] = useState<boolean>(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Poll status, account, and positions
  const fetchBrokerData = async () => {
    try {
      // 1. Fetch account stats
      const accRes = await fetch('http://127.0.0.1:8000/api/broker/account');
      const accJson = await accRes.json();
      if (accJson.success !== false) {
        setAccount(accJson);
        setErrorMsg(null);
      } else {
        setErrorMsg(accJson.error || "无法获取 Alpaca 账户信息，请检查 Keys 配置。");
      }

      // 2. Fetch positions
      const posRes = await fetch('http://127.0.0.1:8000/api/broker/positions');
      const posJson = await posRes.json();
      if (posJson.success) {
        setPositions(posJson.positions);
      }

      // 3. Fetch bot status and logs
      const statusRes = await fetch('http://127.0.0.1:8000/api/live/status');
      const statusJson = await statusRes.json();
      if (statusJson.success) {
        setIsBotRunning(statusJson.status.is_running);
        setLogs(statusJson.logs);
      }

    } catch (e) {
      console.error("Error fetching broker data:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBrokerData();
    const interval = setInterval(fetchBrokerData, 3000); // Poll every 3 seconds
    return () => clearInterval(interval);
  }, []);

  const handleStartBot = async () => {
    setActionLoading("start");
    try {
      const res = await fetch('http://127.0.0.1:8000/api/live/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ignore_market_hours: true })
      });
      const json = await res.json();
      if (json.success) {
        setIsBotRunning(json.status.is_running);
        setLogs(json.logs || []);
      } else {
        alert("启动失败: " + (json.status?.logs?.[json.status.logs.length - 1] || "错误。"));
      }
    } catch (e) {
      alert("请求失败");
    } finally {
      setActionLoading(null);
      fetchBrokerData();
    }
  };

  const handleStopBot = async () => {
    setActionLoading("stop");
    try {
      const res = await fetch('http://127.0.0.1:8000/api/live/stop', { method: 'POST' });
      const json = await res.json();
      setIsBotRunning(json.status.is_running);
    } catch (e) {
      alert("请求失败");
    } finally {
      setActionLoading(null);
      fetchBrokerData();
    }
  };

  const handleCancelAllOrders = async () => {
    if (!window.confirm("确定要撤销 Alpaca 账户中的所有未成交挂单吗？")) return;
    setActionLoading("cancel_orders");
    try {
      const res = await fetch('http://127.0.0.1:8000/api/broker/cancel_orders', { method: 'POST' });
      const json = await res.json();
      alert(json.message || "撤单请求已发送");
    } catch (e) {
      alert("撤单失败");
    } finally {
      setActionLoading(null);
      fetchBrokerData();
    }
  };

  const handleForceLiquidate = async () => {
    if (!window.confirm("🚨 警告：这会以市价立即平仓所有股票持仓！确定继续吗？")) return;
    setActionLoading("liquidate");
    try {
      const res = await fetch('http://127.0.0.1:8000/api/broker/close_positions', { method: 'POST' });
      const json = await res.json();
      alert(json.message || "清仓请求已发送");
    } catch (e) {
      alert("平仓失败");
    } finally {
      setActionLoading(null);
      fetchBrokerData();
    }
  };

  // Extract key action events for clean visual feed
  const getActionFeeds = () => {
    const actionLogs = logs.filter(l => 
      l.includes('触发买入') || l.includes('触发卖出') || l.includes('买单提交') || l.includes('平仓单提交') || l.includes('开始新一轮')
    );
    return actionLogs.slice(-6).reverse(); // Latest 6 events
  };

  const actionFeeds = getActionFeeds();

  if (loading && !account) {
    return (
      <div className="loader-container" style={{ padding: '4rem', textAlign: 'center' }}>
        正在连接 Alpaca 账户...
      </div>
    );
  }

  if (errorMsg) {
    return (
      <div className="card" style={{ padding: '2.5rem', textAlign: 'center', border: '1px solid var(--color-red)', background: 'rgba(255, 59, 48, 0.05)' }}>
        <h3 style={{ color: 'var(--color-red)', marginTop: 0, fontSize: '1.2rem' }}>🔌 Alpaca 账户未连接</h3>
        <p style={{ color: '#e5e5e7', fontSize: '0.95rem', margin: '15px 0' }}>{errorMsg}</p>
        <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
          请在配置文件 <code style={{ color: '#fff', background: '#111', padding: '2px 6px', borderRadius: '4px' }}>backend/.env</code> 中添加您的 Alpaca API Key。
        </div>
      </div>
    );
  }

  return (
    <div className="fade-in">
      {/* 顶部一键托管大操作卡片 */}
      <div 
        className="card" 
        style={{ 
          marginBottom: '1.5rem', 
          padding: '1.5rem 2rem',
          background: isBotRunning 
            ? 'linear-gradient(135deg, rgba(0, 200, 5, 0.08) 0%, rgba(9, 9, 11, 0.95) 100%)' 
            : 'linear-gradient(135deg, #18181b 0%, #09090b 100%)',
          border: isBotRunning ? '1px solid rgba(0, 200, 5, 0.4)' : '1px solid var(--color-border)',
          display: 'flex',
          justify: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1.5rem'
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
            <div style={{
              width: '12px',
              height: '12px',
              borderRadius: '50%',
              background: isBotRunning ? 'var(--color-green)' : '#8e8e93',
              boxShadow: isBotRunning ? '0 0 12px var(--color-green)' : 'none'
            }}></div>
            <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 900, color: '#ffffff' }}>
              {isBotRunning ? '⚡ AI 量化托管交易中' : '⏸️ 托管交易已暂停'}
            </h2>
          </div>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
            {isBotRunning 
              ? '系统正在后台以 1分钟 频率高频评估行情，满足形态与突破信号时将直接提交订单至您的 Alpaca 账户。' 
              : '点击右侧按钮启动 AI 托管。开启后无需手动干预，全自动执行买卖与动态风控。'}
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          {!isBotRunning ? (
            <button 
              onClick={handleStartBot}
              disabled={actionLoading !== null}
              style={{
                background: 'var(--color-green)',
                color: '#000000',
                fontWeight: 900,
                fontSize: '1.05rem',
                padding: '12px 28px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                boxShadow: '0 4px 20px rgba(0, 200, 5, 0.3)',
                transition: 'all 0.2s ease'
              }}
            >
              {actionLoading === "start" ? "⏳ 启动中..." : "▶️ 开启 AI 托管买卖"}
            </button>
          ) : (
            <button 
              onClick={handleStopBot}
              disabled={actionLoading !== null}
              style={{
                background: '#3a3a3c',
                color: '#ffffff',
                fontWeight: 800,
                fontSize: '1rem',
                padding: '12px 24px',
                borderRadius: '8px',
                border: '1px solid #48484a',
                cursor: 'pointer'
              }}
            >
              {actionLoading === "stop" ? "⏳ 停止中..." : "⏸️ 暂停 AI 托管"}
            </button>
          )}
        </div>
      </div>

      {/* 极简资产大字报 */}
      {account && (
        <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
          <div className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1.25rem' }}>
            <span className="stat-label">总资产净值 (Equity)</span>
            <span className="stat-value" style={{ fontSize: '1.5rem', fontWeight: 900 }}>
              ${account.equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1.25rem' }}>
            <span className="stat-label">可用现金 (Cash)</span>
            <span className="stat-value" style={{ fontSize: '1.5rem', fontWeight: 900, color: 'var(--color-green)' }}>
              ${account.cash.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1.25rem' }}>
            <span className="stat-label">持仓证券总额</span>
            <span className="stat-value" style={{ fontSize: '1.5rem', fontWeight: 900 }}>
              ${(account.equity - account.cash).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1.25rem' }}>
            <span className="stat-label">可用购买力 (4x Power)</span>
            <span className="stat-value" style={{ fontSize: '1.5rem', fontWeight: 900, color: '#e5e5e7' }}>
              ${account.buying_power.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
        </div>
      )}

      {/* 持仓卡片 + 交易动态卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: '1.5rem' }}>
        
        {/* Alpaca 持仓大盘 */}
        <div className="card" style={{ padding: '1.25rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 800, color: '#ffffff' }}>
              📋 Alpaca 账户当前持仓 (Live Positions)
            </h3>
            <span style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)' }}>
              模拟盘账号: <strong>{account?.account_number}</strong>
            </span>
          </div>

          {positions.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'var(--color-text-secondary)', padding: '3.5rem 0', fontSize: '0.85rem' }}>
              目前保持空仓防守中。当机器人检测到突破买入信号时，会自动建立仓位并在此展示。
            </div>
          ) : (
            <table className="ledger-table" style={{ fontSize: '0.85rem' }}>
              <thead>
                <tr>
                  <th>代码</th>
                  <th>持股数</th>
                  <th>建仓均价</th>
                  <th>最新现价</th>
                  <th style={{ textAlign: 'right' }}>浮动盈亏</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => {
                  const isUp = pos.unrealized_pnl >= 0;
                  return (
                    <tr key={pos.ticker}>
                      <td style={{ fontWeight: 900, color: '#fff' }}>{pos.ticker}</td>
                      <td>{pos.shares} 股</td>
                      <td>${pos.avg_entry_price.toFixed(2)}</td>
                      <td>${pos.current_price.toFixed(2)}</td>
                      <td style={{ textAlign: 'right', fontWeight: 800, color: isUp ? 'var(--color-green)' : 'var(--color-red)' }}>
                        {isUp ? '+' : ''}${pos.unrealized_pnl.toFixed(2)} ({isUp ? '+' : ''}{pos.unrealized_pnl_pct.toFixed(2)}%)
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* 极简最新交易买卖动态 (Feed) */}
        <div className="card" style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          <div>
            <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', fontWeight: 800, color: '#ffffff' }}>
              ⚡ 机器人最新买卖动态 (Action Feed)
            </h3>

            {actionFeeds.length === 0 ? (
              <div style={{ color: 'var(--color-text-secondary)', fontSize: '0.85rem', padding: '2rem 0', textAlign: 'center' }}>
                启动 AI 托管后，最新的买卖通知卡片将在此实时呈现。
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {actionFeeds.map((feed, idx) => (
                  <div 
                    key={idx} 
                    style={{
                      background: '#141416',
                      border: feed.includes('买单') || feed.includes('买入') ? '1px solid rgba(0, 200, 5, 0.3)' : '1px solid #333',
                      borderRadius: '8px',
                      padding: '10px 14px',
                      fontSize: '0.8rem',
                      color: feed.includes('买单') || feed.includes('买入') ? 'var(--color-green)' : (feed.includes('卖') || feed.includes('平仓') ? 'var(--color-red)' : '#ffffff'),
                      lineHeight: 1.4
                    }}
                  >
                    {feed}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 底部应急操作按钮区 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginTop: '1.5rem', paddingTop: '1rem', borderTop: '1px solid var(--color-border)' }}>
            <button 
              onClick={handleCancelAllOrders}
              disabled={actionLoading !== null}
              style={{
                background: 'rgba(255, 149, 0, 0.1)',
                border: '1px solid #ff9500',
                color: '#ff9500',
                padding: '8px 12px',
                borderRadius: '6px',
                fontSize: '0.8rem',
                fontWeight: 700,
                cursor: 'pointer'
              }}
            >
              📯 撤销所有挂单
            </button>
            <button 
              onClick={handleForceLiquidate}
              disabled={actionLoading !== null}
              style={{
                background: 'rgba(255, 59, 48, 0.15)',
                border: '1px solid var(--color-red)',
                color: 'var(--color-red)',
                padding: '8px 12px',
                borderRadius: '6px',
                fontSize: '0.8rem',
                fontWeight: 800,
                cursor: 'pointer'
              }}
            >
              🚨 一键紧急全平仓
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
