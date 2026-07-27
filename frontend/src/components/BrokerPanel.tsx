// frontend/src/components/BrokerPanel.tsx

import { useState, useEffect } from 'react';
import { API_BASE } from '../config';

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

interface TradeRecord {
  date: string;
  time: string;
  action: string;
  action_cn: string;
  ticker: string;
  shares: number;
  price: number;
  pnl: number;
  reason: string;
}

interface TodaySummary {
  date: string;
  total_trades: number;
  closed_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  best_trade: number;
  worst_trade: number;
}

type ActiveTab = 'feed' | 'history';

export function BrokerPanel() {
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [positions, setPositions] = useState<BrokerPosition[]>([]);
  const [isBotRunning, setIsBotRunning] = useState<boolean>(false);
  const [actionFeed, setActionFeed] = useState<string[]>([]);
  const [tradeHistory, setTradeHistory] = useState<TradeRecord[]>([]);
  const [todaySummary, setTodaySummary] = useState<TodaySummary | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>('feed');

  const fetchBrokerData = async () => {
    try {
      const [accRes, posRes, statusRes, feedRes, histRes, todayRes] = await Promise.all([
        fetch(`${API_BASE}/api/broker/account`),
        fetch(`${API_BASE}/api/broker/positions`),
        fetch(`${API_BASE}/api/live/status`),
        fetch(`${API_BASE}/api/live/action_feed?limit=50`),
        fetch(`${API_BASE}/api/live/trade_history?days=7`),
        fetch(`${API_BASE}/api/live/today_summary`),
      ]);

      const accJson = await accRes.json();
      if (accJson.success !== false) { setAccount(accJson); setErrorMsg(null); }
      else setErrorMsg(accJson.error || '无法获取账户信息');

      const posJson = await posRes.json();
      if (posJson.success) setPositions(posJson.positions);

      const statusJson = await statusRes.json();
      if (statusJson.success) setIsBotRunning(statusJson.status.is_running);

      const feedJson = await feedRes.json();
      if (feedJson.success) setActionFeed(feedJson.logs || []);

      const histJson = await histRes.json();
      if (histJson.success) setTradeHistory(histJson.trades || []);

      const todayJson = await todayRes.json();
      if (todayJson.success) setTodaySummary(todayJson.summary);

    } catch (e) {
      console.error('Error fetching broker data:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBrokerData();
    const interval = setInterval(fetchBrokerData, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleStartBot = async () => {
    setActionLoading('start');
    try {
      const res = await fetch(`${API_BASE}/api/live/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ignore_market_hours: true })
      });
      const json = await res.json();
      if (json.success) setIsBotRunning(json.status.is_running);
      else alert('启动失败: ' + (json.status?.logs?.[json.status.logs.length - 1] || '错误。'));
    } catch { alert('请求失败'); }
    finally { setActionLoading(null); fetchBrokerData(); }
  };

  const handleStopBot = async () => {
    setActionLoading('stop');
    try {
      const res = await fetch(`${API_BASE}/api/live/stop`, { method: 'POST' });
      const json = await res.json();
      setIsBotRunning(json.status.is_running);
    } catch { alert('请求失败'); }
    finally { setActionLoading(null); fetchBrokerData(); }
  };

  const handleCancelAllOrders = async () => {
    if (!window.confirm('确定要撤销所有未成交挂单吗？')) return;
    setActionLoading('cancel_orders');
    try {
      const res = await fetch(`${API_BASE}/api/broker/cancel_orders`, { method: 'POST' });
      const json = await res.json();
      alert(json.message || '撤单请求已发送');
    } catch { alert('撤单失败'); }
    finally { setActionLoading(null); fetchBrokerData(); }
  };

  const handleForceLiquidate = async () => {
    if (!window.confirm('🚨 这会立即以市价平仓所有持仓！确定继续吗？')) return;
    setActionLoading('liquidate');
    try {
      const res = await fetch(`${API_BASE}/api/broker/close_positions`, { method: 'POST' });
      const json = await res.json();
      alert(json.message || '清仓请求已发送');
    } catch { alert('平仓失败'); }
    finally { setActionLoading(null); fetchBrokerData(); }
  };

  const getActionStyle = (action: string) => {
    if (action === 'BUY') return { border: '1px solid rgba(0,200,5,0.4)', color: '#00c805', bg: 'rgba(0,200,5,0.04)' };
    if (action === 'SHORT') return { border: '1px solid rgba(255,59,48,0.5)', color: '#ff6b6b', bg: 'rgba(255,59,48,0.05)' };
    if (action === 'SELL') return { border: '1px solid rgba(255,149,0,0.4)', color: '#ff9500', bg: 'rgba(255,149,0,0.04)' };
    if (action === 'COVER') return { border: '1px solid rgba(100,180,255,0.4)', color: '#64b4ff', bg: 'rgba(100,180,255,0.04)' };
    return { border: '1px solid #333', color: '#888', bg: 'transparent' };
  };

  if (loading && !account) {
    return <div className="loader-container" style={{ padding: '4rem', textAlign: 'center' }}>正在连接 Alpaca 账户...</div>;
  }

  if (errorMsg) {
    return (
      <div className="card" style={{ padding: '2.5rem', textAlign: 'center', border: '1px solid var(--color-red)', background: 'rgba(255,59,48,0.05)' }}>
        <h3 style={{ color: 'var(--color-red)', marginTop: 0 }}>🔌 Alpaca 账户未连接</h3>
        <p style={{ color: '#e5e5e7', fontSize: '0.95rem' }}>{errorMsg}</p>
        <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
          请在 <code style={{ color: '#fff', background: '#111', padding: '2px 6px', borderRadius: '4px' }}>backend/.env</code> 中配置 Alpaca API Key。
        </div>
      </div>
    );
  }

  const todayPnlPositive = (todaySummary?.total_pnl ?? 0) >= 0;

  return (
    <div className="fade-in">
      {/* 顶部 AI 托管控制卡 */}
      <div className="card" style={{
        marginBottom: '1.5rem', padding: '1.5rem 2rem',
        background: isBotRunning
          ? 'linear-gradient(135deg, rgba(0,200,5,0.08) 0%, rgba(9,9,11,0.95) 100%)'
          : 'linear-gradient(135deg, #18181b 0%, #09090b 100%)',
        border: isBotRunning ? '1px solid rgba(0,200,5,0.4)' : '1px solid var(--color-border)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1.5rem'
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
            <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: isBotRunning ? 'var(--color-green)' : '#8e8e93', boxShadow: isBotRunning ? '0 0 12px var(--color-green)' : 'none' }} />
            <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 900, color: '#ffffff' }}>
              {isBotRunning ? '⚡ AI 量化托管交易中' : '⏸️ 托管交易已暂停'}
            </h2>
          </div>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
            {isBotRunning
              ? '系统每 30 秒高频评估做多/做空信号，满足条件时直接向 Alpaca 提交多空双向订单。'
              : '点击右侧按钮启动 AI 托管。开启后全自动执行多空买卖与动态风控。'}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          {!isBotRunning ? (
            <button onClick={handleStartBot} disabled={actionLoading !== null} style={{ background: 'var(--color-green)', color: '#000', fontWeight: 900, fontSize: '1.05rem', padding: '12px 28px', borderRadius: '8px', border: 'none', cursor: 'pointer', boxShadow: '0 4px 20px rgba(0,200,5,0.3)' }}>
              {actionLoading === 'start' ? '⏳ 启动中...' : '▶️ 开启 AI 托管买卖'}
            </button>
          ) : (
            <button onClick={handleStopBot} disabled={actionLoading !== null} style={{ background: '#3a3a3c', color: '#fff', fontWeight: 800, fontSize: '1rem', padding: '12px 24px', borderRadius: '8px', border: '1px solid #48484a', cursor: 'pointer' }}>
              {actionLoading === 'stop' ? '⏳ 停止中...' : '⏸️ 暂停 AI 托管'}
            </button>
          )}
        </div>
      </div>

      {/* 今日盈亏摘要 */}
      {todaySummary && (
        <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(5, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
          <div className="stat-card" style={{ background: '#09090b', border: `1px solid ${todayPnlPositive ? 'rgba(0,200,5,0.3)' : 'rgba(255,59,48,0.3)'}`, padding: '1.25rem' }}>
            <span className="stat-label">今日总盈亏</span>
            <span className="stat-value" style={{ fontSize: '1.4rem', fontWeight: 900, color: todayPnlPositive ? 'var(--color-green)' : 'var(--color-red)' }}>
              {todayPnlPositive ? '+' : ''}${todaySummary.total_pnl.toFixed(2)}
            </span>
          </div>
          <div className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1.25rem' }}>
            <span className="stat-label">胜率</span>
            <span className="stat-value" style={{ fontSize: '1.4rem', fontWeight: 900, color: todaySummary.win_rate >= 50 ? 'var(--color-green)' : 'var(--color-red)' }}>
              {todaySummary.win_rate.toFixed(1)}%
            </span>
          </div>
          <div className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1.25rem' }}>
            <span className="stat-label">盈利 / 亏损</span>
            <span className="stat-value" style={{ fontSize: '1.4rem', fontWeight: 900 }}>
              <span style={{ color: 'var(--color-green)' }}>{todaySummary.wins}</span>
              <span style={{ color: '#555', margin: '0 4px' }}>/</span>
              <span style={{ color: 'var(--color-red)' }}>{todaySummary.losses}</span>
            </span>
          </div>
          <div className="stat-card" style={{ background: '#09090b', border: '1px solid rgba(0,200,5,0.2)', padding: '1.25rem' }}>
            <span className="stat-label">最佳单笔</span>
            <span className="stat-value" style={{ fontSize: '1.3rem', fontWeight: 900, color: 'var(--color-green)' }}>
              +${todaySummary.best_trade.toFixed(2)}
            </span>
          </div>
          <div className="stat-card" style={{ background: '#09090b', border: '1px solid rgba(255,59,48,0.2)', padding: '1.25rem' }}>
            <span className="stat-label">最差单笔</span>
            <span className="stat-value" style={{ fontSize: '1.3rem', fontWeight: 900, color: 'var(--color-red)' }}>
              ${todaySummary.worst_trade.toFixed(2)}
            </span>
          </div>
        </div>
      )}

      {/* 资产概况 */}
      {account && (
        <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
          {[
            { label: '总资产净值', value: `$${account.equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, color: undefined },
            { label: '可用现金', value: `$${account.cash.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, color: 'var(--color-green)' },
            { label: '持仓总额', value: `$${(account.equity - account.cash).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, color: undefined },
            { label: '可用购买力', value: `$${account.buying_power.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, color: '#e5e5e7' },
          ].map(({ label, value, color }) => (
            <div key={label} className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1.25rem' }}>
              <span className="stat-label">{label}</span>
              <span className="stat-value" style={{ fontSize: '1.5rem', fontWeight: 900, color }}>{value}</span>
            </div>
          ))}
        </div>
      )}

      {/* 持仓 + 交易面板 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '1.5rem' }}>
        {/* 持仓表格 */}
        <div className="card" style={{ padding: '1.25rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 800, color: '#fff' }}>📋 当前持仓 (Live Positions)</h3>
            <span style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)' }}>账号: <strong>{account?.account_number}</strong></span>
          </div>
          {positions.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'var(--color-text-secondary)', padding: '3.5rem 0', fontSize: '0.85rem' }}>
              目前空仓防守中。AI 检测到买入/做空信号时将自动建仓并在此展示。
            </div>
          ) : (
            <table className="ledger-table" style={{ fontSize: '0.85rem' }}>
              <thead>
                <tr>
                  <th>代码</th><th>方向</th><th>持股数</th><th>建仓均价</th><th>最新价</th><th style={{ textAlign: 'right' }}>浮动盈亏</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => {
                  const isUp = pos.unrealized_pnl >= 0;
                  const isShort = pos.shares < 0;
                  return (
                    <tr key={pos.ticker}>
                      <td style={{ fontWeight: 900, color: '#fff' }}>{pos.ticker}</td>
                      <td><span style={{ fontSize: '0.75rem', padding: '2px 6px', borderRadius: '4px', background: isShort ? 'rgba(255,59,48,0.15)' : 'rgba(0,200,5,0.12)', color: isShort ? '#ff6b6b' : '#00c805', fontWeight: 700 }}>{isShort ? '做空' : '做多'}</span></td>
                      <td>{Math.abs(pos.shares)} 股</td>
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

        {/* 交易动态 / 历史记录 */}
        <div className="card" style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column' }}>
          {/* Tab 切换 */}
          <div style={{ display: 'flex', gap: '8px', marginBottom: '1rem', borderBottom: '1px solid var(--color-border)', paddingBottom: '10px' }}>
            {(['feed', 'history'] as ActiveTab[]).map((tab) => (
              <button key={tab} onClick={() => setActiveTab(tab)} style={{
                background: activeTab === tab ? 'rgba(255,255,255,0.08)' : 'transparent',
                border: activeTab === tab ? '1px solid rgba(255,255,255,0.15)' : '1px solid transparent',
                color: activeTab === tab ? '#fff' : 'var(--color-text-secondary)',
                padding: '5px 14px', borderRadius: '6px', cursor: 'pointer', fontSize: '0.82rem', fontWeight: activeTab === tab ? 700 : 400
              }}>
                {tab === 'feed' ? '⚡ 实时买卖动态' : '📅 历史交易记录'}
              </button>
            ))}
          </div>

          {/* Action Feed Tab */}
          {activeTab === 'feed' && (
            <div style={{ flex: 1, overflowY: 'auto', maxHeight: '380px' }}>
              {actionFeed.length === 0 ? (
                <div style={{ color: 'var(--color-text-secondary)', fontSize: '0.85rem', padding: '2.5rem 0', textAlign: 'center' }}>
                  启动 AI 托管后，实际买卖操作（做多/做空/平仓）将实时展示在此。<br />
                  <span style={{ fontSize: '0.75rem', opacity: 0.6 }}>扫描日志已过滤，仅显示真实交易动作</span>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {actionFeed.map((feed, idx) => {
                    const actionMatch = feed.match(/\[([A-Z]+)\]/);
                    const action = actionMatch ? ['BUY','SHORT','SELL','COVER'].find(a => feed.includes(a === 'BUY' ? '做多买入' : a === 'SHORT' ? '融券做空' : a === 'SELL' ? '多单平仓' : '空单平仓')) || '' : '';
                    const style = getActionStyle(action);
                    return (
                      <div key={idx} style={{ background: style.bg, border: style.border, borderRadius: '8px', padding: '10px 14px', fontSize: '0.79rem', color: style.color, lineHeight: 1.5 }}>
                        {feed}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Trade History Tab */}
          {activeTab === 'history' && (
            <div style={{ flex: 1, overflowY: 'auto', maxHeight: '380px' }}>
              {tradeHistory.length === 0 ? (
                <div style={{ color: 'var(--color-text-secondary)', fontSize: '0.85rem', padding: '2.5rem 0', textAlign: 'center' }}>
                  近 7 天暂无交易记录。<br />
                  <span style={{ fontSize: '0.75rem', opacity: 0.6 }}>交易成功后可在此复盘每笔买卖</span>
                </div>
              ) : (
                <table className="ledger-table" style={{ fontSize: '0.78rem', width: '100%' }}>
                  <thead>
                    <tr>
                      <th>时间</th><th>代码</th><th>操作</th><th>股数</th><th>成交价</th><th style={{ textAlign: 'right' }}>盈亏</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...tradeHistory].reverse().map((trade, idx) => {
                      const st = getActionStyle(trade.action);
                      const hasPnl = trade.pnl !== 0;
                      return (
                        <tr key={idx}>
                          <td style={{ color: 'var(--color-text-secondary)', fontSize: '0.72rem', whiteSpace: 'nowrap' }}>{trade.time.slice(5)}</td>
                          <td style={{ fontWeight: 900, color: '#fff' }}>{trade.ticker}</td>
                          <td><span style={{ padding: '2px 7px', borderRadius: '4px', border: st.border, color: st.color, fontSize: '0.72rem', fontWeight: 700 }}>{trade.action_cn}</span></td>
                          <td>{trade.shares}</td>
                          <td>${trade.price.toFixed(2)}</td>
                          <td style={{ textAlign: 'right', fontWeight: 800, color: hasPnl ? (trade.pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)') : '#555' }}>
                            {hasPnl ? `${trade.pnl >= 0 ? '+' : ''}$${trade.pnl.toFixed(2)}` : '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* 底部应急按钮 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid var(--color-border)' }}>
            <button onClick={handleCancelAllOrders} disabled={actionLoading !== null} style={{ background: 'rgba(255,149,0,0.1)', border: '1px solid #ff9500', color: '#ff9500', padding: '8px 12px', borderRadius: '6px', fontSize: '0.8rem', fontWeight: 700, cursor: 'pointer' }}>
              📯 撤销所有挂单
            </button>
            <button onClick={handleForceLiquidate} disabled={actionLoading !== null} style={{ background: 'rgba(255,59,48,0.15)', border: '1px solid var(--color-red)', color: 'var(--color-red)', padding: '8px 12px', borderRadius: '6px', fontSize: '0.8rem', fontWeight: 800, cursor: 'pointer' }}>
              🚨 一键紧急全平仓
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
