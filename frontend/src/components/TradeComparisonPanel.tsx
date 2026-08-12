// frontend/src/components/TradeComparisonPanel.tsx

import React, { useState, useEffect } from 'react';
import { StockChart } from './StockChart';
import { API_BASE } from '../config';

interface TradeComparisonPanelProps {
  watchlist: string[];
  activeTicker: string;
  onSelectTicker: (ticker: string) => void;
}

export function TradeComparisonPanel({ watchlist, activeTicker, onSelectTicker }: TradeComparisonPanelProps) {
  const [selectedTicker, setSelectedTicker] = useState<string>('SNDK');
  const [selectedInterval, setSelectedInterval] = useState<'1m' | '5m' | '15m' | '30m'>('1m');
  const [loading, setLoading] = useState<boolean>(true);
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const res = await fetch(`${API_BASE}/api/trade_comparison_data?ticker=${selectedTicker}&interval=${selectedInterval}`);
        const json = await res.json();
        if (json.success) {
          setData(json);
        }
      } catch (e) {
        console.error("Failed to fetch trade comparison data:", e);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [selectedTicker, selectedInterval]);

  const tickerList = [
    { ticker: 'SNDK', pnl: '+$4,510.56', positive: true },
    { ticker: 'MU', pnl: '+$2,799.09', positive: true },
    { ticker: 'PLTR', pnl: '+$863.38', positive: true },
    { ticker: 'NVDA', pnl: '+$711.06', positive: true },
    { ticker: 'TSLA', pnl: '-$360.72', positive: false },
    { ticker: 'MSFT', pnl: '-$624.48', positive: false },
    { ticker: 'NBIS', pnl: '-$1,329.58', positive: false },
    { ticker: 'AMD', pnl: '-$1,655.06', positive: false },
  ];

  // Convert candles to StockChart format
  const candles = (data?.candles || []).map((c: any) => ({
    time: c.time,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
    volume: c.volume,
    vwap: null,
    ema_9: null,
    ema_21: null,
    ema_50: null,
    rsi: null,
    squeeze: false
  }));

  // Map trades onto chart markers
  const markers: any[] = [];
  (data?.trades || []).forEach((t: any) => {
    // Parse time string to timestamp if possible
    const enTimeParts = t.entry_time.split(" ")[1]?.split(":") || ["09", "30"];
    const exTimeParts = t.exit_time.split(" ")[1]?.split(":") || ["10", "00"];
    
    markers.push({
      time: Math.floor(new Date(t.entry_time).getTime() / 1000) || candles[0]?.time || 0,
      position: t.side === 'LONG' ? 'belowBar' : 'aboveBar',
      color: t.side === 'LONG' ? '#00c805' : '#a855f7',
      shape: t.side === 'LONG' ? 'arrowUp' : 'arrowDown',
      text: t.side === 'LONG' ? `🛒 BUY LONG @ $${t.entry_price.toFixed(2)}` : `📉 SHORT @ $${t.entry_price.toFixed(2)}`
    });

    markers.push({
      time: Math.floor(new Date(t.exit_time).getTime() / 1000) || candles[candles.length - 1]?.time || 0,
      position: 'aboveBar',
      color: '#ff5000',
      shape: 'arrowDown',
      text: `🔴 EXIT @ $${t.exit_price.toFixed(2)} (持仓 ${t.duration_min} 分钟 | PnL: $${t.pnl.toFixed(2)})`
    });
  });

  return (
    <div style={{ background: '#ffffff', color: '#0f1419', borderRadius: '12px', padding: '24px', border: '1px solid #e1e8ed', boxShadow: '0 2px 8px rgba(0,0,0,0.04)' }}>
      
      {/* Header Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', borderBottom: '1px solid #e1e8ed', paddingBottom: '16px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '22px', fontWeight: 700, color: '#0f1419' }}>
            🌱 真实 K 线买卖位置与持仓复盘看板
          </h2>
          <div style={{ fontSize: '13px', color: '#536471', marginTop: '4px' }}>
            点击下方股票按钮（如 SNDK, MU），直接查看该股票全天真实 K 线及每一个买卖点与持仓分钟数
          </div>
        </div>

        {/* Timeframe Selector Pills */}
        <div style={{ display: 'flex', background: '#f7f9fa', borderRadius: '20px', padding: '4px', border: '1px solid #e1e8ed' }}>
          {(['1m', '5m', '15m', '30m'] as const).map(tf => (
            <button
              key={tf}
              onClick={() => setSelectedInterval(tf)}
              style={{
                padding: '6px 16px',
                borderRadius: '16px',
                border: 'none',
                background: selectedInterval === tf ? '#ffffff' : 'transparent',
                color: selectedInterval === tf ? '#00c805' : '#536471',
                fontWeight: 700,
                cursor: 'pointer',
                boxShadow: selectedInterval === tf ? '0 1px 3px rgba(0,0,0,0.1)' : 'none'
              }}
            >
              {tf.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* 1. 个股盈亏明细表 (Screen-shot summary table) */}
      <div style={{ marginBottom: '24px', background: '#ffffff', border: '1px solid #e1e8ed', borderRadius: '12px', padding: '16px' }}>
        <h3 style={{ fontSize: '15px', fontWeight: 700, margin: '0 0 12px 0', color: '#0f1419' }}>
          📈 新逻辑下的个股盈亏明细表 (Per-Ticker Performance)
        </h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ background: '#f7f9fa' }}>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>股票代码</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>交易笔数</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>胜率 (Win Rate)</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>新逻辑净盈亏 (Net PnL)</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>关键表现说明</th>
              </tr>
            </thead>
            <tbody>
              {(data?.summary_table || tickerList).map((row: any) => (
                <tr
                  key={row.ticker}
                  onClick={() => { setSelectedTicker(row.ticker); onSelectTicker(row.ticker); }}
                  style={{
                    borderBottom: '1px solid #f0f3f5',
                    background: selectedTicker === row.ticker ? 'rgba(0, 200, 5, 0.05)' : 'transparent',
                    cursor: 'pointer'
                  }}
                >
                  <td style={{ padding: '10px 12px', fontWeight: 700 }}>
                    {row.ticker} {selectedTicker === row.ticker && '👈'}
                  </td>
                  <td style={{ padding: '10px 12px' }}>{row.trades || row.trade_count}</td>
                  <td style={{ padding: '10px 12px' }}>{row.win_rate || row.winRate}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <span style={{
                      display: 'inline-block',
                      padding: '3px 8px',
                      borderRadius: '6px',
                      fontWeight: 700,
                      background: (row.positive ?? (row.pnl && row.pnl.includes('+'))) ? 'rgba(0, 200, 5, 0.12)' : 'rgba(255, 80, 0, 0.12)',
                      color: (row.positive ?? (row.pnl && row.pnl.includes('+'))) ? '#00c805' : '#ff5000'
                    }}>
                      {row.pnl}
                    </span>
                  </td>
                  <td style={{ padding: '10px 12px', color: '#536471' }}>{row.desc}</td>
                </tr>
              ))}
              <tr style={{ background: '#f7f9fa', fontWeight: 'bold' }}>
                <td style={{ padding: '10px 12px' }}>合计</td>
                <td style={{ padding: '10px 12px' }}>450</td>
                <td style={{ padding: '10px 12px' }}>46.2%</td>
                <td style={{ padding: '10px 12px' }}>
                  <span style={{ display: 'inline-block', padding: '4px 10px', borderRadius: '6px', fontWeight: 700, background: 'rgba(0, 200, 5, 0.15)', color: '#00c805' }}>
                    +$4,914.25
                  </span>
                </td>
                <td style={{ padding: '10px 12px', color: '#00c805', fontWeight: 700 }}>全天实现逆转获利 4,914.25 美金</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* 2. Interactive Ticker Switcher Pills */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '13px', fontWeight: 700, color: '#536471' }}>选择观察股票：</span>
        {tickerList.map(item => (
          <button
            key={item.ticker}
            onClick={() => { setSelectedTicker(item.ticker); onSelectTicker(item.ticker); }}
            style={{
              padding: '8px 16px',
              borderRadius: '20px',
              border: selectedTicker === item.ticker ? '2px solid #00c805' : '1px solid #e1e8ed',
              background: selectedTicker === item.ticker ? '#0f1419' : '#ffffff',
              color: selectedTicker === item.ticker ? '#ffffff' : '#0f1419',
              fontWeight: 700,
              fontSize: '13px',
              cursor: 'pointer',
              transition: 'all 0.2s ease'
            }}
          >
            {item.ticker} <span style={{ fontSize: '11px', color: item.positive ? '#00c805' : '#ff5000', marginLeft: '4px' }}>{item.pnl}</span>
          </button>
        ))}
      </div>

      {/* 3. Real TradingView Native K-Line Chart */}
      <div style={{ background: '#000000', borderRadius: '12px', padding: '16px', marginBottom: '24px', border: '1px solid #1e293b' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <div style={{ color: '#ffffff', fontWeight: 700, fontSize: '16px' }}>
            [{selectedTicker}] - 今日 {selectedInterval.toUpperCase()} 真实盘中 K 线图与买卖点标注
          </div>
          <div style={{ fontSize: '12px', color: '#94a3b8' }}>
            🛒 绿色上箭: 买入建仓 | 🟣 紫色下箭: 诱多做空 | 🔴 红色标出: 平仓位置
          </div>
        </div>

        {loading ? (
          <div style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>
            加载 {selectedTicker} ({selectedInterval.toUpperCase()}) 真实 K 线数据中...
          </div>
        ) : candles.length > 0 ? (
          <StockChart candles={candles} markers={markers} />
        ) : (
          <div style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>
            暂无 {selectedTicker} 数据
          </div>
        )}
      </div>

      {/* 4. Matched Trade Execution Ledger Table for Selected Ticker */}
      <div style={{ background: '#ffffff', border: '1px solid #e1e8ed', borderRadius: '12px', padding: '20px' }}>
        <h3 style={{ fontSize: '15px', fontWeight: 700, margin: '0 0 16px 0', color: '#0f1419' }}>
          📋 [{selectedTicker}] 今日买卖时间与持仓分钟数全明细 ({data?.trades?.length || 0} 笔交易)
        </h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ background: '#f7f9fa' }}>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>股票</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>方向</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>买入/做空时间</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>入场价</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>平仓时间</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>平仓价</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>持仓时长</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>成交股数</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>名义金额</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>净盈亏 ($)</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>收益率 (%)</th>
                <th style={{ padding: '10px 12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>离场原因</th>
              </tr>
            </thead>
            <tbody>
              {(data?.trades || []).length === 0 ? (
                <tr><td colSpan={12} style={{ textAlign: 'center', padding: '20px', color: '#536471' }}>今日暂无该股票触发平仓的交易记录</td></tr>
              ) : (
                (data?.trades || []).map((t: any, idx: number) => {
                  const enTime = t.entry_time?.split(" ")[1]?.substring(0, 8) || t.entry_time;
                  const exTime = t.exit_time?.split(" ")[1]?.substring(0, 8) || t.exit_time;
                  const isPos = t.pnl > 0;
                  return (
                    <tr key={idx} style={{ borderBottom: '1px solid #f0f3f5' }}>
                      <td style={{ padding: '10px 12px', fontWeight: 700 }}>{t.ticker}</td>
                      <td style={{ padding: '10px 12px' }}>
                        <span style={{
                          padding: '3px 8px', borderRadius: '12px', fontSize: '11px', fontWeight: 700,
                          background: t.side === 'LONG' ? 'rgba(0, 200, 5, 0.12)' : 'rgba(255, 80, 0, 0.12)',
                          color: t.side === 'LONG' ? '#00c805' : '#ff5000'
                        }}>
                          {t.side}
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px' }}>{enTime}</td>
                      <td style={{ padding: '10px 12px' }}>${t.entry_price.toFixed(2)}</td>
                      <td style={{ padding: '10px 12px' }}>{exTime}</td>
                      <td style={{ padding: '10px 12px' }}>${t.exit_price.toFixed(2)}</td>
                      <td style={{ padding: '10px 12px', fontWeight: 700, color: '#0f1419' }}>{t.duration_min} 分钟</td>
                      <td style={{ padding: '10px 12px' }}>{t.shares} 股</td>
                      <td style={{ padding: '10px 12px' }}>${t.notional ? t.notional.toLocaleString('en-US', { maximumFractionDigits: 0 }) : (t.shares * t.entry_price).toFixed(0)}</td>
                      <td style={{ padding: '10px 12px', fontWeight: 700, color: isPos ? '#00c805' : '#ff5000' }}>
                        ${t.pnl >= 0 ? '+' : ''}{t.pnl.toFixed(2)}
                      </td>
                      <td style={{ padding: '10px 12px', fontWeight: 700, color: isPos ? '#00c805' : '#ff5000' }}>
                        {t.pnl_pct >= 0 ? '+' : ''}{t.pnl_pct.toFixed(2)}%
                      </td>
                      <td style={{ padding: '10px 12px', color: '#536471' }}>{t.reason}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}
