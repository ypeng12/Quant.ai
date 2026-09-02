import React, { useState, useEffect } from 'react';
import { API_BASE } from '../config';
import { MLDynamicVisualizationDashboard } from './MLDynamicVisualizationDashboard';
import { MLVisualInteractiveLab } from './MLVisualInteractiveLab';

export const InstitutionalPanel: React.FC = () => {
  const [activeSubTab, setActiveSubTab] = useState<'mlVisualLab' | 'twoStage' | 'alphaLab' | 'optimal' | 'statArb' | 'riskParity' | 'dsr' | 'lowLatency' | 'ofi' | 'multiAsset'>('mlVisualLab');
  const [loading, setLoading] = useState<boolean>(false);
  const [resultData, setResultData] = useState<any>(null);
  const [alphaResearchData, setAlphaResearchData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch precomputed Alpha Research Lab results on mount
  useEffect(() => {
    fetchLatestAlphaResearch();
  }, []);

  const fetchLatestAlphaResearch = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/research/latest_results`);
      const data = await res.json();
      if (data.success) {
        setAlphaResearchData(data);
      } else {
        setError(data.error || 'Failed to fetch research results');
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const triggerRunAlphaExperiment = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/research/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lookback_days: 20, holding_days: 5, cost_bps: 5.0, use_synthetic: true })
      });
      const data = await res.json();
      if (data.success) {
        fetchLatestAlphaResearch();
      } else {
        setError(data.error || 'Failed to trigger alpha experiment');
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // OFI Trigger
  const runOFI = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/orderbook/ofi`, { method: 'POST' });
      const data = await res.json();
      if (data.success) setResultData(data.result);
      else setError(data.error || 'Failed to compute OFI');
    } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  };

  // Multi-Asset Backtest Trigger
  const runMultiAsset = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/portfolio/backtest-multi`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers: ['AAPL', 'MSFT', 'TSLA', 'NVDA', 'AMZN', 'GOOGL', 'META'], period: '1y', top_n: 3 })
      });
      const data = await res.json();
      if (data.success) setResultData(data.result);
      else setError(data.error || 'Failed to run multi-asset backtest');
    } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  };

  // 1. Almgren-Chriss Optimal Execution Demo Trigger
  const runOptimalExecution = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/optimal-execution/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          total_shares: 100000,
          num_intervals: 10,
          daily_volatility: 0.02,
          avg_daily_volume: 5000000.0,
          risk_aversion_lambda: 0.00001,
          current_price: 150.0
        })
      });
      const data = await res.json();
      if (data.success) setResultData(data);
      else setError(data.error || 'Failed to simulate optimal execution');
    } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  };

  // 2. StatArb Pairs Trading Trigger
  const runStatArb = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/stat-arb/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker_y: 'KO', ticker_x: 'PEP', period: '1y', z_entry: 2.0, z_exit: 0.5 })
      });
      const data = await res.json();
      if (data.success) setResultData(data.result);
      else setError(data.error || 'Failed to run stat arb');
    } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  };

  // 3. Risk Parity Allocation Trigger
  const runRiskParity = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/portfolio/risk-parity`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers: ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TLT', 'GLD'], period: '1y' })
      });
      const data = await res.json();
      if (data.success) setResultData(data.result);
      else setError(data.error || 'Failed to compute Risk Parity');
    } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  };

  // 4. Deflated Sharpe Ratio Trigger
  const runDSR = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/metrics/dsr`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker: 'TSLA', period: '1y', num_trials: 50 })
      });
      const data = await res.json();
      if (data.success) setResultData(data.result);
      else setError(data.error || 'Failed to calculate DSR');
    } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  };

  // 5. Zero-Allocation Memory Profiling Trigger
  const runLowLatencyBench = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/low-latency/benchmark`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ num_events: 500000 })
      });
      const data = await res.json();
      if (data.success) setResultData(data.result);
      else setError(data.error || 'Failed to run low latency benchmark');
    } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-2xl text-slate-100 mt-6">
      <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-6">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <span>🏛️</span> Institutional Quantitative Architecture Terminal
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            专业量化研究与策略验证终端 (Institutional Quantitative Research Terminal)
          </p>
        </div>
        <span className="px-3 py-1 rounded-full text-xs font-mono bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
          PRO QUANT ENGINE ACTIVE
        </span>
      </div>

      {/* Sub-tab Selectors */}
      <div className="flex gap-2 border-b border-slate-800 pb-3 mb-6 overflow-x-auto">
        <button
          onClick={() => { setActiveSubTab('mlVisualLab'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'mlVisualLab'
              ? 'bg-sky-600 text-white shadow-lg shadow-sky-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          🧠 机器学习全景几何实验室 (ML Visual Lab)
        </button>

        <button
          onClick={() => { setActiveSubTab('twoStage'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'twoStage'
              ? 'bg-purple-600 text-white shadow-lg shadow-purple-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          🏛️ Quant.ai 两级自适应 ML 动态诊断 Tab
        </button>

        <button
          onClick={() => { setActiveSubTab('alphaLab'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'alphaLab'
              ? 'bg-amber-600 text-white shadow-lg shadow-amber-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          🔬 样本外 Alpha 验证 (Out-of-Sample Alpha Lab)
        </button>

        <button
          onClick={() => { setActiveSubTab('optimal'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'optimal'
              ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          📈 最优算法执行 (Almgren-Chriss Model)
        </button>

        <button
          onClick={() => { setActiveSubTab('statArb'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'statArb'
              ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          ⚖️ 协整与统计套利 (StatArb OU)
        </button>

        <button
          onClick={() => { setActiveSubTab('riskParity'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'riskParity'
              ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          🛡️ 风险平价组合 (Risk Parity ERC)
        </button>

        <button
          onClick={() => { setActiveSubTab('dsr'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'dsr'
              ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          🔬 夏普比率过拟合审计 (Deflated Sharpe Ratio)
        </button>

        <button
          onClick={() => { setActiveSubTab('lowLatency'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'lowLatency'
              ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          ⚡ C++ 内存性能分析 (Memory Profiler)
        </button>

        <button
          onClick={() => { setActiveSubTab('ofi'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'ofi'
              ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          📊 订单流不平衡度 (Order Flow Imbalance)
        </button>

        <button
          onClick={() => { setActiveSubTab('multiAsset'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'multiAsset'
              ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          🌐 多资产组合回测 (Multi-Asset Universe)
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-xs font-mono">
          ⚠️ {error}
        </div>
      )}

      {/* SubTab Content */}
      {activeSubTab === 'mlVisualLab' && (
        <div className="mb-6">
          <MLVisualInteractiveLab />
        </div>
      )}

      {activeSubTab === 'twoStage' && (
        <div className="mb-6">
          <MLDynamicVisualizationDashboard />
        </div>
      )}

      {activeSubTab === 'alphaLab' && (
        <div className="space-y-6">
          <div className="bg-slate-950/60 border border-amber-500/20 rounded-xl p-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-amber-300">
                  点位时间一致性与 Purged Walk-Forward Alpha 验证
                </h3>
                <p className="text-xs text-slate-400 mt-1">
                  Point-in-time universe across 38 liquid ETFs (94,040 rows OHLCV). Zero future leakage, 5d embargo, 5 bps friction.
                </p>
              </div>
              <button
                onClick={triggerRunAlphaExperiment}
                disabled={loading}
                className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-xs font-bold transition-all shadow-lg shadow-amber-600/20 disabled:opacity-50"
              >
                {loading ? 'Running Experiment...' : '⚡ Re-Run Out-of-Sample CV'}
              </button>
            </div>

            {alphaResearchData && (
              <div className="mt-5 space-y-5">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 font-mono text-xs">
                  <div className="bg-slate-900/80 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">HISTORICAL SPAN</span>
                    <span className="text-white font-bold">{alphaResearchData.trading_dates} Trading Days</span>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">UNIVERSE SIZE</span>
                    <span className="text-white font-bold">{alphaResearchData.universe_size} Liquid ETFs</span>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">VALIDATION SCHEME</span>
                    <span className="text-amber-400 font-bold">Purged Walk-Forward (5d Embargo)</span>
                  </div>
                  <div className="bg-slate-900/80 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">TRANSACTION FRICTION</span>
                    <span className="text-emerald-400 font-bold">{alphaResearchData.cost_bps} bps</span>
                  </div>
                </div>

                {/* Model Suite Comparison Table */}
                <div>
                  <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-2">
                    Model Hierarchy Out-of-Sample Performance Table
                  </h4>
                  <div className="overflow-x-auto border border-slate-800 rounded-lg">
                    <table className="w-full text-left text-xs font-mono">
                      <thead className="bg-slate-900 text-slate-400 uppercase text-[10px]">
                        <tr>
                          <th className="py-2.5 px-3">Model Name</th>
                          <th className="py-2.5 px-3">Rank IC</th>
                          <th className="py-2.5 px-3">Net Sharpe</th>
                          <th className="py-2.5 px-3">Max Drawdown</th>
                          <th className="py-2.5 px-3">Turnover</th>
                          <th className="py-2.5 px-3">Deflated Sharpe (DSR)</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60 bg-slate-950/40">
                        {alphaResearchData.results.map((m: any, idx: number) => (
                          <tr key={idx} className="hover:bg-slate-900/50 transition-colors">
                            <td className="py-2.5 px-3 font-bold text-slate-200">
                              {m.model_name}
                              <span className="block text-[10px] text-slate-500 font-normal">{m.description}</span>
                            </td>
                            <td className={`py-2.5 px-3 ${m.rank_ic >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                              {m.rank_ic.toFixed(4)}
                            </td>
                            <td className={`py-2.5 px-3 font-bold ${m.net_sharpe >= 0.5 ? 'text-emerald-400' : m.net_sharpe >= 0 ? 'text-amber-400' : 'text-rose-400'}`}>
                              {m.net_sharpe.toFixed(2)}
                            </td>
                            <td className="py-2.5 px-3 text-rose-400">
                              {(m.max_drawdown * 100).toFixed(1)}%
                            </td>
                            <td className="py-2.5 px-3 text-slate-300">
                              {(m.turnover * 100).toFixed(1)}%
                            </td>
                            <td className="py-2.5 px-3 text-indigo-300 font-bold">
                              {m.dsr.toFixed(2)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Feature Drift PSI Audit */}
                <div>
                  <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-2">
                    Population Stability Index (PSI) Feature Drift Audit
                  </h4>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-2 font-mono text-xs">
                    {alphaResearchData.drift_audit.map((d: any, idx: number) => (
                      <div key={idx} className="bg-slate-900 p-2.5 rounded-lg border border-slate-800 flex items-center justify-between">
                        <div>
                          <span className="text-[10px] text-slate-400 block">{d.feature}</span>
                          <span className="font-bold text-slate-200">PSI: {d.psi.toFixed(4)}</span>
                        </div>
                        <span className="px-2 py-0.5 rounded text-[9px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                          {d.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Subtab 1: Almgren-Chriss Execution */}
      {activeSubTab === 'optimal' && (
        <div className="space-y-4">
          <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-indigo-300">Almgren-Chriss Optimal Execution Simulator</h3>
                <p className="text-xs text-slate-400 mt-1">
                  Solves for the efficient execution frontier by balancing Permanent & Temporary Market Impact against Volatility Risk ($\lambda$).
                </p>
              </div>
              <button
                onClick={runOptimalExecution}
                disabled={loading}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold transition-all shadow-lg shadow-indigo-600/20 disabled:opacity-50"
              >
                {loading ? 'Simulating...' : 'Run Almgren-Chriss Engine'}
              </button>
            </div>

            {resultData && (
              <div className="mt-5 space-y-4 font-mono text-xs">
                <div className="grid grid-cols-3 gap-3">
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">TOTAL SHARES</span>
                    <span className="text-white font-bold">{resultData.parameters?.total_shares?.toLocaleString()}</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">TOTAL EXPECTED COST</span>
                    <span className="text-amber-400 font-bold">${resultData.total_expected_cost?.toFixed(2)}</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">RISK VARIANCE</span>
                    <span className="text-indigo-400 font-bold">{resultData.total_variance?.toFixed(4)}</span>
                  </div>
                </div>

                <div className="overflow-x-auto border border-slate-800 rounded-lg">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-900 text-slate-400 uppercase text-[10px]">
                      <tr>
                        <th className="py-2 px-3">Interval</th>
                        <th className="py-2 px-3">Trade Shares</th>
                        <th className="py-2 px-3">Remaining Inventory</th>
                        <th className="py-2 px-3">Temp Impact ($)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {resultData.trajectory?.map((row: any) => (
                        <tr key={row.interval}>
                          <td className="py-2 px-3 font-semibold text-indigo-300">T+{row.interval}</td>
                          <td className="py-2 px-3 text-emerald-400 font-bold">{row.trade_shares?.toLocaleString()}</td>
                          <td className="py-2 px-3 text-slate-300">{row.remaining_inventory?.toLocaleString()}</td>
                          <td className="py-2 px-3 text-rose-400">${row.temp_impact?.toFixed(4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Subtab 2: StatArb Pairs */}
      {activeSubTab === 'statArb' && (
        <div className="space-y-4">
          <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-indigo-300">Statistical Arbitrage & Cointegration Engine</h3>
                <p className="text-xs text-slate-400 mt-1">
                  Engle-Granger Cointegration Test + Ornstein-Uhlenbeck (OU) Mean Reversion Half-Life Estimation ($t_{1/2}$).
                </p>
              </div>
              <button
                onClick={runStatArb}
                disabled={loading}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold transition-all shadow-lg shadow-indigo-600/20 disabled:opacity-50"
              >
                {loading ? 'Fitting OU Process...' : 'Run Pair Test (KO / PEP)'}
              </button>
            </div>

            {resultData && (
              <div className="mt-5 space-y-4 font-mono text-xs">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">HEDGE RATIO (BETA)</span>
                    <span className="text-white font-bold">{resultData.hedge_ratio?.toFixed(4)}</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">ADF P-VALUE</span>
                    <span className={`font-bold ${resultData.is_cointegrated ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {resultData.p_value?.toFixed(4)} {resultData.is_cointegrated ? '(COINTEGRATED)' : '(NOT COINT)'}
                    </span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">OU HALF-LIFE (DAYS)</span>
                    <span className="text-amber-400 font-bold">{resultData.half_life_days?.toFixed(2)} Days</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">TOTAL TRADES GENERATED</span>
                    <span className="text-indigo-300 font-bold">{resultData.total_trades}</span>
                  </div>
                </div>

                <div className="p-3 bg-slate-900 rounded-lg border border-slate-800">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-slate-400">Current Spread Z-Score:</span>
                    <span className="text-emerald-400 font-bold">{resultData.current_z_score?.toFixed(2)}</span>
                  </div>
                  <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden flex">
                    <div className="bg-rose-500 h-full" style={{ width: '25%' }} title="-2.0 Entry"></div>
                    <div className="bg-slate-700 h-full" style={{ width: '50%' }}></div>
                    <div className="bg-emerald-500 h-full" style={{ width: '25%' }} title="+2.0 Entry"></div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Subtab 3: Risk Parity */}
      {activeSubTab === 'riskParity' && (
        <div className="space-y-4">
          <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-indigo-300">Risk Parity & ERC Portfolio Optimization</h3>
                <p className="text-xs text-slate-400 mt-1">
                  Equal Risk Contribution (ERC) portfolio weights with Ledoit-Wolf Shrinkage Covariance estimation.
                </p>
              </div>
              <button
                onClick={runRiskParity}
                disabled={loading}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold transition-all shadow-lg shadow-indigo-600/20 disabled:opacity-50"
              >
                {loading ? 'Optimizing ERC...' : 'Run Risk Parity Optimizer'}
              </button>
            </div>

            {resultData && (
              <div className="mt-5 space-y-4 font-mono text-xs">
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">PORTFOLIO ANN RETURN</span>
                    <span className="text-emerald-400 font-bold">{(resultData.annualized_return * 100).toFixed(2)}%</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">PORTFOLIO ANN VOLATILITY</span>
                    <span className="text-indigo-400 font-bold">{(resultData.annualized_volatility * 100).toFixed(2)}%</span>
                  </div>
                </div>

                <div className="overflow-x-auto border border-slate-800 rounded-lg">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-900 text-slate-400 uppercase text-[10px]">
                      <tr>
                        <th className="py-2 px-3">Asset Ticker</th>
                        <th className="py-2 px-3">ERC Weight (%)</th>
                        <th className="py-2 px-3">Risk Contribution (%)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {Object.keys(resultData.weights || {}).map((ticker) => (
                        <tr key={ticker}>
                          <td className="py-2 px-3 font-bold text-white">{ticker}</td>
                          <td className="py-2 px-3 text-emerald-400">{(resultData.weights[ticker] * 100).toFixed(2)}%</td>
                          <td className="py-2 px-3 text-indigo-300">{(resultData.risk_contributions[ticker] * 100).toFixed(2)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Subtab 4: Deflated Sharpe Ratio */}
      {activeSubTab === 'dsr' && (
        <div className="space-y-4">
          <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-indigo-300">Deflated Sharpe Ratio (DSR) 夏普比率衰减与过拟合审计</h3>
                <p className="text-xs text-slate-400 mt-1">
                  Adjusts observed Sharpe Ratio for non-normal returns, skewness, kurtosis, and multiple testing trial count ($N$).
                </p>
              </div>
              <button
                onClick={runDSR}
                disabled={loading}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold transition-all shadow-lg shadow-indigo-600/20 disabled:opacity-50"
              >
                {loading ? 'Auditing DSR...' : 'Audit DSR (50 Trials)'}
              </button>
            </div>

            {resultData && (
              <div className="mt-5 space-y-4 font-mono text-xs">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">OBSERVED SHARPE</span>
                    <span className="text-white font-bold">{resultData.observed_sharpe?.toFixed(2)}</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">MIN BENCHMARK SHARPE</span>
                    <span className="text-amber-400 font-bold">{resultData.benchmark_sharpe?.toFixed(2)}</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">DEFLATED SHARPE PROBABILITY</span>
                    <span className={`font-bold ${resultData.dsr_probability >= 0.95 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {(resultData.dsr_probability * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">OVERFITTING VERDICT</span>
                    <span className={`font-bold ${resultData.is_statistically_significant ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {resultData.is_statistically_significant ? 'PASSED (GENUINE)' : 'FAILED (OVERFITTED)'}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Subtab 5: Low Latency Memory Profiler */}
      {activeSubTab === 'lowLatency' && (
        <div className="space-y-4">
          <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-emerald-300">Zero-Allocation Freelist Memory Profiler</h3>
                <p className="text-xs text-slate-400 mt-1">
                  Benchmarks custom C++/Python zero-allocation freelist memory pool against standard heap allocation across 500,000 order events.
                </p>
              </div>
              <button
                onClick={runLowLatencyBench}
                disabled={loading}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold transition-all shadow-lg shadow-emerald-600/20 disabled:opacity-50"
              >
                {loading ? 'Profiling 500k Events...' : 'Run Memory Benchmark'}
              </button>
            </div>

            {resultData && (
              <div className="mt-5 space-y-4 font-mono text-xs">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">FREELIST EXEC TIME</span>
                    <span className="text-emerald-400 font-bold">{resultData.freelist_execution_time_sec?.toFixed(4)}s</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">STANDARD HEAP TIME</span>
                    <span className="text-rose-400 font-bold">{resultData.standard_heap_execution_time_sec?.toFixed(4)}s</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">SPEEDUP FACTOR</span>
                    <span className="text-amber-300 font-bold">{resultData.speedup_factor?.toFixed(2)}x Faster</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">FREELIST ALLOCATIONS</span>
                    <span className="text-emerald-300 font-bold">{resultData.freelist_allocations_count} (ZERO GC)</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Subtab 6: OFI */}
      {activeSubTab === 'ofi' && (
        <div className="space-y-4">
          <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-indigo-300">Level-2 Order Flow Imbalance (OFI) & Micro-Price</h3>
                <p className="text-xs text-slate-400 mt-1">
                  Calculates Order Flow Imbalance (OFI) and Micro-Price (P_micro) for HFT lead-lag signals.
                </p>
              </div>
              <button
                onClick={runOFI}
                disabled={loading}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold transition-all shadow-lg shadow-indigo-600/20 disabled:opacity-50"
              >
                {loading ? 'Computing OFI...' : 'Run OFI Signal Test'}
              </button>
            </div>

            {resultData && (
              <div className="mt-5 space-y-4 font-mono text-xs">
                <div className="overflow-x-auto border border-slate-800 rounded-lg">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-900 text-slate-400 uppercase text-[10px]">
                      <tr>
                        <th className="py-2 px-3">Bid Price</th>
                        <th className="py-2 px-3">Bid Vol</th>
                        <th className="py-2 px-3">Ask Price</th>
                        <th className="py-2 px-3">Ask Vol</th>
                        <th className="py-2 px-3">OFI Signal</th>
                        <th className="py-2 px-3">Micro-Price</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {resultData.map((row: any, idx: number) => (
                        <tr key={idx}>
                          <td className="py-2 px-3 text-emerald-400 font-bold">${row.bid_price}</td>
                          <td className="py-2 px-3 text-slate-300">{row.bid_vol}</td>
                          <td className="py-2 px-3 text-rose-400 font-bold">${row.ask_price}</td>
                          <td className="py-2 px-3 text-slate-300">{row.ask_vol}</td>
                          <td className={`py-2 px-3 font-bold ${row.ofi > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{row.ofi}</td>
                          <td className="py-2 px-3 text-amber-300">${row.micro_price?.toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Subtab 7: Multi-Asset */}
      {activeSubTab === 'multiAsset' && (
        <div className="space-y-4">
          <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-indigo-300">Multi-Asset Stock Pool Backtest Engine</h3>
                <p className="text-xs text-slate-400 mt-1">
                  Vectorized multi-asset stock pool simulator with daily alpha ranking, sector concentration caps & position limits.
                </p>
              </div>
              <button
                onClick={runMultiAsset}
                disabled={loading}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold transition-all shadow-lg shadow-indigo-600/20 disabled:opacity-50"
              >
                {loading ? 'Simulating Stock Pool...' : 'Run Pool Simulation (7 Stocks)'}
              </button>
            </div>

            {resultData && (
              <div className="mt-5 space-y-4 font-mono text-xs">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">TOTAL RETURN</span>
                    <span className="text-emerald-400 font-bold">{(resultData.total_return * 100).toFixed(2)}%</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px]">SHARPE RATIO</span>
                    <span className="text-indigo-400 font-bold">{resultData.sharpe_ratio?.toFixed(2)}</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg bor