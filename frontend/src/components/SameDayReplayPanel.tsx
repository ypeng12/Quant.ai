// frontend/src/components/SameDayReplayPanel.tsx

import React, { useState, useEffect } from 'react';
import { StockChart } from './StockChart';
import { LedgerTable, type LedgerItem } from './LedgerTable';

interface SameDayReplayPanelProps {
  watchlist: string[];
  activeTicker: string;
  onSelectTicker: (ticker: string) => void;
}

export function SameDayReplayPanel({ watchlist, activeTicker, onSelectTicker }: SameDayReplayPanelProps) {
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [replayData, setReplayData] = useState<any>(null);
  const [focusTime, setFocusTime] = useState<number | undefined>(undefined);

  // Fetch available history dates for active ticker
  useEffect(() => {
    const fetchDates = async () => {
      try {
        const res = await fetch(`http://127.0.0.1:8000/api/replay/available_dates?ticker=${activeTicker}`);
        const json = await res.json();
        if (json.success && json.dates.length > 0) {
          setAvailableDates(json.dates);
          setSelectedDate(json.dates[0]); // default to latest date
        }
      } catch (e) {
        console.error("Failed to fetch available replay dates:", e);
      }
    };
    fetchDates();
  }, [activeTicker]);

  // Load replay data when ticker or selectedDate changes
  useEffect(() => {
    if (!selectedDate) return;
    const loadDayData = async () => {
      setLoading(true);
      setReplayData(null);
      try {
        const params = new URLSearchParams({
          ticker: activeTicker.toUpperCase(),
          date: selectedDate,
          strategy_mode: 'dynamic',
          stop_loss_pct: '0.015',
          profit_target_pct: '0.030',
          trailing_stop_mode: 'atr',
          trailing_stop_atr_mult: '2.0',
          rsi_threshold_buy: '65',
          risk_per_trade_pct: '0.01',
          max_position_size_pct: '0.50',
          commission_per_share: '0.005',
          slippage_rate: '0.0003',
          market_open_focus: 'true'
        });
        const res = await fetch(`http://127.0.0.1:8000/api/replay/data?${params.toString()}`);
        const json = await res.json();
        if (json.success) {
          setReplayData(json);
        }
      } catch (e) {
        console.error("Failed to load same-day replay data:", e);
      } finally {
        setLoading(false);
      }
    };

    loadDayData();
  }, [activeTicker, selectedDate]);

  const ledger: LedgerItem[] = replayData ? replayData.ledger : [];
  const candles = replayData ? replayData.candles : [];
  const markers = replayData ? replayData.markers : [];

  // Calculate day summary metrics
  const calculateDayMetrics = () => {
    if (!ledger || ledger.length === 0) {
      return { pnl: 0, pnlPct: 0, trades: 0, winRate: 0, commission: 0 };
    }
    let totalPnl = 0;
    let wins = 0;
    let roundTrips = 0;
    let totalComm = 0;

    for (const item of ledger) {
      totalComm += item.commission || 0;
      if (item.action === 'SELL' && item.realized_pnl !== undefined) {
        roundTrips += 1;
        totalPnl += item.realized_pnl;
        if (item.realized_pnl > 0) wins += 1;
      }
    }
    const winRate = roundTrips > 0 ? (wins / roundTrips) * 100 : 0;
    const pnlPct = (totalPnl / 100000) * 100;
    return { pnl: totalPnl, pnlPct, trades: roundTrips, winRate, commission: totalComm };
  };

  const metrics = calculateDayMetrics();
  const isProfit = metrics.pnl >= 0;

  const handleRowClick = (item: LedgerItem) => {
    const t = Math.floor(new Date(item.timestamp).getTime() / 1000);
    setFocusTime(t);
  };

  return (
    <div className="fade-in">
      {/* 顶部极简过滤条：股票切换器 + 日期选择器 */}
      <div className="card" style={{ marginBottom: '1.25rem', padding: '1rem 1.25rem', background: '#09090b', border: '1px solid var(--color-border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          
          {/* 快捷股票选择按钮组 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', fontWeight: 700 }}>标的股票:</span>
            {watchlist.map((ticker) => (
              <button
                key={ticker}
                onClick={() => onSelectTicker(ticker)}
                style={{
                  background: activeTicker === ticker ? 'var(--color-green)' : '#1c1c1e',
                  color: activeTicker === ticker ? '#000000' : '#ffffff',
                  border: 'none',
                  borderRadius: '6px',
                  padding: '6px 14px',
                  fontWeight: 800,
                  fontSize: '0.85rem',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease'
                }}
              >
                {ticker}
              </button>
            ))}
          </div>

          {/* 交易日期选择 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', fontWeight: 700 }}>复盘日期:</span>
            <select
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              style={{
                background: '#141416',
                border: '1px solid #333',
                color: '#fff',
                padding: '6px 12px',
                borderRadius: '6px',
                fontSize: '0.85rem',
                fontWeight: 700,
                cursor: 'pointer'
              }}
            >
              {availableDates.map(d => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* 极简日内盈亏卡片 */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', marginBottom: '1.25rem' }}>
        <div className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1rem' }}>
          <span className="stat-label">当日结算净盈亏</span>
          <span className="stat-value" style={{ fontSize: '1.4rem', color: isProfit ? 'var(--color-green)' : 'var(--color-red)' }}>
            {isProfit ? '+' : ''}${metrics.pnl.toFixed(2)} ({isProfit ? '+' : ''}{metrics.pnlPct.toFixed(2)}%)
          </span>
        </div>
        <div className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1rem' }}>
          <span className="stat-label">成交笔数 (Round Trips)</span>
          <span className="stat-value" style={{ fontSize: '1.4rem', color: '#ffffff' }}>
            {metrics.trades} 笔
          </span>
        </div>
        <div className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1rem' }}>
          <span className="stat-label">日内胜率 (Win Rate)</span>
          <span className="stat-value" style={{ fontSize: '1.4rem', color: 'var(--color-green)' }}>
            {metrics.winRate.toFixed(1)}%
          </span>
        </div>
        <div className="stat-card" style={{ background: '#09090b', border: '1px solid var(--color-border)', padding: '1rem' }}>
          <span className="stat-label">交易摩擦损耗 (Commission)</span>
          <span className="stat-value" style={{ fontSize: '1.4rem', color: 'var(--color-text-secondary)' }}>
            ${metrics.commission.toFixed(2)}
          </span>
        </div>
      </div>

      {/* 图表展示卡片 */}
      <div className="card" style={{ marginBottom: '1.25rem', padding: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h3 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 800, color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
            📈 {activeTicker} 当日 K 线图 & 买卖标记透视 ({selectedDate})
          </h3>
          <span style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)' }}>
            🟢 箭头为买入点 (BUY) | 🔴 箭头为卖出点 (SELL)
          </span>
        </div>

        {loading ? (
          <div className="loader-container" style={{ padding: '4rem', textAlign: 'center' }}>
            正在加载 {activeTicker} ({selectedDate}) 同天行情与买卖标记...
          </div>
        ) : (
          <StockChart candles={candles} markers={markers} focusTime={focusTime} />
        )}
      </div>

      {/* 当日买卖流水账本 */}
      <div className="card" style={{ padding: '1rem' }}>
        <h3 style={{ margin: '0 0 12px 0', fontSize: '0.95rem', fontWeight: 800, color: '#fff' }}>
          📜 当日买卖明细账本 (点击可定位图表标记)
        </h3>
        <LedgerTable ledger={ledger} onRowClick={handleRowClick} />
      </div>
    </div>
  );
}
