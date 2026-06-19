// frontend/src/App.tsx

import React, { useState, useEffect, useRef } from 'react';
import { StockChart } from './components/StockChart';
import { PortfolioStats } from './components/PortfolioStats';
import { LedgerTable, type LedgerItem } from './components/LedgerTable';
import { IntradayZoomChart } from './components/IntradayZoomChart';
import { StrategySettings, type StrategyParams } from './components/StrategySettings';
import { CompanyInfoCard } from './components/CompanyInfoCard';
import { PatternLog } from './components/PatternLog';
import { ScannerPanel } from './components/ScannerPanel';
import { ChatPanel } from './components/ChatPanel';
import { EquityCurve } from './components/EquityCurve';
import { RegimeBreakdown } from './components/RegimeBreakdown';
import { ResearchReportPanel } from './components/ResearchReportPanel';
import { WalkForwardPanel } from './components/WalkForwardPanel';
import { ExperimentCompare } from './components/ExperimentCompare';

interface SummaryData {
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

interface RegimeData {
  regime: string;
  total_pnl: number;
  trade_count: number;
  win_rate: number;
  wins: number;
  losses: number;
  commission: number;
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
  drawdown_curve: { time: number; value: number }[];
  regime_breakdown: RegimeData[];
  regime_distribution: Record<string, number>;
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
  strategy_mode: 'opening_breakout',
  stop_loss_pct: 0.015,
  profit_target_pct: 0.030,
  trailing_stop_mode: 'atr',
  trailing_stop_atr_mult: 2.0,
  rsi_threshold_buy: 65,
  risk_per_trade_pct: 0.01,
  max_position_size_pct: 0.50,
  position_sizing_mode: 'atr',
  commission_per_share: 0.005,
  slippage_rate: 0.0003,
  market_open_focus: true
};

const INTERVAL_LABELS: Record<string, string> = {
  "1m": "1 Min",
  "5m": "5 Min",
  "15m": "15 Min",
  "30m": "30 Min",
  "1h": "1 Hour",
  "1d": "Daily"
};

type ActiveTab = 'dashboard' | 'research' | 'report' | 'walkforward' | 'experiments' | 'replay';

function App() {
  const [watchlist, setWatchlist] = useState<string[]>(["TSLA", "NVDA", "AAPL", "MSFT", "AMD"]);
  const [newTickerInput, setNewTickerInput] = useState<string>('');
  
  const [activeTicker, setActiveTicker] = useState<string>('TSLA');
  const [activeInterval, setActiveInterval] = useState<string>('1d');
  const [strategyParams, setStrategyParams] = useState<StrategyParams>(DEFAULT_STRATEGY_PARAMS);
  const [activeTab, setActiveTab] = useState<ActiveTab>('report');
  
  const [loading, setLoading] = useState<boolean>(true);
  const [data, setData] = useState<BacktestResponse | null>(null);
  const [sidebarPrices, setSidebarPrices] = useState<Record<string, number>>({});
  
  // 公司元数据状态
  const [companyInfo, setCompanyInfo] = useState<CompanyInfo | null>(null);
  const [infoLoading, setInfoLoading] = useState<boolean>(false);

  // AI 智能托管托管状态
  const [aiAutoPilot, setAiAutoPilot] = useState<boolean>(true);
  const [tuningLoading, setTuningLoading] = useState<boolean>(false);
  const [tuningReport, setTuningReport] = useState<string | null>(null);
  const [tuningMetrics, setTuningMetrics] = useState<any>(null);

  // Intraday Zoom Panel states
  const [zoomTradeItem, setZoomTradeItem] = useState<LedgerItem | null>(null);
  const [zoomCandles, setZoomCandles] = useState<any[]>([]);
  const [zoomLoading, setZoomLoading] = useState<boolean>(false);
  const [focusTime, setFocusTime] = useState<number | undefined>(undefined);

  // Replay Simulator states
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [replayDate, setReplayDate] = useState<string>('');
  const [replayLoading, setReplayLoading] = useState<boolean>(false);
  const [replayData, setReplayData] = useState<any>(null);
  const [replayIndex, setReplayIndex] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [replaySpeed, setReplaySpeed] = useState<number>(300);

  // Workflow Guide visibility
  const [showGuide, setShowGuide] = useState<boolean>(true);

  // AI 智能调参逻辑
  useEffect(() => {
    if (!aiAutoPilot) {
      setTuningReport(null);
      setTuningMetrics(null);
      return;
    }

    const runAiTuning = async () => {
      setTuningLoading(true);
      try {
        const response = await fetch('http://127.0.0.1:8000/api/ai_tune', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ticker: activeTicker.toUpperCase(),
            interval: activeInterval,
            period: activeInterval === '1m' ? '5d' : '1mo'
          })
        });
        const json = await response.json();
        if (json.success) {
          // 应用 AI 调参最优值
          setStrategyParams(prev => ({
            ...prev,
            ...json.best_params
          }));
          setTuningReport(json.reasoning);
          setTuningMetrics(json.metrics);
        }
      } catch (e) {
        console.error("AI dynamic tuning call failed:", e);
      } finally {
        setTuningLoading(false);
      }
    };

    runAiTuning();
  }, [aiAutoPilot, activeTicker, activeInterval]);

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
          slippage_rate: String(strategyParams.slippage_rate),
          market_open_focus: String(strategyParams.market_open_focus)
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
          console.error("Backtest failed:", json.error);
        }
      } catch (e) {
        console.error("API connection failed:", e);
      } finally {
        setLoading(false);
      }
    };

    // 如果 AI 调参中，等待调参完成再拉取数据以防止触发多次不一致的请求
    if (!tuningLoading) {
      fetchBacktestData();
    }
  }, [activeTicker, activeInterval, strategyParams, tuningLoading]);

  // 2. 获取公司详情介绍
  useEffect(() => {
    const fetchCompanyDetails = async () => {
      setInfoLoading(true);
      try {
        const res = await fetch(`http://127.0.0.1:8000/api/company_info?ticker=${activeTicker}`);
        const json = await res.json();
        setCompanyInfo(json);
      } catch (e) {
        console.error("Company info fetch failed:", e);
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

  // Handle AI agent backtest request
  const handleAgentBacktest = (config: Record<string, unknown>) => {
    const newParams: StrategyParams = {
      ...DEFAULT_STRATEGY_PARAMS,
      ...config as Partial<StrategyParams>
    };
    const ticker = (config.ticker as string) || activeTicker;
    const interval = (config.interval as string) || activeInterval;
    
    setActiveTicker(ticker.toUpperCase());
    setActiveInterval(interval);
    setStrategyParams(newParams);
  };

  // available dates fetch side-effect
  useEffect(() => {
    if (activeTab === 'replay') {
      const fetchDates = async () => {
        try {
          const res = await fetch(`http://127.0.0.1:8000/api/replay/available_dates?ticker=${activeTicker}`);
          const json = await res.json();
          if (json.success && json.dates.length > 0) {
            setAvailableDates(json.dates);
            setReplayDate(json.dates[0]); // default to latest day
          }
        } catch (e) {
          console.error("Failed to fetch available dates:", e);
        }
      };
      fetchDates();
    }
  }, [activeTab, activeTicker]);

  // load replay data
  const handleLoadReplay = async () => {
    if (!replayDate) return;
    setReplayLoading(true);
    setIsPlaying(false);
    setReplayIndex(0);
    setReplayData(null);
    try {
      const params = new URLSearchParams({
        ticker: activeTicker.toUpperCase(),
        date: replayDate,
        strategy_mode: strategyParams.strategy_mode,
        stop_loss_pct: String(strategyParams.stop_loss_pct),
        profit_target_pct: String(strategyParams.profit_target_pct),
        trailing_stop_mode: strategyParams.trailing_stop_mode,
        trailing_stop_atr_mult: String(strategyParams.trailing_stop_atr_mult),
        rsi_threshold_buy: String(strategyParams.rsi_threshold_buy),
        risk_per_trade_pct: String(strategyParams.risk_per_trade_pct),
        max_position_size_pct: String(strategyParams.max_position_size_pct),
        commission_per_share: String(strategyParams.commission_per_share),
        slippage_rate: String(strategyParams.slippage_rate),
        market_open_focus: String(strategyParams.market_open_focus),
      });
      const res = await fetch(`http://127.0.0.1:8000/api/replay/data?${params.toString()}`);
      const json = await res.json();
      if (json.success) {
        setReplayData(json);
        setReplayIndex(0);
      } else {
        alert("加载复盘数据失败: " + json.error);
      }
    } catch (e) {
      console.error(e);
      alert("网络请求失败");
    } finally {
      setReplayLoading(false);
    }
  };

  const playbackTimerRef = useRef<any>(null);

  // Playback timer loop
  useEffect(() => {
    if (isPlaying && replayData && replayIndex < replayData.candles.length - 1) {
      playbackTimerRef.current = setInterval(() => {
        setReplayIndex((prev) => {
          if (prev >= replayData.candles.length - 1) {
            setIsPlaying(false);
            clearInterval(playbackTimerRef.current);
            return prev;
          }
          return prev + 1;
        });
      }, replaySpeed);
    } else {
      if (playbackTimerRef.current) {
        clearInterval(playbackTimerRef.current);
      }
    }

    return () => {
      if (playbackTimerRef.current) {
        clearInterval(playbackTimerRef.current);
      }
    };
  }, [isPlaying, replayData, replayIndex, replaySpeed]);

  // Ledger row click handler
  const handleLedgerRowClick = async (item: LedgerItem) => {
    if (activeInterval === '1d') {
      setZoomLoading(true);
      setZoomTradeItem(item);
      setZoomCandles([]);
      try {
        const dateStr = item.timestamp.split(' ')[0]; // YYYY-MM-DD
        const res = await fetch(`http://127.0.0.1:8000/api/intraday_data?ticker=${item.ticker}&date=${dateStr}`);
        const json = await res.json();
        if (json.success) {
          setZoomCandles(json.candles);
        } else {
          alert("加载日内数据失败: " + json.error);
        }
      } catch (e) {
        console.error(e);
      } finally {
        setZoomLoading(false);
      }
    } else {
      const t = Math.floor(new Date(item.timestamp).getTime() / 1000);
      setFocusTime(t);
      const chartEl = document.getElementById('main-chart-card');
      chartEl?.scrollIntoView({ behavior: 'smooth' });
    }
  };

  // Replay live state calculations
  const slicedCandles = replayData ? replayData.candles.slice(0, replayIndex + 1) : [];
  const currentTimestamp = slicedCandles.length > 0 ? slicedCandles[slicedCandles.length - 1].time : 0;
  
  const slicedLedger = replayData 
    ? replayData.ledger.filter((item: any) => {
        const t = Math.floor(new Date(item.timestamp).getTime() / 1000);
        return t <= currentTimestamp;
      })
    : [];

  const slicedMarkers = replayData 
    ? replayData.markers.filter((m: any) => m.time <= currentTimestamp)
    : [];

  const getLiveReplayStats = () => {
    if (!replayData || slicedCandles.length === 0) return { cash: 100000, shares: 0, positionValue: 0, equity: 100000, pnl: 0, pnlPct: 0 };
    
    let cash = 100000;
    let shares = 0;
    
    for (const item of slicedLedger) {
      cash = item.cash_remaining;
      if (item.action === 'BUY') {
        shares += item.shares;
      } else {
        shares -= item.shares;
      }
    }
    
    const lastCandle = slicedCandles[slicedCandles.length - 1];
    const currentPrice = lastCandle.close;
    const positionValue = shares * currentPrice;
    const equity = cash + positionValue;
    const netPnL = equity - 100000;
    const pnlPct = (netPnL / 100000) * 100;
    
    return {
      cash,
      shares,
      positionValue,
      equity,
      pnl: netPnL,
      pnlPct,
      currentPrice
    };
  };

  const liveStats = getLiveReplayStats();

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
    e.stopPropagation();
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
          Quant<span>.ai</span>
        </div>
        
        {/* Tab Navigation */}
        <div className="nav-tabs">
          <button
            className={`nav-tab ${activeTab === 'report' ? 'active' : ''}`}
            onClick={() => setActiveTab('report')}
          >
            📖 Deep Research
          </button>
          <button
            className={`nav-tab ${activeTab === 'research' ? 'active' : ''}`}
            onClick={() => setActiveTab('research')}
          >
            🤖 AI Research
          </button>
          <button
            className={`nav-tab ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setActiveTab('dashboard')}
          >
            📊 Dashboard
          </button>
          <button
            className={`nav-tab ${activeTab === 'replay' ? 'active' : ''}`}
            onClick={() => setActiveTab('replay')}
          >
            🎬 Replay Simulator
          </button>
          <button
            className={`nav-tab ${activeTab === 'walkforward' ? 'active' : ''}`}
            onClick={() => setActiveTab('walkforward')}
          >
            🔄 Walk-Forward
          </button>
          <button
            className={`nav-tab ${activeTab === 'experiments' ? 'active' : ''}`}
            onClick={() => setActiveTab('experiments')}
          >
            🧪 Experiments
          </button>
        </div>

        <div style={{ color: 'var(--color-text-secondary)', fontSize: '0.85rem', fontWeight: 600 }}>
          AI Quant Research Agent Platform
        </div>
      </header>

      {/* 主布局网格 */}
      <div className="app-container">
        {/* 左侧内容区 */}
        <main className="main-content">
          {/* Collapsible Workflow Guide */}
          {showGuide && (activeTab === 'dashboard' || activeTab === 'replay') && (
            <div className="card fade-in" style={{ marginBottom: '1.5rem', background: 'rgba(0, 200, 5, 0.04)', border: '1px solid rgba(0, 200, 5, 0.2)', position: 'relative' }}>
              <button 
                onClick={() => setShowGuide(false)} 
                style={{ position: 'absolute', top: '12px', right: '16px', background: 'transparent', border: 'none', color: 'var(--color-text-secondary)', cursor: 'pointer', fontSize: '0.85rem' }}
              >
                ✕ 隐藏指南
              </button>
              <h3 style={{ margin: '0 0 8px 0', fontSize: '1rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '6px' }}>
                💡 Quant.ai 智能量化交易终端使用指南
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', fontSize: '0.8rem', color: '#e5e5e7', lineHeight: 1.4 }}>
                <div>
                  <strong style={{ color: 'var(--color-green)' }}>第一步：寻找高波动标的 🔍</strong>
                  <p style={{ margin: '4px 0 0 0' }}>
                    使用右下角的 <strong>选股扫描面板</strong> 进行盘前扫描，筛选出具备 RVol (相对成交量) 与 ATR 振幅支撑的股票，它们是日内开盘突击的最优交易候选。
                  </p>
                </div>
                <div>
                  <strong style={{ color: 'var(--color-green)' }}>第二步：设计策略与AI调参 🤖</strong>
                  <p style={{ margin: '4px 0 0 0' }}>
                    在 <strong>Dashboard</strong> 中，您可以启用 <strong>AI Auto-Pilot 智能托管</strong>。系统会自动拉取最近 5 天的数据进行快速寻优，制定出抗回撤、收益稳健的量化配置。
                  </p>
                </div>
                <div>
                  <strong style={{ color: 'var(--color-green)' }}>第三步：历史沙盒复盘 🎬</strong>
                  <p style={{ margin: '4px 0 0 0' }}>
                    切换到 <strong>Replay Simulator</strong>。选择任意历史日期，点【加载复盘沙盒】，再点击播放即可仿真复盘该天系统买卖的全流程。
                  </p>
                </div>
                <div>
                  <strong style={{ color: 'var(--color-green)' }}>第四步：成交检查与透视 🔎</strong>
                  <p style={{ margin: '4px 0 0 0' }}>
                    在交易流水中，<strong>点击任意一行交易记录</strong>：如果是日线交易，下方会弹出 <strong>1分钟日内微观透视</strong> 详细图表，显示具体开盘成交时刻，让您精准审计。
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Deep Research Tab */}
          {activeTab === 'report' && (
            <ResearchReportPanel 
              onApplyParams={(config, tab) => {
                setStrategyParams(prev => ({ ...prev, ...config }));
                setActiveTab(tab);
              }}
              activeTicker={activeTicker}
            />
          )}

          {/* AI Research Tab */}
          {activeTab === 'research' && (
            <ChatPanel 
              onRunBacktest={handleAgentBacktest}
              isLoading={loading}
              activeTicker={activeTicker}
            />
          )}

          {/* Walk-Forward Tab */}
          {activeTab === 'walkforward' && (
            <WalkForwardPanel activeTicker={activeTicker} />
          )}

          {/* Experiments Tab */}
          {activeTab === 'experiments' && (
            <ExperimentCompare />
          )}

          {/* Replay Simulator Tab */}
          {activeTab === 'replay' && (
            <div className="fade-in">
              <div className="card" style={{ marginBottom: '1.5rem', background: '#09090b', border: '1px solid var(--color-border)' }}>
                <h2 style={{ fontSize: '1.1rem', fontWeight: 800, margin: '0 0 1rem 0', color: '#fff' }}>
                  🎬 Quant.ai 开盘历史交易复盘模拟器
                </h2>
                
                {/* 选项栏 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <label style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', fontWeight: 700 }}>复盘日期 (Past Date)</label>
                    <select 
                      value={replayDate} 
                      onChange={(e) => setReplayDate(e.target.value)}
                      style={{ background: '#111', border: '1px solid #333', color: '#fff', padding: '6px 12px', borderRadius: '6px', fontSize: '0.82rem', minWidth: '150px' }}
                    >
                      {availableDates.map(d => (
                        <option key={d} value={d}>{d}</option>
                      ))}
                    </select>
                  </div>

                  <button 
                    onClick={handleLoadReplay}
                    disabled={replayLoading || !replayDate}
                    className="btn btn-primary"
                    style={{ marginTop: '1.1rem', padding: '8px 16px', fontSize: '0.8rem', cursor: 'pointer' }}
                  >
                    {replayLoading ? '⏳ 加载中...' : '🔌 加载复盘沙盒'}
                  </button>

                  {replayData && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '1.1rem', background: '#141416', padding: '4px 12px', borderRadius: '8px', border: '1px solid #222' }}>
                      <button 
                        onClick={() => setIsPlaying(!isPlaying)}
                        style={{ background: 'transparent', border: 'none', color: 'var(--color-green)', fontSize: '1.1rem', cursor: 'pointer', display: 'flex', alignItems: 'center', padding: '4px' }}
                        title={isPlaying ? '暂停' : '播放'}
                      >
                        {isPlaying ? '⏸️ 暂停' : '▶️ 播放'}
                      </button>
                      
                      <button 
                        onClick={() => {
                          setReplayIndex(prev => Math.min(replayData.candles.length - 1, prev + 1));
                          setIsPlaying(false);
                        }}
                        style={{ background: 'transparent', border: 'none', color: '#fff', fontSize: '1.1rem', cursor: 'pointer', display: 'flex', alignItems: 'center', padding: '4px' }}
                        title="单步步进"
                      >
                        ➡️ 单步
                      </button>

                      <button 
                        onClick={() => {
                          setReplayIndex(0);
                          setIsPlaying(false);
                        }}
                        style={{ background: 'transparent', border: 'none', color: 'var(--color-red)', fontSize: '1.1rem', cursor: 'pointer', display: 'flex', alignItems: 'center', padding: '4px' }}
                        title="重置"
                      >
                        ⏹️ 重置
                      </button>

                      {/* 播放速度 */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', color: 'var(--color-text-secondary)', marginLeft: '12px' }}>
                        <span>回放间隔:</span>
                        <input 
                          type="range" 
                          min="50" 
                          max="1000" 
                          step="50" 
                          value={1050 - replaySpeed} 
                          onChange={(e) => setReplaySpeed(1050 - Number(e.target.value))}
                          style={{ width: '80px', accentColor: 'var(--color-green)' }}
                        />
                        <span>{(1000 / replaySpeed).toFixed(1)}x</span>
                      </div>
                    </div>
                  )}
                </div>

                <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--color-text-secondary)', lineHeight: 1.4 }}>
                  💡 <strong>复盘模式说明</strong>：系统会拉取该股当天 1分钟 级别完整的价格数据，以所选的策略参数在沙盒中从 09:30 开始分时播放。
                  您可以手动调节播放速度，观察系统的实时开盘决策并校对买卖点。
                </p>
              </div>

              {replayData ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                  {/* 复盘图表 */}
                  <div className="card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                      <h3 className="card-title" style={{ margin: 0 }}>📈 1分钟 分时复盘曲线 (Sandbox Time-series Chart)</h3>
                      <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>
                        进度: <strong>{slicedCandles.length} / {replayData.candles.length}</strong> 根 K线 | 
                        当前时间: <strong style={{ color: '#fff' }}>
                          {slicedCandles.length > 0 
                            ? new Date(slicedCandles[slicedCandles.length - 1].time * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) 
                            : '09:30'}
                        </strong>
                      </span>
                    </div>
                    <StockChart candles={slicedCandles} markers={slicedMarkers} />
                  </div>

                  {/* 实时账户与交易流水 */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: '1.5rem' }}>
                    {/* Live Account Stats */}
                    <div className="card">
                      <h3 className="card-title">💵 模拟账户动态表现 (Live Portfolio)</h3>
                      <div className="stats-grid" style={{ gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '10px' }}>
                        <div className="stat-card" style={{ background: '#111', padding: '12px' }}>
                          <span className="stat-label">总资产权益 (Equity)</span>
                          <span className="stat-value" style={{ fontSize: '1.2rem' }}>${liveStats.equity.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                        </div>
                        <div className="stat-card" style={{ background: '#111', padding: '12px' }}>
                          <span className="stat-label">账户现金 (Cash)</span>
                          <span className="stat-value" style={{ fontSize: '1.2rem' }}>${liveStats.cash.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                        </div>
                        <div className="stat-card" style={{ background: '#111', padding: '12px' }}>
                          <span className="stat-label">持仓市值 (Holdings)</span>
                          <span className="stat-value" style={{ fontSize: '1.2rem' }}>${liveStats.positionValue.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                        </div>
                        <div className="stat-card" style={{ background: '#111', padding: '12px' }}>
                          <span className="stat-label">持股数量 (Shares)</span>
                          <span className="stat-value" style={{ fontSize: '1.2rem', color: liveStats.shares > 0 ? 'var(--color-green)' : '#fff' }}>{liveStats.shares} 股</span>
                        </div>
                        <div className="stat-card" style={{ background: '#111', padding: '12px', gridColumn: 'span 2' }}>
                          <span className="stat-label">净收益 (PnL / %)</span>
                          <span className="stat-value" style={{ fontSize: '1.25rem', color: liveStats.pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
                            {liveStats.pnl >= 0 ? '+' : ''}${liveStats.pnl.toFixed(2)} ({liveStats.pnl >= 0 ? '+' : ''}{liveStats.pnlPct.toFixed(2)}%)
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Ledger List */}
                    <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
                      <h3 className="card-title" style={{ margin: '0 0 10px 0' }}>📜 日内动态交易账本 (Live Ledger)</h3>
                      <div style={{ flex: 1, maxHeight: '230px', overflowY: 'auto' }}>
                        {slicedLedger.length === 0 ? (
                          <p style={{ color: 'var(--color-text-secondary)', margin: '20px 0', textAlign: 'center', fontSize: '0.85rem' }}>
                            等待策略触发开盘信号...
                          </p>
                        ) : (
                          <table className="ledger-table" style={{ fontSize: '0.8rem' }}>
                            <thead>
                              <tr>
                                <th>时间</th>
                                <th>动作</th>
                                <th>股数</th>
                                <th>成交价</th>
                                <th style={{ textAlign: 'right' }}>实现PnL</th>
                              </tr>
                            </thead>
                            <tbody>
                              {[...slicedLedger].reverse().map((item: any, idx: number) => {
                                const pnl = item.realized_pnl;
                                const isBuy = item.action === 'BUY';
                                const hasPnl = pnl !== undefined && !isBuy;
                                const pnlColor = hasPnl ? (pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)') : 'inherit';
                                return (
                                  <tr key={idx}>
                                    <td>{item.timestamp.split(' ')[1]}</td>
                                    <td>
                                      <span className={`action-badge ${item.action.toLowerCase()}`} style={{ fontSize: '0.65rem', padding: '2px 4px' }}>
                                        {item.action === 'BUY' ? 'BUY' : 'SELL'}
                                      </span>
                                    </td>
                                    <td>{item.shares}</td>
                                    <td>${item.execution_price.toFixed(2)}</td>
                                    <td style={{ textAlign: 'right', fontWeight: 700, color: pnlColor }}>
                                      {hasPnl ? `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}` : '--'}
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="card loader-container" style={{ padding: '3rem', textAlign: 'center', color: 'var(--color-text-secondary)' }}>
                  请选择复盘日期并点击【加载复盘沙盒】开始仿真！
                </div>
              )}
            </div>
          )}

          {(activeTab === 'dashboard' || activeTab === 'research') && (
            loading ? (
              <div className="loader-container">
                Simulating {activeTicker} ({INTERVAL_LABELS[activeInterval] || activeInterval}) backtest...
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
                      {pnlSign}${data.summary.net_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({pnlSign}{data.summary.pnl_pct.toFixed(2)}%)
                    </div>
                  </div>
                  
                  {/* 周期切换器 */}
                  <div className="interval-picker-container">
                    <div className="time-tabs" style={{ marginTop: 0 }}>
                      {Object.entries(INTERVAL_LABELS).map(([key]) => (
                        <button
                          key={key}
                          className={`tab-btn ${activeInterval === key ? 'active' : ''}`}
                          onClick={() => handleIntervalChange(key)}
                        >
                          {key.toUpperCase()}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {/* 核心 K 线图表 */}
                <div id="main-chart-card" className="chart-wrapper">
                  <StockChart candles={data.candles} markers={data.markers} focusTime={focusTime} />
                </div>

                {/* Equity & Drawdown Curves */}
                <EquityCurve 
                  equityCurve={data.equity_curve} 
                  drawdownCurve={data.drawdown_curve || []} 
                />

                {/* Regime Breakdown */}
                <RegimeBreakdown 
                  breakdown={data.regime_breakdown || []} 
                  distribution={data.regime_distribution || {}} 
                />

                {/* AI 托管微调状态报告 */}
                {activeTab === 'dashboard' && tuningLoading && (
                  <div className="card" style={{
                    background: 'linear-gradient(135deg, #1c1c1e, #141416)',
                    border: '1px dashed rgba(0, 200, 5, 0.4)',
                    borderRadius: '10px',
                    padding: '20px',
                    marginBottom: '1.5rem',
                    textAlign: 'center',
                    boxShadow: '0 8px 32px rgba(0,0,0,0.3)'
                  }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                      <div className="spinner" style={{
                        width: '32px',
                        height: '32px',
                        borderRadius: '50%',
                        border: '3px solid rgba(0,200,5,0.1)',
                        borderTop: '3px solid var(--color-green)',
                        animation: 'spin 1s linear infinite'
                      }}></div>
                      <h4 style={{ margin: 0, fontWeight: 700, color: '#ffffff', fontSize: '0.95rem' }}>AI 托管机器学习模型正在自动优化最佳参数...</h4>
                      <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.8rem', margin: 0 }}>正在对 {activeTicker} 近期 5 天的高频 1m 波动率和突破阻力位进行量化网格搜索。</p>
                    </div>
                  </div>
                )}

                {activeTab === 'dashboard' && aiAutoPilot && tuningReport && !tuningLoading && (
                  <div className="card" style={{
                    background: 'linear-gradient(135deg, #1c1c1e, #121214)',
                    border: '1px solid rgba(0, 200, 5, 0.25)',
                    borderRadius: '10px',
                    padding: '1.25rem',
                    marginBottom: '1.5rem',
                    boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
                    animation: 'fadeIn 0.5s ease-in-out'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '0.75rem', borderBottom: '1px solid var(--color-border)', paddingBottom: '0.5rem' }}>
                      <span style={{ fontSize: '1.3rem' }}>🛡️</span>
                      <h4 style={{ margin: 0, fontWeight: 800, fontSize: '0.95rem', color: '#ffffff' }}>AI 智能托管报告 (AI Auto-Pilot Tuning Report)</h4>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                      <p style={{ color: '#e5e5ea', fontSize: '0.82rem', margin: 0, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                        {tuningReport}
                      </p>
                      
                      {tuningMetrics && (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', background: '#141416', padding: '10px 16px', borderRadius: '8px', border: '1px solid var(--color-border)' }}>
                          <div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--color-text-secondary)', marginBottom: '2px' }}>回测总盈亏</div>
                            <div style={{ fontSize: '0.95rem', fontWeight: 800, color: tuningMetrics.net_pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
                              ${tuningMetrics.net_pnl.toFixed(2)}
                            </div>
                          </div>
                          <div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--color-text-secondary)', marginBottom: '2px' }}>测算胜率</div>
                            <div style={{ fontSize: '0.95rem', fontWeight: 800, color: 'var(--color-green)' }}>
                              {tuningMetrics.win_rate.toFixed(1)}%
                            </div>
                          </div>
                          <div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--color-text-secondary)', marginBottom: '2px' }}>最大回撤</div>
                            <div style={{ fontSize: '0.95rem', fontWeight: 800, color: 'var(--color-red)' }}>
                              {(tuningMetrics.max_drawdown * 100).toFixed(2)}%
                            </div>
                          </div>
                          <div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--color-text-secondary)', marginBottom: '2px' }}>测算交易数</div>
                            <div style={{ fontSize: '0.95rem', fontWeight: 800, color: '#ffffff' }}>
                              {tuningMetrics.round_trips} 笔
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* 策略设置与形态识别日志 并排展示 */}
                {activeTab === 'dashboard' && (
                  <>
                    <div className="strategy-patterns-grid">
                      <StrategySettings 
                        params={strategyParams} 
                        onChange={setStrategyParams} 
                        onReset={resetStrategyParams}
                        aiAutoPilot={aiAutoPilot}
                        onToggleAutoPilot={setAiAutoPilot}
                      />
                      <PatternLog patterns={data.patterns_log} />
                    </div>

                    {/* 选股扫描面板 */}
                    <ScannerPanel customTickers={watchlist} onSelectTicker={setActiveTicker} />
                  </>
                )}

                {/* 账户业绩统计 */}
                <PortfolioStats summary={data.summary} />

                {/* 交易明细账本 */}
                <LedgerTable ledger={data.ledger} onRowClick={handleLedgerRowClick} />

                {/* 日内 1分钟 交易微观透视 */}
                {zoomLoading && (
                  <div className="card loader-container" style={{ marginTop: '1.5rem', padding: '2rem', textAlign: 'center' }}>
                    <div className="spinner" style={{
                      width: '24px',
                      height: '24px',
                      borderRadius: '50%',
                      border: '2px solid rgba(0,200,5,0.1)',
                      borderTop: '2px solid var(--color-green)',
                      animation: 'spin 1s linear infinite',
                      margin: '0 auto 10px auto'
                    }}></div>
                    <span style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
                      正在拉取 {zoomTradeItem?.ticker} 日内高频分时数据并进行 1分钟 细节对齐...
                    </span>
                  </div>
                )}
                {!zoomLoading && zoomTradeItem && zoomCandles.length > 0 && (
                  <IntradayZoomChart 
                    candles={zoomCandles} 
                    tradeItem={zoomTradeItem} 
                    onClose={() => {
                      setZoomTradeItem(null);
                      setZoomCandles([]);
                    }} 
                  />
                )}
              </>
            ) : (
              <div className="loader-container">
                Cannot connect to backend. Please ensure FastAPI is running on http://127.0.0.1:8000
              </div>
            )
          )}
        </main>

        {/* 右侧边栏自选股列表 & 公司档案 */}
        <aside className="sidebar">
          <h4 className="sidebar-title">Watchlist</h4>
          
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
              placeholder="Add ticker, e.g. GOOGL" 
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
              Add
            </button>
          </form>

          {/* 选中的公司基本介绍档案 */}
          <div style={{ marginTop: '1rem' }}>
            <CompanyInfoCard ticker={activeTicker} info={companyInfo} loading={infoLoading} />
          </div>
          
          <div style={{ marginTop: 'auto', padding: '1rem', background: '#1c1c1e', border: '1px solid var(--color-border)', borderRadius: '8px', fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>
            <strong style={{ color: '#ffffff', display: 'block', marginBottom: '4px' }}>About Quant.ai</strong>
            AI-powered quantitative research platform. Define strategies via natural language, run backtests with realistic cost modeling, and receive AI-generated risk analysis reports.
            <br /><br />
            <em style={{ fontSize: '0.75rem' }}>For educational and research purposes only. Not investment advice.</em>
          </div>
        </aside>
      </div>
    </div>
  );
}

export default App;
