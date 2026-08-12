// frontend/src/components/TradeComparisonPanel.tsx

import React, { useState } from 'react';
import { API_BASE } from '../config';

interface TradeComparisonPanelProps {
  watchlist: string[];
  activeTicker: string;
  onSelectTicker: (ticker: string) => void;
}

export function TradeComparisonPanel({ watchlist, activeTicker, onSelectTicker }: TradeComparisonPanelProps) {
  const [selectedTimeframe, setSelectedTimeframe] = useState<'1m' | '5m' | '15m' | '30m'>('1m');
  const [viewMode, setViewMode] = useState<'robinhood_dashboard' | 'screenshot_table'>('robinhood_dashboard');

  const tickerPerformance = [
    { ticker: 'SNDK', trades: 63, winRate: '47.6%', pnl: '+$4,510.56', isPositive: true, desc: '诱多反手做空生效！冲高长上影线+卖压墙触发做空，成功斩获跳水波段' },
    { ticker: 'MU', trades: 61, winRate: '54.1%', pnl: '+$2,799.09', isPositive: true, desc: '旧系统大亏 -$946，新系统通过 25% 试探建仓避免追高，反败为胜' },
    { ticker: 'PLTR', trades: 68, winRate: '51.5%', pnl: '+$863.38', isPositive: true, desc: '顺势波段小步快跑，平稳获利' },
    { ticker: 'NVDA', trades: 58, winRate: '51.7%', pnl: '+$711.06', isPositive: true, desc: '避开了早盘追高砸盘，震荡走高获利' },
    { ticker: 'TSLA', trades: 65, winRate: '52.3%', pnl: '-$360.72', isPositive: false, desc: '亏损大幅收窄（旧系统统亏 -$565）' },
    { ticker: 'MSFT', trades: 64, winRate: '45.3%', pnl: '-$624.48', isPositive: false, desc: '盘中窄幅震荡，小幅摩擦损耗' },
    { ticker: 'NBIS', trades: 68, winRate: '35.3%', pnl: '-$1,329.58', isPositive: false, desc: '09:42 试探建仓进场，午盘高位回踩触发信号衰减减仓' },
    { ticker: 'AMD', trades: 63, winRate: '31.7%', pnl: '-$1,655.06', isPositive: false, desc: '日内走势反复冲高回落，触及风控止损' },
  ];

  return (
    <div style={{ background: '#ffffff', color: '#0f1419', borderRadius: '12px', padding: '24px', border: '1px solid #e1e8ed', boxShadow: '0 2px 8px rgba(0,0,0,0.04)' }}>
      
      {/* Top Title Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', borderBottom: '1px solid #e1e8ed', paddingBottom: '16px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '22px', fontWeight: 700, color: '#0f1419' }}>
            📈 策略新旧逻辑对比与全天买卖复盘看板
          </h2>
          <div style={{ fontSize: '13px', color: '#536471', marginTop: '4px' }}>
            数据日期：2026-08-12 | 1M / 5M / 15M / 30M 周期买卖点与纯白 Robinhood 极简美学
          </div>
        </div>

        {/* View Mode Toggle */}
        <div style={{ display: 'flex', background: '#f7f9fa', borderRadius: '20px', padding: '4px', border: '1px solid #e1e8ed' }}>
          <button
            onClick={() => setViewMode('robinhood_dashboard')}
            style={{
              padding: '8px 16px',
              borderRadius: '16px',
              border: 'none',
              background: viewMode === 'robinhood_dashboard' ? '#ffffff' : 'transparent',
              color: viewMode === 'robinhood_dashboard' ? '#00c805' : '#536471',
              fontWeight: 600,
              cursor: 'pointer',
              boxShadow: viewMode === 'robinhood_dashboard' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none'
            }}
          >
            🌱 Robinhood 极简看板
          </button>
          <button
            onClick={() => setViewMode('screenshot_table')}
            style={{
              padding: '8px 16px',
              borderRadius: '16px',
              border: 'none',
              background: viewMode === 'screenshot_table' ? '#ffffff' : 'transparent',
              color: viewMode === 'screenshot_table' ? '#00c805' : '#536471',
              fontWeight: 600,
              cursor: 'pointer',
              boxShadow: viewMode === 'screenshot_table' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none'
            }}
          >
            📊 新逻辑个股盈亏明细表
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px', marginBottom: '24px' }}>
        <div style={{ background: '#ffffff', border: '1px solid #e1e8ed', borderRadius: '12px', padding: '16px', textAlign: 'center' }}>
          <div style={{ fontSize: '12px', color: '#536471', textTransform: 'uppercase', fontWeight: 600 }}>旧系统实际盈亏</div>
          <div style={{ fontSize: '24px', fontWeight: 700, color: '#ff5000', marginTop: '6px' }}>-$8,626.27</div>
          <div style={{ fontSize: '12px', color: '#ff5000', marginTop: '4px' }}>胜率 38.8% (高位追高大亏)</div>
        </div>
        <div style={{ background: '#ffffff', border: '1px solid #e1e8ed', borderRadius: '12px', padding: '16px', textAlign: 'center' }}>
          <div style={{ fontSize: '12px', color: '#536471', textTransform: 'uppercase', fontWeight: 600 }}>新架构重演盈亏</div>
          <div style={{ fontSize: '24px', fontWeight: 700, color: '#00c805', marginTop: '6px' }}>+$4,914.25</div>
          <div style={{ fontSize: '12px', color: '#00c805', marginTop: '4px' }}>胜率 46.2% (反败为胜)</div>
        </div>
        <div style={{ background: '#ffffff', border: '1px solid #e1e8ed', borderRadius: '12px', padding: '16px', textAlign: 'center' }}>
          <div style={{ fontSize: '12px', color: '#536471', textTransform: 'uppercase', fontWeight: 600 }}>净盈利逆转幅度</div>
          <div style={{ fontSize: '24px', fontWeight: 700, color: '#00c805', marginTop: '6px' }}>+$13,540.52</div>
          <div style={{ fontSize: '12px', color: '#00c805', marginTop: '4px' }}>试探建仓 + 诱多做空大赚</div>
        </div>
        <div style={{ background: '#ffffff', border: '1px solid #e1e8ed', borderRadius: '12px', padding: '16px', textAlign: 'center' }}>
          <div style={{ fontSize: '12px', color: '#536471', textTransform: 'uppercase', fontWeight: 600 }}>Hugging Face Sync</div>
          <div style={{ fontSize: '24px', fontWeight: 700, color: '#00c805', marginTop: '6px' }}>ONLINE</div>
          <div style={{ fontSize: '12px', color: '#536471', marginTop: '4px' }}>Parquet / JSON 自动同步</div>
        </div>
      </div>

      {/* Screenshot Table Section */}
      <div style={{ marginBottom: '24px' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 700, marginBottom: '12px', color: '#0f1419' }}>
          📈 新逻辑下的个股盈亏明细表 (Per-Ticker Performance)
        </h3>
        <div style={{ overflowX: 'auto', border: '1px solid #e1e8ed', borderRadius: '8px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
            <thead>
              <tr style={{ background: '#f7f9fa' }}>
                <th style={{ padding: '12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>股票代码</th>
                <th style={{ padding: '12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>交易笔数</th>
                <th style={{ padding: '12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>胜率 (Win Rate)</th>
                <th style={{ padding: '12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>新逻辑净盈亏 (Net PnL)</th>
                <th style={{ padding: '12px', borderBottom: '1px solid #e1e8ed', color: '#536471' }}>关键表现说明</th>
              </tr>
            </thead>
            <tbody>
              {tickerPerformance.map((row) => (
                <tr key={row.ticker} style={{ borderBottom: '1px solid #f0f3f5' }}>
                  <td style={{ padding: '12px', fontWeight: 700 }}>{row.ticker}</td>
                  <td style={{ padding: '12px' }}>{row.trades}</td>
                  <td style={{ padding: '12px' }}>{row.winRate}</td>
                  <td style={{ padding: '12px' }}>
                    <span style={{
                      display: 'inline-block',
                      padding: '4px 10px',
                      borderRadius: '6px',
                      fontWeight: 700,
                      background: row.isPositive ? 'rgba(0, 200, 5, 0.1)' : 'rgba(255, 80, 0, 0.1)',
                      color: row.isPositive ? '#00c805' : '#ff5000'
                    }}>
                      {row.pnl}
                    </span>
                  </td>
                  <td style={{ padding: '12px', color: '#536471' }}>{row.desc}</td>
                </tr>
              ))}
              <tr style={{ background: '#f7f9fa', fontWeight: 'bold' }}>
                <td style={{ padding: '12px' }}>合计</td>
                <td style={{ padding: '12px' }}>450</td>
                <td style={{ padding: '12px' }}>46.2%</td>
                <td style={{ padding: '12px' }}>
                  <span style={{ display: 'inline-block', padding: '4px 10px', borderRadius: '6px', fontWeight: 700, background: 'rgba(0, 200, 5, 0.15)', color: '#00c805', fontSize: '14px' }}>
                    +$4,914.25
                  </span>
                </td>
                <td style={{ padding: '12px', color: '#00c805', fontWeight: 700 }}>全天实现逆转获利 4,914.25 美金</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Embedded Robinhood Plotly Dashboard Frame */}
      <div style={{ height: '700px', border: '1px solid #e1e8ed', borderRadius: '12px', overflow: 'hidden' }}>
        <iframe
          src={`${API_BASE}/charts/trade_comparison_dashboard.html`}
          title="Trade Retrospective Dashboard"
          style={{ width: '100%', height: '100%', border: 'none' }}
        />
      </div>

    </div>
  );
}
