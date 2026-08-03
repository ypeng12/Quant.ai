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

interface BrokerPanelProps {
  watchlist?: string[];
}

type ActiveTab = 'analysis' | 'actions' | 'history';

export function BrokerPanel({ watchlist = [] }: BrokerPanelProps) {
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [positions, setPositions] = useState<BrokerPosition[]>([]);
  const [isBotRunning, setIsBotRunning] = useState<boolean>(false);
  const [activeTickers, setActiveTickers] = useState<string[]>([]);
  const [actionFeed, setActionFeed] = useState<string[]>([]);
  const [analysisFeed, setAnalysisFeed] = useState<string[]>([]);
  const [tradeHistory, setTradeHistory] = useState<TradeRecord[]>([]);
  const [todaySummary, setTodaySummary] = useState<TodaySummary | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [closingTicker, setClosingTicker] = useState<string | null>(null);

  const handleClosePosition = async (ticker: string) => {
    if (!window.confirm(`确定要手动强行卖出 / 平仓 ${ticker} 吗？\nConfirm manual force sell/close position for ${ticker}?`)) {
      return;
    }
    setClosingTicker(ticker);
    try {
      const res = await fetch(`${API_BASE}/api/live/close_position`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker })
      });
      const data = await res.json();
      if (data.success) {
        await fetchBrokerData();
      } else {
        alert(`平仓失败: ${data.error || data.detail || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`请求失败: ${err}`);
    } finally {
      setClosingTicker(null);
    }
  };

  // Extended hours limit order state
  const [showExtModal, setShowExtModal] = useState(false);
  const [extSymbol, setExtSymbol] = useState(watchlist[0] || 'TSLA');
  const [extSide, setExtSide] = useState<'buy' | 'sell'>('sell');
  const [extQty, setExtQty] = useState(10);
  const [extPrice, setExtPrice] = useState(300.0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>('analysis');
  const [marketMode, setMarketMode] = useState<'MANUAL_OPEN' | 'MANUAL_CLOSE' | 'AUTO_EXCHANGE'>('MANUAL_OPEN');
  const [isMarketOpen, setIsMarketOpen] = useState<boolean>(true);
  const [focusTickers, setFocusTickers] = useState<string[]>([]);

  const fetchBrokerData = async () => {
    try {
      const [accRes, posRes, statusRes, feedRes, analysisRes, histRes, todayRes] = await Promise.all([
        fetch(`${API_BASE}/api/broker/account`),
        fetch(`${API_BASE}/api/broker/positions`),
        fetch(`${API_BASE}/api/live/status`),
        fetch(`${API_BASE}/api/live/action_feed?limit=50`),
        fetch(`${API_BASE}/api/live/analysis_feed?limit=80`),
        fetch(`${API_BASE}/api/live/trade_history?days=30`),
        fetch(`${API_BASE}/api/live/today_summary`),
      ]);

      const accJson = await accRes.json();
      if (accJson.success !== false) { setAccount(accJson); setErrorMsg(null); }
      else setErrorMsg(accJson.error || 'Failed to fetch account info');

      const posJson = await posRes.json();
      if (posJson.success) setPositions(posJson.positions);

      const statusJson = await statusRes.json();
      if (statusJson.success) {
        setIsBotRunning(statusJson.status.is_running);
        if (statusJson.status.market_mode) {
          setMarketMode(statusJson.status.market_mode);
        }
        if (statusJson.status.is_market_open !== undefined) {
          setIsMarketOpen(statusJson.status.is_market_open);
        }
        if (statusJson.status.active_tickers) {
          setActiveTickers(statusJson.status.active_tickers);
        }
        if (statusJson.status.focus_tickers) {
          setFocusTickers(statusJson.status.focus_tickers);
        }
      }

      const feedJson = await feedRes.json();
      if (feedJson.success) setActionFeed(feedJson.logs || []);

      const analysisJson = await analysisRes.json();
      if (analysisJson.success) setAnalysisFeed(analysisJson.logs || []);

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

  // Sync watchlist to AI Live Scanner automatically when changed
  useEffect(() => {
    if (watchlist.length > 0) {
      fetch(`${API_BASE}/api/live/watchlist/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers: watchlist })
      }).then(res => res.json()).then(data => {
        if (data.success && data.active_tickers) {
          setActiveTickers(data.active_tickers);
        }
      }).catch(err => console.error('Watchlist sync error:', err));
    }
  }, [watchlist]);

  useEffect(() => {
    fetchBrokerData();
    const interval = setInterval(fetchBrokerData, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleSetMarketMode = async (mode: 'MANUAL_OPEN' | 'MANUAL_CLOSE' | 'AUTO_EXCHANGE') => {
    setActionLoading('market_mode');
    try {
      const res = await fetch(`${API_BASE}/api/live/market_mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ market_mode: mode })
      });
      const json = await res.json();
      if (json.success) {
        setMarketMode(mode);
        if (json.status) {
          setIsMarketOpen(json.status.is_market_open);
          setIsBotRunning(json.status.is_running);
        }
      } else {
        alert('设置开盘模式失败: ' + (json.data?.error || json.error || '未知错误'));
      }
    } catch {
      alert('请求失败');
    } finally {
      setActionLoading(null);
      fetchBrokerData();
    }
  };

  const handleToggleFocusTicker = async (ticker: string) => {
    const sym = ticker.toUpperCase().trim();
    const nextFocus = focusTickers.includes(sym)
      ? focusTickers.filter(t => t !== sym)
      : [...focusTickers, sym];

    try {
      const res = await fetch(`${API_BASE}/api/live/focus_tickers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers: nextFocus })
      });
      const json = await res.json();
      if (json.success) {
        setFocusTickers(json.data?.focus_tickers || nextFocus);
      }
    } catch (e) {
      console.error('Focus tickers error:', e);
    } finally {
      fetchBrokerData();
    }
  };

  const handleStartBot = async () => {
    setActionLoading('start');
    try {
      const res = await fetch(`${API_BASE}/api/live/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers: watchlist, ignore_market_hours: true, market_mode: marketMode })
      });
      const json = await res.json();
      if (json.success) setIsBotRunning(json.status.is_running);
      else alert('Failed to start bot: ' + (json.status?.logs?.[json.status.logs.length - 1] || 'Error.'));
    } catch { alert('Request failed'); }
    finally { setActionLoading(null); fetchBrokerData(); }
  };

  const handleStopBot = async () => {
    setActionLoading('stop');
    try {
      const res = await fetch(`${API_BASE}/api/live/stop`, { method: 'POST' });
      const json = await res.json();
      setIsBotRunning(json.status.is_running);
    } catch { alert('Request failed'); }
    finally { setActionLoading(null); fetchBrokerData(); }
  };

  const handleCancelAllOrders = async () => {
    if (!window.confirm('Are you sure you want to cancel all pending open orders?')) return;
    setActionLoading('cancel_orders');
    try {
      const res = await fetch(`${API_BASE}/api/broker/cancel_orders`, { method: 'POST' });
      const json = await res.json();
      alert(json.message || 'Order cancellation request sent');
    } catch { alert('Failed to cancel orders'); }
    finally { setActionLoading(null); fetchBrokerData(); }
  };

  const handleForceLiquidate = async () => {
    if (!window.confirm('🚨 This will immediately close ALL open positions at market price! Continue?')) return;
    setActionLoading('liquidate');
    try {
      const res = await fetch(`${API_BASE}/api/broker/close_positions`, { method: 'POST' });
      const json = await res.json();
      alert(json.message || 'Force liquidation request sent');
    } catch { alert('Failed to close positions'); }
    finally { setActionLoading(null); fetchBrokerData(); }
  };

  const handleSendExtendedHoursOrder = async () => {
    setActionLoading('ext_order');
    try {
      const res = await fetch(`${API_BASE}/api/live/extended_hours_order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: extSymbol,
          qty: Number(extQty),
          side: extSide,
          limit_price: Number(extPrice)
        })
      });
      const json = await res.json();
      if (json.success) {
        alert(`🌙 [Extended-Hours Order] Order submitted! ${extSymbol} ${extSide.toUpperCase()} ${extQty} shares @ $${extPrice}`);
        setShowExtModal(false);
      } else {
        alert('Order failed: ' + (json.message || json.error || 'Unknown error'));
      }
    } catch {
      alert('Request failed');
    } finally {
      setActionLoading(null);
      fetchBrokerData();
    }
  };

  const getActionStyle = (action: string) => {
    if (action === 'BUY') return { border: '1px solid rgba(0,200,5,0.4)', color: '#00c805', bg: 'rgba(0,200,5,0.04)' };
    if (action === 'SHORT') return { border: '1px solid rgba(255,59,48,0.5)', color: '#ff6b6b', bg: 'rgba(255,59,48,0.05)' };
    if (action === 'SELL') return { border: '1px solid rgba(255,149,0,0.4)', color: '#ff9500', bg: 'rgba(255,149,0,0.04)' };
    if (action === 'COVER') return { border: '1px solid rgba(100,180,255,0.4)', color: '#64b4ff', bg: 'rgba(100,180,255,0.04)' };
    if (action === 'PARTIAL_SELL') return { border: '1px solid rgba(0,200,5,0.6)', color: '#00c805', bg: 'rgba(0,200,5,0.12)' };
    if (action === 'PARTIAL_COVER') return { border: '1px solid rgba(100,180,255,0.6)', color: '#64b4ff', bg: 'rgba(100,180,255,0.12)' };
    if (action === 'PYRAMID_BUY') return { border: '1px solid rgba(192,132,252,0.6)', color: '#c084fc', bg: 'rgba(192,132,252,0.12)' };
    return { border: '1px solid #333', color: '#888', bg: 'transparent' };
  };

  if (loading && !account) {
    return <div className="loader-container" style={{ padding: '4rem', textAlign: 'center' }}>Connecting to Alpaca Account...</div>;
  }

  if (errorMsg) {
    return (
      <div className="card" style={{ padding: '2.5rem', textAlign: 'center', border: '1px solid var(--color-red)', background: 'rgba(255,59,48,0.05)' }}>
        <h3 style={{ color: 'var(--color-red)', marginTop: 0 }}>🔌 Alpaca Account Disconnected</h3>
        <p style={{ color: '#e5e5e7', fontSize: '0.95rem' }}>{errorMsg}</p>
        <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
          Please configure your Alpaca API Key in <code style={{ color: '#fff', background: '#111', padding: '2px 6px', borderRadius: '4px' }}>backend/.env</code>.
        </div>
      </div>
    );
  }

  const todayPnlPositive = (todaySummary?.total_pnl ?? 0) >= 0;

  return (
    <div className="fade-in">
      {/* Top AI Automated Management Control Card */}
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
              {isBotRunning ? '⚡ AI Quant Bot Running' : '⏸️ AI Automated Trading Paused'}
            </h2>
          </div>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
            {isBotRunning
              ? 'Evaluating long/short signals every 30s and submitting orders directly to Alpaca.'
              : 'Click Start to enable AI execution. Automatically manages trades and risk controls.'}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          {!isBotRunning ? (
            <button onClick={handleStartBot} disabled={actionLoading !== null} style={{ background: 'var(--color-green)', color: '#000', fontWeight: 900, fontSize: '1.05rem', padding: '12px 28px', borderRadius: '8px', border: 'none', cursor: 'pointer', boxShadow: '0 4px 20px rgba(0,200,5,0.3)' }}>
              {actionLoading === 'start' ? '⏳ Starting...' : '▶️ Start AI Bot'}
            </button>
          ) : (
            <button onClick={handleStopBot} disabled={actionLoading !== null} style={{ background: '#3a3a3c', color: '#fff', fontWeight: 800, fontSize: '1rem', padding: '12px 24px', borderRadius: '8px', border: '1px solid #48484a', cursor: 'pointer' }}>
              {actionLoading === 'stop' ? '⏳ Stopping...' : '⏸️ Pause AI Bot'}
            </button>
          )}
          <button onClick={() => setShowExtModal(true)} disabled={actionLoading !== null} style={{ background: 'linear-gradient(135deg, #2e1065 0%, #3b0764 100%)', color: '#c084fc', fontWeight: 800, fontSize: '0.95rem', padding: '12px 20px', borderRadius: '8px', border: '1px solid rgba(192,132,252,0.4)', cursor: 'pointer', boxShadow: '0 4px 15px rgba(147,51,234,0.25)' }}>
            🌙 Extended-Hours Limit Order
          </button>
        </div>
      </div>

      {/* Manual Market Open / Close Control Card */}
      <div style={{
        marginBottom: '1.2rem',
        padding: '12px 18px',
        background: 'linear-gradient(135deg, rgba(20,20,25,0.95) 0%, rgba(10,10,12,0.95) 100%)',
        borderRadius: '10px',
        border: '1px solid rgba(255,255,255,0.12)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '12px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '0.95rem', fontWeight: 800, color: '#fff' }}>🎛️ 人为开关盘控制:</span>
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 10px',
            borderRadius: '6px',
            background: marketMode === 'MANUAL_OPEN'
              ? 'rgba(0, 200, 5, 0.15)'
              : marketMode === 'MANUAL_CLOSE'
                ? 'rgba(255, 59, 48, 0.15)'
                : 'rgba(100, 180, 255, 0.15)',
            border: `1px solid ${
              marketMode === 'MANUAL_OPEN'
                ? 'rgba(0, 200, 5, 0.4)'
                : marketMode === 'MANUAL_CLOSE'
                  ? 'rgba(255, 59, 48, 0.4)'
                  : 'rgba(100, 180, 255, 0.4)'
            }`,
            fontSize: '0.82rem',
            fontWeight: 800,
            color: marketMode === 'MANUAL_OPEN'
              ? '#00c805'
              : marketMode === 'MANUAL_CLOSE'
                ? '#ff6b6b'
                : '#64b4ff'
          }}>
            {marketMode === 'MANUAL_OPEN' && '🟢 人为强制开盘中 (打破休市限制，允许全天候买卖)'}
            {marketMode === 'MANUAL_CLOSE' && '🔴 人为强制关盘中 (暂停研判扫描与下单)'}
            {marketMode === 'AUTO_EXCHANGE' && `⏱️ 交易所自动模式 (${isMarketOpen ? '美股已开盘 ✅' : '美股休市中 💤'})`}
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            onClick={() => handleSetMarketMode('MANUAL_OPEN')}
            disabled={actionLoading !== null}
            style={{
              background: marketMode === 'MANUAL_OPEN' ? 'rgba(0, 200, 5, 0.25)' : 'rgba(255,255,255,0.05)',
              border: marketMode === 'MANUAL_OPEN' ? '1px solid #00c805' : '1px solid rgba(255,255,255,0.15)',
              color: marketMode === 'MANUAL_OPEN' ? '#00c805' : '#ccc',
              fontWeight: 800,
              fontSize: '0.82rem',
              padding: '6px 14px',
              borderRadius: '6px',
              cursor: 'pointer'
            }}
          >
            🟢 人为强制开盘
          </button>
          <button
            onClick={() => handleSetMarketMode('MANUAL_CLOSE')}
            disabled={actionLoading !== null}
            style={{
              background: marketMode === 'MANUAL_CLOSE' ? 'rgba(255, 59, 48, 0.25)' : 'rgba(255,255,255,0.05)',
              border: marketMode === 'MANUAL_CLOSE' ? '1px solid #ff5d5d' : '1px solid rgba(255,255,255,0.15)',
              color: marketMode === 'MANUAL_CLOSE' ? '#ff6b6b' : '#ccc',
              fontWeight: 800,
              fontSize: '0.82rem',
              padding: '6px 14px',
              borderRadius: '6px',
              cursor: 'pointer'
            }}
          >
            🔴 人为强制关盘
          </button>
          <button
            onClick={() => handleSetMarketMode('AUTO_EXCHANGE')}
            disabled={actionLoading !== null}
            style={{
              background: marketMode === 'AUTO_EXCHANGE' ? 'rgba(100, 180, 255, 0.25)' : 'rgba(255,255,255,0.05)',
              border: marketMode === 'AUTO_EXCHANGE' ? '1px solid #64b4ff' : '1px solid rgba(255,255,255,0.15)',
              color: marketMode === 'AUTO_EXCHANGE' ? '#64b4ff' : '#ccc',
              fontWeight: 800,
              fontSize: '0.82rem',
              padding: '6px 14px',
              borderRadius: '6px',
              cursor: 'pointer'
            }}
          >
            ⏱️ 交易所自动
          </button>
        </div>
      </div>

      {/* AI Scanner Watchlist Synchronization Bar */}
      <div style={{
        marginBottom: '1.2rem',
        padding: '10px 16px',
        background: 'rgba(255,255,255,0.03)',
        borderRadius: '8px',
        border: '1px solid rgba(255,255,255,0.08)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '10px',
        fontSize: '0.82rem'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--color-green)', fontWeight: 700 }}>🎯 AI 实时研判股票池 ({activeTickers.length} 支已自动对齐):</span>
          {activeTickers.map(t => {
            const isFocus = focusTickers.includes(t.toUpperCase());
            return (
              <button
                key={t}
                onClick={() => handleToggleFocusTicker(t)}
                title={isFocus ? "已设为重点重仓标的 (点击取消)" : "点击设为 AI 重点重仓关注标的 (优先研判+15分置信加成+1.75x仓位)"}
                style={{
                  background: isFocus ? 'linear-gradient(135deg, rgba(192,132,252,0.25) 0%, rgba(147,51,234,0.3) 100%)' : 'rgba(255,255,255,0.08)',
                  border: isFocus ? '1px solid rgba(192,132,252,0.7)' : '1px solid rgba(255,255,255,0.12)',
                  boxShadow: isFocus ? '0 0 10px rgba(192,132,252,0.35)' : 'none',
                  padding: '3px 10px',
                  borderRadius: '6px',
                  color: isFocus ? '#fff' : '#ccc',
                  fontWeight: 800,
                  fontSize: '0.78rem',
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  transition: 'all 0.2s ease'
                }}
              >
                {isFocus ? `🔥 ${t} (重点重仓)` : t}
              </button>
            );
          })}
        </div>
        <span style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)' }}>
          💡 点击股票按钮可随时切换【🔥 重点重仓关注】状态（享 1.75x 仓位与最高研判优先级）
        </span>
      </div>

      {/* Today PnL Summary */}
      {(() => {
        if (!todaySummary && tradeHistory.length === 0) return null;

        const curDate = selectedDate || todaySummary?.date || (tradeHistory.length > 0 ? (tradeHistory[0].date || tradeHistory[0].time?.slice(0, 10))?.trim() : new Date().toLocaleDateString('sv-SE'));
        const closedToday = tradeHistory.filter(t => {
          const d = (t.date || t.time?.slice(0, 10))?.trim();
          return d === curDate && (t.action === 'SELL' || t.action === 'COVER');
        });
        const calcWins = closedToday.filter(t => (t.pnl || 0) > 0).length;
        const calcLosses = closedToday.filter(t => (t.pnl || 0) < 0).length;
        const calcClosed = closedToday.length;
        const calcWinRate = calcClosed > 0 ? (calcWins / calcClosed) * 100 : 0.0;

        const bestTradeVal = (todaySummary?.best_trade !== undefined && todaySummary.best_trade !== 0)
          ? todaySummary.best_trade
          : (closedToday.length > 0 ? Math.max(0, ...closedToday.map(t => t.pnl || 0)) : 0);

        const worstTradeVal = (todaySummary?.worst_trade !== undefined && todaySummary.worst_trade !== 0)
          ? todaySummary.worst_trade
          : (closedToday.length > 0 ? Math.min(0, ...closedToday.map(t => t.pnl || 0)) : 0);

        const winsVal = (todaySummary?.wins !== undefined && todaySummary.wins > 0) ? todaySummary.wins : calcWins;
        const lossesVal = (todaySummary?.losses !== undefined && todaySummary.losses > 0) ? todaySummary.losses : calcLosses;
        const winRateVal = (todaySummary?.win_rate !== undefined && todaySummary.win_rate > 0) ? todaySummary.win_rate : calcWinRate;
        const netPnlVal = todaySummary?.total_pnl ?? closedToday.reduce((sum, t) => sum + (t.pnl || 0), 0);

        return (
          <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(5, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
            <div className="stat-card" style={{ background: '#09090b', border: `1px solid ${netPnlVal >= 0 ? 'rgba(0,200,5,0.3)' : 'rgba(255,59,48,0.3)'}`, padding: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <span className="stat-label">Realized PnL</span>
                <span style={{ fontSize: '0.68rem', padding: '1px 5px', borderRadius: '3px', background: 'rgba(0,200,5,0.15)', color: '#00c805', fontWeight: 700 }}>Alpaca Live</span>
              </div>
              <span className="stat-value" style={{ fontSize: '1.4rem', fontWeight: 900, color: netPnlVal >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
                {netPnlVal >= 0 ? '+' : ''}${netPnlVal.toFixed(2)}
              </span>
            </div>
            <div className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1.25rem' }}>
              <span className="stat-label">Win Rate</span>
              <span className="stat-value" style={{ fontSize: '1.4rem', fontWeight: 900, color: winRateVal >= 50 ? 'var(--color-green)' : 'var(--color-red)' }}>
                {winRateVal.toFixed(1)}%
              </span>
            </div>
            <div className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1.25rem' }}>
              <span className="stat-label">Wins / Losses</span>
              <span className="stat-value" style={{ fontSize: '1.4rem', fontWeight: 900 }}>
                <span style={{ color: 'var(--color-green)' }}>{winsVal}</span>
                <span style={{ color: '#555', margin: '0 4px' }}>/</span>
                <span style={{ color: 'var(--color-red)' }}>{lossesVal}</span>
              </span>
            </div>
            <div className="stat-card" style={{ background: '#09090b', border: '1px solid rgba(0,200,5,0.2)', padding: '1.25rem' }}>
              <span className="stat-label">Best Trade</span>
              <span className="stat-value" style={{ fontSize: '1.3rem', fontWeight: 900, color: 'var(--color-green)' }}>
                +${bestTradeVal.toFixed(2)}
              </span>
            </div>
            <div className="stat-card" style={{ background: '#09090b', border: '1px solid rgba(255,59,48,0.2)', padding: '1.25rem' }}>
              <span className="stat-label">Worst Trade</span>
              <span className="stat-value" style={{ fontSize: '1.3rem', fontWeight: 900, color: 'var(--color-red)' }}>
                ${worstTradeVal.toFixed(2)}
              </span>
            </div>
          </div>
        );
      })()}

      {/* Account Overview */}
      {account && (
        <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
          {[
            { label: 'Net Equity', value: `$${account.equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, color: undefined },
            { label: 'Available Cash', value: `$${account.cash.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, color: 'var(--color-green)' },
            { label: 'Position Value', value: `$${(account.equity - account.cash).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, color: undefined },
            { label: 'Buying Power', value: `$${account.buying_power.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, color: '#e5e5e7' },
          ].map(({ label, value, color }) => (
            <div key={label} className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1.25rem' }}>
              <span className="stat-label">{label}</span>
              <span className="stat-value" style={{ fontSize: '1.5rem', fontWeight: 900, color }}>{value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Positions + Trading Feed Panel */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '1.5rem' }}>
        {/* Positions Table */}
        <div className="card" style={{ padding: '1.25rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 800, color: '#fff' }}>📋 Live Positions</h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              {positions.length > 0 && (
                <button
                  onClick={async () => {
                    if (window.confirm("⚠️ 确定要强行全平所有持仓吗？(Force liquidate all positions)")) {
                      try {
                        const res = await fetch(`${API_BASE}/api/broker/close_all`, { method: 'POST' });
                        const d = await res.json();
                        if (d.success) fetchBrokerData();
                      } catch (e) {}
                    }
                  }}
                  style={{
                    background: 'rgba(255, 59, 48, 0.12)',
                    border: '1px solid rgba(255, 59, 48, 0.3)',
                    color: '#ff6b6b',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    fontSize: '0.72rem',
                    fontWeight: 700,
                    cursor: 'pointer'
                  }}
                >
                  🔥 Close All Positions
                </button>
              )}
              <span style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)' }}>Account: <strong>{account?.account_number}</strong></span>
            </div>
          </div>
          {positions.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '3rem 1.5rem', background: 'rgba(0,0,0,0.2)', borderRadius: '8px', border: '1px dashed rgba(255,255,255,0.1)' }}>
              {(!isMarketOpen || marketMode === 'MANUAL_CLOSE') ? (
                <div>
                  <div style={{ fontSize: '1.1rem', fontWeight: 800, color: '#ff6b6b', marginBottom: '6px' }}>
                    💤 休市中 / 人为关盘中
                  </div>
                  <div style={{ fontSize: '0.82rem', color: 'var(--color-text-secondary)' }}>
                    美股交易所处于非常规交易时段或系统已设定为人为关盘。正在等待开盘或手动切换开盘模式...
                  </div>
                </div>
              ) : (
                <div>
                  <div style={{ fontSize: '1.1rem', fontWeight: 800, color: '#00c805', marginBottom: '6px' }}>
                    📡 系统全频段研判中 (监控池目前空仓)
                  </div>
                  <div style={{ fontSize: '0.82rem', color: 'var(--color-text-secondary)' }}>
                    AI 量化引擎正在实时扫描 Watchlist 股票池微观数据，暂未发现符合条件的合适买点，持续全频监控中...
                  </div>
                </div>
              )}
            </div>
          ) : (
            <table className="ledger-table" style={{ fontSize: '0.85rem' }}>
              <thead>
                <tr>
                  <th>Ticker</th><th>Side</th><th>Shares</th><th>Avg Price</th><th>Current Price</th><th style={{ textAlign: 'right' }}>Unrealized PnL</th><th style={{ textAlign: 'center' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => {
                  const isUp = pos.unrealized_pnl >= 0;
                  const isShort = pos.shares < 0;
                  return (
                    <tr key={pos.ticker}>
                      <td style={{ fontWeight: 900, color: '#fff' }}>{pos.ticker}</td>
                      <td><span style={{ fontSize: '0.75rem', padding: '2px 6px', borderRadius: '4px', background: isShort ? 'rgba(255,59,48,0.15)' : 'rgba(0,200,5,0.12)', color: isShort ? '#ff6b6b' : '#00c805', fontWeight: 700 }}>{isShort ? 'SHORT' : 'LONG'}</span></td>
                      <td>{Math.abs(pos.shares)} shs</td>
                      <td>${pos.avg_entry_price.toFixed(2)}</td>
                      <td>${pos.current_price.toFixed(2)}</td>
                      <td style={{ textAlign: 'right', fontWeight: 800, color: isUp ? 'var(--color-green)' : 'var(--color-red)' }}>
                        {isUp ? '+' : ''}${pos.unrealized_pnl.toFixed(2)} ({isUp ? '+' : ''}{pos.unrealized_pnl_pct.toFixed(2)}%)
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <button
                          onClick={() => handleClosePosition(pos.ticker)}
                          disabled={closingTicker === pos.ticker}
                          title={isShort ? `强行平空仓 (Close Short ${pos.ticker})` : `强行卖出/平仓 (Sell ${pos.ticker})`}
                          style={{
                            background: 'transparent',
                            border: '1px solid rgba(255, 59, 48, 0.35)',
                            color: '#ff4d4d',
                            width: '26px',
                            height: '26px',
                            borderRadius: '50%',
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontWeight: 900,
                            fontSize: '0.85rem',
                            cursor: 'pointer',
                            transition: 'all 0.2s ease',
                            padding: 0
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background = 'rgba(255, 59, 48, 0.2)';
                            e.currentTarget.style.borderColor = 'rgba(255, 59, 48, 0.7)';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background = 'transparent';
                            e.currentTarget.style.borderColor = 'rgba(255, 59, 48, 0.35)';
                          }}
                        >
                          {closingTicker === pos.ticker ? '⏳' : '✕'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Live Feed / History Panel */}
        <div className="card" style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column' }}>
          {/* Tabs */}
          <div style={{ display: 'flex', gap: '8px', marginBottom: '1rem', borderBottom: '1px solid var(--color-border)', paddingBottom: '10px' }}>
            {([
              { id: 'analysis', label: '🧠 AI Live Analysis & Alerts' },
              { id: 'actions', label: '⚡ Execution Activity' },
              { id: 'history', label: '📅 Trade History' },
            ] as { id: ActiveTab; label: string }[]).map((tab) => (
              <button key={tab.id} onClick={() => setActiveTab(tab.id)} style={{
                background: activeTab === tab.id ? 'rgba(255,255,255,0.08)' : 'transparent',
                border: activeTab === tab.id ? '1px solid rgba(255,255,255,0.15)' : '1px solid transparent',
                color: activeTab === tab.id ? '#fff' : 'var(--color-text-secondary)',
                padding: '5px 14px', borderRadius: '6px', cursor: 'pointer', fontSize: '0.82rem', fontWeight: activeTab === tab.id ? 700 : 400
              }}>
                {tab.label}
              </button>
            ))}
          </div>

          {/* 1. AI Analysis & Alerts Tab */}
          {activeTab === 'analysis' && (
            <div style={{ flex: 1, overflowY: 'auto', maxHeight: '380px' }}>
              {analysisFeed.length === 0 ? (
                <div style={{ color: 'var(--color-text-secondary)', fontSize: '0.85rem', padding: '2.5rem 0', textAlign: 'center' }}>
                  When AI Bot is active, real-time indicator snapshots and pattern alerts will appear here.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {analysisFeed.map((log, idx) => {
                    const isBuyOrShort = log.includes('BUY') || log.includes('SHORT');
                    const isAlert = log.includes('🔔') || log.includes('⚡') || log.includes('🔥') || log.includes('🌡️');
                    const isSell = log.includes('SELL') || log.includes('COVER') || log.includes('Close');
                    
                    let bg = '#141416';
                    let border = '1px solid #27272a';
                    let color = '#d4d4d8';

                    if (isBuyOrShort) {
                      bg = 'rgba(0, 200, 5, 0.08)';
                      border = '1px solid rgba(0, 200, 5, 0.4)';
                      color = 'var(--color-green)';
                    } else if (isAlert) {
                      bg = 'rgba(255, 149, 0, 0.06)';
                      border = '1px solid rgba(255, 149, 0, 0.3)';
                      color = '#ffb020';
                    } else if (isSell) {
                      bg = 'rgba(255, 59, 48, 0.06)';
                      border = '1px solid rgba(255, 59, 48, 0.3)';
                      color = '#ff6b6b';
                    }

                    return (
                      <div key={idx} style={{
                        background: bg,
                        border: border,
                        borderRadius: '8px',
                        padding: '10px 14px',
                        fontSize: '0.79rem',
                        color: color,
                        lineHeight: 1.5,
                        fontFamily: 'monospace, sans-serif'
                      }}>
                        {log}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* 2. Execution Activity Tab */}
          {activeTab === 'actions' && (
            <div style={{ flex: 1, overflowY: 'auto', maxHeight: '380px' }}>
              {actionFeed.length === 0 ? (
                <div style={{ color: 'var(--color-text-secondary)', fontSize: '0.85rem', padding: '2.5rem 0', textAlign: 'center' }}>
                  No executed orders yet.<br />
                  <span style={{ fontSize: '0.75rem', opacity: 0.6 }}>Order execution logs will be listed here.</span>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {actionFeed.map((feed, idx) => {
                    const actionMatch = feed.match(/\[([A-Z]+)\]/);
                    const action = actionMatch ? ['BUY','SHORT','SELL','COVER'].find(a => feed.includes(a)) || '' : '';
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

          {/* 3. Trade History Tab */}
          {activeTab === 'history' && (
            <div style={{ flex: 1, overflowY: 'auto', maxHeight: '380px' }}>
              {tradeHistory.length === 0 ? (
                <div style={{ color: 'var(--color-text-secondary)', fontSize: '0.85rem', padding: '2.5rem 0', textAlign: 'center' }}>
                  No historical trade records in the last 7 days.<br />
                  <span style={{ fontSize: '0.75rem', opacity: 0.6 }}>Executed trades will be recorded here for review.</span>
                </div>
              ) : (
                <table className="ledger-table" style={{ fontSize: '0.78rem', width: '100%' }}>
                  <thead>
                    <tr>
                      <th>Time</th><th>Ticker</th><th>Action</th><th>Shares</th><th>Price</th><th style={{ textAlign: 'right' }}>PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...tradeHistory].reverse().map((trade, idx) => {
                      const st = getActionStyle(trade.action);
                      const hasPnl = trade.pnl !== 0;
                      return (
                        <tr key={idx}>
                          <td style={{ color: 'var(--color-text-secondary)', fontSize: '0.72rem', whiteSpace: 'nowrap' }}>{trade.time ? (trade.time.length > 5 ? trade.time.slice(5) : trade.time) : (trade.date || '—')}</td>
                          <td style={{ fontWeight: 900, color: '#fff' }}>{trade.ticker}</td>
                          <td><span style={{ padding: '2px 7px', borderRadius: '4px', border: st.border, color: st.color, fontSize: '0.72rem', fontWeight: 700 }}>{trade.action}</span></td>
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

          {/* Emergency Action Buttons */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid var(--color-border)' }}>
            <button onClick={handleCancelAllOrders} disabled={actionLoading !== null} style={{ background: 'rgba(255,149,0,0.1)', border: '1px solid #ff9500', color: '#ff9500', padding: '8px 12px', borderRadius: '6px', fontSize: '0.8rem', fontWeight: 700, cursor: 'pointer' }}>
              📯 Cancel All Open Orders
            </button>
            <button onClick={handleForceLiquidate} disabled={actionLoading !== null} style={{ background: 'rgba(255,59,48,0.15)', border: '1px solid var(--color-red)', color: 'var(--color-red)', padding: '8px 12px', borderRadius: '6px', fontSize: '0.8rem', fontWeight: 800, cursor: 'pointer' }}>
              🚨 Emergency Close All Positions
            </button>
          </div>
        </div>
      </div>

      {/* ====== Execution Log with Date Selector ====== */}
      {(() => {
        const todayStr = todaySummary?.date || new Date().toLocaleDateString('sv-SE');
        const rawDates = tradeHistory.map(t => (t.date || t.time?.slice(0, 10))?.trim()).filter(Boolean) as string[];
        const availableDates = Array.from(new Set(rawDates)).sort().reverse();
        if (todayStr && !availableDates.includes(todayStr)) {
          availableDates.unshift(todayStr);
        }

        const effectiveDate = selectedDate || (availableDates.length > 0 ? availableDates[0] : todayStr);
        const displayTrades = [...tradeHistory].filter(t => {
          const d = (t.date || t.time?.slice(0, 10))?.trim();
          return d === effectiveDate;
        }).reverse();

        // Calculate metrics for selected date
        const totalTradesCount = displayTrades.length;
        const closedTrades = displayTrades.filter(t => t.action === 'SELL' || t.action === 'COVER');
        const winsCount = closedTrades.filter(t => (t.pnl || 0) > 0).length;
        const lossesCount = closedTrades.filter(t => (t.pnl || 0) < 0).length;
        const netPnl = closedTrades.reduce((sum, t) => sum + (t.pnl || 0), 0);

        const tickerMap: Record<string, { trades: TradeRecord[]; totalPnl: number; openAction: string | null }> = {};
        displayTrades.forEach(t => {
          if (!tickerMap[t.ticker]) tickerMap[t.ticker] = { trades: [], totalPnl: 0, openAction: null };
          tickerMap[t.ticker].trades.push(t);
          tickerMap[t.ticker].totalPnl += t.pnl;
          if (t.action === 'BUY' || t.action === 'SHORT') tickerMap[t.ticker].openAction = t.action;
          if (t.action === 'SELL' || t.action === 'COVER') tickerMap[t.ticker].openAction = null;
        });

        return (
          <div className="card" style={{ marginTop: '1.5rem', padding: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.2rem', flexWrap: 'wrap', gap: '1rem' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 900, color: '#fff' }}>📒 Execution & Review Log</h3>
                  {/* Date Picker Selector */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <select
                      value={effectiveDate}
                      onChange={(e) => setSelectedDate(e.target.value)}
                      style={{
                        background: 'rgba(255,255,255,0.08)',
                        border: '1px solid var(--color-border)',
                        color: '#00e5ff',
                        borderRadius: '6px',
                        padding: '4px 10px',
                        fontSize: '0.82rem',
                        fontWeight: 800,
                        cursor: 'pointer',
                        outline: 'none'
                      }}
                    >
                      {availableDates.map(d => (
                        <option key={d} value={d} style={{ background: '#1c1c1e', color: '#fff' }}>
                          {d === todayStr ? `🔴 Live Today (${d})` : `🗓️ ${d}`}
                        </option>
                      ))}
                    </select>
                    {selectedDate && selectedDate !== todayStr && (
                      <button
                        onClick={() => setSelectedDate('')}
                        style={{
                          background: 'rgba(0,200,5,0.15)',
                          border: '1px solid var(--color-green)',
                          color: 'var(--color-green)',
                          borderRadius: '6px',
                          padding: '4px 10px',
                          fontSize: '0.78rem',
                          fontWeight: 800,
                          cursor: 'pointer'
                        }}
                      >
                        ⚡ Switch to Today Real-Time
                      </button>
                    )}
                  </div>
                </div>
                <p style={{ margin: '4px 0 0', fontSize: '0.78rem', color: 'var(--color-text-secondary)' }}>
                  {effectiveDate === todayStr ? '🔴 Real-time stream of all orders today' : `🗓️ Historical review for date: ${effectiveDate}`}
                </p>
              </div>

              <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '0.72rem', color: 'var(--color-text-secondary)' }}>Total Trades</div>
                  <div style={{ fontSize: '1rem', fontWeight: 900, color: '#fff' }}>{totalTradesCount} orders</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '0.72rem', color: 'var(--color-text-secondary)' }}>Wins / Losses</div>
                  <div style={{ fontSize: '1rem', fontWeight: 900 }}>
                    <span style={{ color: 'var(--color-green)' }}>{winsCount}</span>
                    <span style={{ color: '#444', margin: '0 4px' }}>/</span>
                    <span style={{ color: 'var(--color-red)' }}>{lossesCount}</span>
                  </div>
                </div>
                <div style={{ textAlign: 'right', minWidth: '100px' }}>
                  <div style={{ fontSize: '0.72rem', color: 'var(--color-text-secondary)' }}>Net PnL ({effectiveDate})</div>
                  <div style={{ fontSize: '1.3rem', fontWeight: 900, color: netPnl >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
                    {netPnl >= 0 ? '+' : ''}${netPnl.toFixed(2)}
                  </div>
                </div>
              </div>
            </div>

            {displayTrades.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '3rem 0', color: 'var(--color-text-secondary)', fontSize: '0.85rem' }}>
                No executed trades found for {effectiveDate}. All executed buy, short, and exit orders for this date will be recorded here.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                {/* Ticker Group Cards */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(155px, 1fr))', gap: '10px' }}>
                  {Object.entries(tickerMap).map(([ticker, info]) => {
                    const isWin  = info.totalPnl > 0;
                    const isLoss = info.totalPnl < 0;
                    const isOpen = info.openAction !== null;
                    return (
                      <div key={ticker} style={{
                        background: isWin ? 'rgba(0,200,5,0.06)' : isLoss ? 'rgba(255,59,48,0.06)' : 'rgba(255,255,255,0.03)',
                        border: `1px solid ${isWin ? 'rgba(0,200,5,0.35)' : isLoss ? 'rgba(255,59,48,0.35)' : 'rgba(255,255,255,0.1)'}`,
                        borderRadius: '10px', padding: '12px 14px'
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontWeight: 900, fontSize: '1.05rem', color: '#fff' }}>{ticker}</span>
                          {isOpen && (
                            <span style={{ fontSize: '0.68rem', padding: '2px 7px', borderRadius: '4px', background: info.openAction === 'BUY' ? 'rgba(0,200,5,0.2)' : 'rgba(255,59,48,0.2)', color: info.openAction === 'BUY' ? '#00c805' : '#ff6b6b', fontWeight: 700 }}>
                              {info.openAction === 'BUY' ? 'LONG ▲' : 'SHORT ▼'}
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
                          {info.trades.length} trades
                        </div>
                        <div style={{ fontSize: '1.15rem', fontWeight: 900, marginTop: '6px', color: isWin ? 'var(--color-green)' : isLoss ? 'var(--color-red)' : '#666' }}>
                          {info.totalPnl === 0 ? 'Open...' : `${info.totalPnl > 0 ? '+' : ''}$${info.totalPnl.toFixed(2)}`}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Stream Table */}
                <table className="ledger-table" style={{ fontSize: '0.82rem', width: '100%' }}>
                  <thead>
                    <tr>
                      <th style={{ width: '80px' }}>Time</th>
                      <th>Ticker</th>
                      <th>Action</th>
                      <th>Shares</th>
                      <th>Price</th>
                      <th>Trigger Signal</th>
                      <th style={{ textAlign: 'right' }}>PnL (USD)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayTrades.map((trade: TradeRecord, idx: number) => {
                      const st = getActionStyle(trade.action);
                      const hasPnl = trade.pnl !== 0;
                      return (
                        <tr key={idx} style={{ borderLeft: `3px solid ${hasPnl && trade.pnl > 0 ? 'rgba(0,200,5,0.55)' : hasPnl && trade.pnl < 0 ? 'rgba(255,59,48,0.55)' : 'rgba(255,255,255,0.07)'}` }}>
                          <td style={{ color: 'var(--color-text-secondary)', fontSize: '0.75rem', whiteSpace: 'nowrap', paddingLeft: '10px' }}>
                            {trade.time.slice(11, 19)}
                          </td>
                          <td style={{ fontWeight: 900, fontSize: '0.9rem', color: '#fff' }}>{trade.ticker}</td>
                          <td>
                            <span style={{ padding: '3px 9px', borderRadius: '5px', border: st.border, color: st.color, background: st.bg, fontSize: '0.75rem', fontWeight: 700 }}>
                              {trade.action}
                            </span>
                          </td>
                          <td style={{ fontWeight: 600 }}>{trade.shares} shs</td>
                          <td style={{ fontWeight: 700, color: '#e5e5e7' }}>${trade.price.toFixed(2)}</td>
                          <td style={{ fontSize: '0.72rem', color: 'var(--color-text-secondary)', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {trade.reason}
                          </td>
                          <td style={{ textAlign: 'right', fontWeight: 900, fontSize: '0.9rem', color: hasPnl ? (trade.pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)') : '#555' }}>
                            {hasPnl ? `${trade.pnl >= 0 ? '+' : ''}$${trade.pnl.toFixed(2)}` : 'Open'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })()}

      {/* Extended-Hours Modal */}
      {showExtModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(8px)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 9999 }}>
          <div className="card fade-in" style={{ width: '460px', padding: '2rem', background: '#09090b', border: '1px solid rgba(192,132,252,0.4)', boxShadow: '0 20px 50px rgba(0,0,0,0.9), 0 0 30px rgba(147,51,234,0.3)', borderRadius: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.2rem' }}>
              <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 900, color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                🌙 Extended-Hours Limit Order
              </h3>
              <button onClick={() => setShowExtModal(false)} style={{ background: 'transparent', border: 'none', color: '#888', fontSize: '1.4rem', cursor: 'pointer' }}>×</button>
            </div>
            
            <p style={{ fontSize: '0.82rem', color: 'var(--color-text-secondary)', marginBottom: '1.5rem', lineHeight: '1.5' }}>
              Pre-market (04:00 - 09:30 EST) and After-hours (16:00 - 20:00 EST) <strong>do not support Market Orders</strong>. This submits a Limit Order with Extended-Hours support directly to Alpaca.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#aaa', marginBottom: '4px', fontWeight: 700 }}>Ticker Symbol</label>
                <input
                  type="text"
                  value={extSymbol}
                  onChange={(e) => setExtSymbol(e.target.value.toUpperCase())}
                  placeholder="e.g. TSLA, NVDA"
                  style={{ width: '100%', padding: '10px 14px', borderRadius: '6px', border: '1px solid #333', background: '#141416', color: '#fff', fontSize: '0.95rem', fontWeight: 800 }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: '#aaa', marginBottom: '4px', fontWeight: 700 }}>Order Side</label>
                  <select
                    value={extSide}
                    onChange={(e) => setExtSide(e.target.value as 'buy' | 'sell')}
                    style={{ width: '100%', padding: '10px 14px', borderRadius: '6px', border: '1px solid #333', background: '#141416', color: '#fff', fontSize: '0.9rem', fontWeight: 800 }}
                  >
                    <option value="sell">🔴 SELL / CLOSE</option>
                    <option value="buy">🟢 BUY / LONG</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: '#aaa', marginBottom: '4px', fontWeight: 700 }}>Share Quantity</label>
                  <input
                    type="number"
                    value={extQty}
                    onChange={(e) => setExtQty(Math.max(1, parseInt(e.target.value) || 1))}
                    style={{ width: '100%', padding: '10px 14px', borderRadius: '6px', border: '1px solid #333', background: '#141416', color: '#fff', fontSize: '0.95rem', fontWeight: 800 }}
                  />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#aaa', marginBottom: '4px', fontWeight: 700 }}>Limit Price ($)</label>
                <input
                  type="number"
                  step="0.01"
                  value={extPrice}
                  onChange={(e) => setExtPrice(parseFloat(e.target.value) || 0.0)}
                  style={{ width: '100%', padding: '10px 14px', borderRadius: '6px', border: '1px solid rgba(192,132,252,0.5)', background: '#141416', color: '#c084fc', fontSize: '1.1rem', fontWeight: 900 }}
                />
              </div>

              <div style={{ display: 'flex', gap: '10px', marginTop: '1rem' }}>
                <button
                  onClick={() => setShowExtModal(false)}
                  style={{ flex: 1, padding: '12px', borderRadius: '8px', border: '1px solid #333', background: '#18181b', color: '#ccc', fontWeight: 700, cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleSendExtendedHoursOrder}
                  disabled={actionLoading !== null}
                  style={{ flex: 2, padding: '12px', borderRadius: '8px', border: 'none', background: 'linear-gradient(135deg, #7c3aed 0%, #9333ea 100%)', color: '#fff', fontWeight: 900, fontSize: '0.95rem', cursor: 'pointer', boxShadow: '0 4px 15px rgba(147,51,234,0.4)' }}
                >
                  {actionLoading === 'ext_order' ? '⏳ Submitting...' : '⚡ Submit Extended-Hours Limit Order'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
