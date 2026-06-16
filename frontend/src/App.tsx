// frontend/src/App.tsx

import React, { useState, useEffect } from 'react';
import { StockChart } from './components/StockChart';
import { PortfolioStats } from './components/PortfolioStats';
import { LedgerTable } from './components/LedgerTable';
import { StrategySettings } from './components/StrategySettings';
import { CompanyInfoCard } from './components/CompanyInfoCard';
import { PatternLog } from './components/PatternLog';
import { ScannerPanel } from './components/ScannerPanel';

interface SummaryData {
  initial_cash: number;
  final_equity: number;
  net_pnl: number;
  pnl_pct: number;
  total_trades: number;
  round_trips: number;
  win_rate: number;
  commission: number;
}

interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap: number | null;
  ema_9: number | null;
  ema_21: number | null;
  ema_50: number | null;
  rsi: number | null;
  squeeze: boolean;
}

interface LedgerItem {
  timestamp: string;
  action: 'BUY' | 'SELL';
  ticker: string;
  shares: number;
  market_price: number;
  execution_price: number;
  commission: number;
  total_value: number;
  total_cost?: number;
  revenue?: number;
  realized_pnl?: number;
  cash_remaining: number;
}

interface ChartMarker {
  time: number;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown';
  text: string;
}

interface PatternEvent {
  time: string;
  ticker: string;
  pattern: string;
  type: 'bullish' | 'bearish';
  price: number;
  desc: string;
}

interface StrategyParams {
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

interface BacktestResponse {
  success: boolean;
  ticker: string;
  period: string;
  interval: string;
  summary: SummaryData;
  ledger: LedgerItem[];
  candles: CandleData[];
  markers: ChartMarker[];
  equity_curve: { time: number; value: number }[];
  patterns_log: PatternEvent[];
  error?: string;
}

interface CompanyInfo {
  name: string;
  sector: string;
  industry: string;
  market_cap: number;
  description: string;
}

const DEFAULT_STRATEGY_PARAMS: StrategyParams = {
  strategy_mode: 'consensus',
  stop_loss_pct: 0.01,
  profit_target_pct: 0.015,
  trailing_stop_mode: 'atr',
  trailing_stop_atr_mult: 2.0,
  rsi_threshold_buy: 65,
  risk_per_trade_pct: 0.01,
  max_position_size_pct: 0.50,
  position_sizing_mode: 'atr',
  commission_per_share: 0.005,
  slippage_rate: 0.0003
};

const INTERVAL_LABELS: Record<string, string> = {
  "1m": "1分钟",
  "5m": "5分钟",
  "15m": "15分钟",
  "30m": "30分钟",
  "1h": "1小时",
  "1d": "日线级"
};

function App() {
  const [watchlist, setWatchlist] = useState<string[]>(["TSLA", "NVDA", "AAPL", "MSFT", "AMD"]);
  const [newTickerInput, setNewTickerInput] = useState<string>('');
  
  const [activeTicker, setActiveTicker] = useState<string>('TSLA');
  const [activeInterval, setActiveInterval] = useState<string>('1m');
  const [strategyParams, setStrategyParams] = useState<StrategyParams>(DEFAULT_STRATEGY_PARAMS);
  
  const [loading, setLoading] = useState<boolean>(true);
  const [data, setData] = useState<BacktestResponse | null>(null);
  const [sidebarPrices, setSidebarPrices] = useState<Record<string, number>>({});
  
  // 公司元数据状态
  const [companyInfo, setCompanyInfo] = useState<CompanyInfo | null>(null);
  const [infoLoading, setInfoLoading] = useState<boolean>(false);

  // 1. 获取回测仿真数据 (参数改变自动重算)
  useEffect(() => {
    const fetchBacktestData = async () => {
      setLoading(true);
      try {
        const queryParams = new URLSearchParams({
          ticker: activeTicker,
          interval: activeInterval,
          strategy_mode: strategyParams.strategy_mode,
          stop_loss_pct: String(strategyParams.stop_loss_pct),
          profit_target_pct: String(strategyParams.profit_target_pct),
          trailing_stop_mode: strategyParams.trailing_stop_mode,
          trailing_stop_atr_mult: String(strategyParams.trailing_stop_atr_mult),
          rsi_threshold_buy: String(strategyParams.rsi_threshold_buy),
          risk_per_trade_pct: String(strategyParams.risk_per_trade_pct),
          max_position_size_pct: String(strategyParams.max_position_size_pct),
          position_sizing_mode: strategyParams.position_sizing_mode,
          commission_per_share: String(strategyParams.commission_per_share),
          slippage_rate: String(strategyParams.slippage_rate)
        });

        const res = await fetch(`http://127.0.0.1:8000/api/backtest?${queryParams.toString()}`);
        const json: BacktestResponse = await res.json();
        
        if (json.success) {
          setData(json);
          // 更新侧边栏收盘价
          if (json.candles.length > 0) {
            const lastCandle = json.candles[json.candles.length - 1];
            setSidebarPrices(prev => ({
              ...prev,
              [activeTicker]: lastCandle.close
            }));
          }
        } else {
          console.error("回测运行失败:", json.error);
        }
      } catch (e) {
        console.error("连接 API 服务器失败:", e);
      } finally {
        setLoading(false);
      }
    };

    fetchBacktestData();
  }, [activeTicker, activeInterval, strategyParams]);

  // 2. 获取公司详情介绍
  useEffect(() => {
    const fetchCompanyDetails = async () => {
      setInfoLoading(true);
      try {
        const res = await fetch(`http://127.0.0.1:8000/api/company_info?ticker=${activeTicker}`);
        const json = await res.json();
        setCompanyInfo(json);
      } catch (e) {
        console.error("获取公司介绍失败:", e);
      } finally {
        setInfoLoading(false);
      }
    };

    fetchCompanyDetails();
  }, [activeTicker]);

  // 3. 异步获取侧边栏其它股票的基本收盘价
  useEffect(() => {
    const fetchInitialPrices = async () => {
      for (const ticker of watchlist) {
        if (ticker === activeTicker) continue;
        try {
          const res = await fetch(`http://127.0.0.1:8000/api/backtest?ticker=${ticker}&interval=1d`);
          const json: BacktestResponse = await res.json();
          if (json.success && json.candles.length > 0) {
            const lastCandle = json.candles[json.candles.length - 1];
            setSidebarPrices(prev => ({
              ...prev,
              [ticker]: lastCandle.close
            }));
          }
        } catch (e) {}
      }
    };
    fetchInitialPrices();
  }, [watchlist]);

  const handleTickerChange = (ticker: string) => {
    setActiveTicker(ticker);
  };

  const handleIntervalChange = (interval: string) => {
    setActiveInterval(interval);
  };

  // 添加自选股
  const handleAddTicker = (e: React.FormEvent) => {
    e.preventDefault();
    const cleanTicker = newTickerInput.trim().toUpperCase();
    if (cleanTicker && !watchlist.includes(cleanTicker)) {
      setWatchlist([...watchlist, cleanTicker]);
      setActiveTicker(cleanTicker);
      setNewTickerInput('');
    }
  };

  // 删除自选股
  const handleRemoveTicker = (tickerToRemove: string, e: React.MouseEvent) => {
    e.stopPropagation(); // 阻止触发切换股票
    const newWatchlist = watchlist.filter(t => t !== tickerToRemove);
    setWatchlist(newWatchlist);
    if (activeTicker === tickerToRemove && newWatchlist.length > 0) {
      setActiveTicker(newWatchlist[0]);
    }
  };

  const resetStrategyParams = () => {
    setStrategyParams(DEFAULT_STRATEGY_PARAMS);
  };

  // 盈亏汇总
  const hasPnL = data && data.summary;
  const netPnL = hasPnL ? data.summary.net_pnl : 0;
  const isPnLUp = netPnL >= 0;
  const pnlColorClass = isPnLUp ? 'up' : 'down';
  const pnlSign = isPnLUp ? '+' : '';

  return (
    <div>
      {/* 顶部标题栏 */}
      <header className="header-bar">
        <div className="logo">
          Quont<span>.ai</span>
        </div>
        <div style={{ color: 'var(--color-text-secondary)', fontSize: '0.9rem', fontWeight: 600 }}>
          Professional AI 量化交易模拟回测终端
        </div>
      </header>

      {/* 主布局网格 */}
      <div className="app-container">
        {/* 左侧内容区 */}
        <main className="main-content">
          {loading ? (
            <div className="loader-container">
              正在模拟重播 {activeTicker} ({INTERVAL_LABELS[activeInterval] || activeInterval}) 数据并计算 K线 形态...
            </div>
          ) : data ? (
            <>
              {/* 账户资产价值计数器 */}
              <div className="pnl-header-container">
                <div>
                  <div className="portfolio-value">
                    ${data.summary.final_equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div className={`pnl-text ${pnlColorClass}`}>
                    {pnlSign}${data.summary.net_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({pnlSign}{data.summary.pnl_pct.toFixed(2)}%) 当前区间盈亏
                  </div>
                </div>
                
                {/* 周期切换器 */}
                <div className="interval-picker-container">
                  <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', fontWeight: 600 }}>切换 K 线周期</span>
                  <div className="time-tabs" style={{ marginTop: 0 }}>
                    {Object.entries(INTERVAL_LABELS).map(([key, label]) => (
                      <button
                        key={key}
                        className={`tab-btn ${activeInterval === key ? 'active' : ''}`}
                        onClick={() => handleIntervalChange(key)}
                      >
                        {key.toUpperCase()} ({label})
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* 核心 K 线图表 */}
              <div className="chart-wrapper">
                <StockChart candles={data.candles} markers={data.markers} />
              </div>

              {/* 策略设置与形态识别日志 并排展示 */}
              <div className="strategy-patterns-grid">
                <StrategySettings 
                  params={strategyParams} 
                  onChange={setStrategyParams} 
                  onReset={resetStrategyParams} 
                />
                <PatternLog patterns={data.patterns_log} />
              </div>

              {/* 选股扫描面板 */}
              <ScannerPanel customTickers={watchlist} onSelectTicker={setActiveTicker} />

              {/* 账户业绩统计 */}
              <PortfolioStats summary={data.summary} />

              {/* 交易明细账本 */}
              <LedgerTable ledger={data.ledger} />
            </>
          ) : (
            <div className="loader-container">
              未能连接到量化服务器，请确保 FastAPI 后端服务运行在 http://127.0.0.1:8000
            </div>
          )}
        </main>

        {/* 右侧边栏自选股列表 & 公司档案 */}
        <aside className="sidebar">
          <h4 className="sidebar-title">自选监控池 (Watchlist)</h4>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {watchlist.map((ticker) => {
              const price = sidebarPrices[ticker];
              const isActive = ticker === activeTicker;
              return (
                <div
                  key={ticker}
                  className={`watchlist-item ${isActive ? 'active' : ''}`}
                  onClick={() => handleTickerChange(ticker)}
                  style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                >
                  <div>
                    <span className="watchlist-ticker">{ticker}</span>
                  </div>
                  
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span className="watchlist-price">
                      {price ? `$${price.toFixed(2)}` : '...'}
                    </span>
                    <button 
                      onClick={(e) => handleRemoveTicker(ticker, e)}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--color-text-secondary)',
                        fontSize: '0.9rem',
                        cursor: 'pointer',
                        padding: '0 4px'
                      }}
                      onMouseEnter={(e) => e.currentTarget.style.color = 'var(--color-red)'}
                      onMouseLeave={(e) => e.currentTarget.style.color = 'var(--color-text-secondary)'}
                    >
                      ×
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {/* 添加自选股表单 */}
          <form onSubmit={handleAddTicker} style={{ display: 'flex', gap: '8px', marginTop: '0.25rem' }}>
            <input 
              type="text" 
              placeholder="添加股票代码, 如 NVDA" 
              value={newTickerInput}
              onChange={(e) => setNewTickerInput(e.target.value)}
              style={{
                flex: 1,
                background: '#1c1c1e',
                border: '1px solid var(--color-border)',
                borderRadius: '6px',
                padding: '6px 10px',
                color: '#ffffff',
                fontSize: '0.85rem'
              }}
            />
            <button 
              type="submit"
              style={{
                background: 'var(--color-green)',
                color: '#000000',
                border: 'none',
                borderRadius: '6px',
                padding: '6px 12px',
                fontWeight: 700,
                fontSize: '0.85rem',
                cursor: 'pointer'
              }}
            >
              添加
            </button>
          </form>

          {/* 选中的公司基本介绍档案 */}
          <div style={{ marginTop: '1rem' }}>
            <CompanyInfoCard ticker={activeTicker} info={companyInfo} loading={infoLoading} />
          </div>
          
          <div style={{ marginTop: 'auto', padding: '1rem', background: '#1c1c1e', border: '1px solid var(--color-border)', borderRadius: '8px', fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
            <strong style={{ color: '#ffffff', display: 'block', marginBottom: '4px' }}>动态回测规则说明:</strong>
            1. **多周期切换**：支持 1m ~ 1d 不同级别。1m-1h 为常规交易时段日内测试，15:55 自动强平。<br />
            2. **形态驱动**：可将检测到的 M顶/W底、锤子线、吞没K线作为策略的触发与防守参考指标。<br />
            3. **智能风控**：启用 ATR 风险对齐仓位后，系统会根据振幅自动收紧/放大买入股数，控制亏损期望。
          </div>
        </aside>
      </div>
    </div>
  );
}

export default App;
