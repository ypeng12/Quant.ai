// frontend/src/components/InstitutionalPanel.tsx

import React, { useState } from 'react';
import { API_BASE } from '../config';

export const InstitutionalPanel: React.FC = () => {
  const [activeSubTab, setActiveSubTab] = useState<'optimal' | 'statArb' | 'riskParity' | 'dsr' | 'lowLatency' | 'ofi' | 'multiAsset'>('optimal');
  const [loading, setLoading] = useState<boolean>(false);
  const [resultData, setResultData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

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
      if (data.success) {
        setResultData(data);
      } else {
        setError(data.error || 'Failed to simulate optimal execution');
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // 2. StatArb Pairs Trading Trigger
  const runStatArb = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/stat-arb/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker_y: 'KO',
          ticker_x: 'PEP',
          period: '1y',
          z_entry: 2.0,
          z_exit: 0.5
        })
      });
      const data = await res.json();
      if (data.success) {
        setResultData(data.result);
      } else {
        setError(data.error || 'Failed to run stat arb');
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // 3. Risk Parity Allocation Trigger
  const runRiskParity = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/portfolio/optimize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tickers: ['AAPL', 'MSFT', 'TSLA', 'NVDA', 'AMZN'],
          period: '1y'
        })
      });
      const data = await res.json();
      if (data.success) {
        setResultData(data);
      } else {
        setError(data.error || 'Failed to calculate Risk Parity');
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // 4. Deflated Sharpe Ratio Trigger
  const runDSR = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/metrics/dsr`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker: 'TSLA',
          period: '1y',
          num_trials: 50
        })
      });
      const data = await res.json();
      if (data.success) {
        setResultData(data.result);
      } else {
        setError(data.error || 'Failed to calculate DSR');
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
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
      if (data.success) {
        setResultData(data.result);
      } else {
        setError(data.error || 'Failed to run low latency benchmark');
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-2xl text-slate-100 mt-6">
      <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-6">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <span>🏛️</span> Institutional Quantitative Architecture Terminal
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Proprietary Trading & Quantitative Research Suite (Jane Street / Citadel / Jump Trading Standards)
          </p>
        </div>
        <span className="px-3 py-1 rounded-full text-xs font-mono bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
          PRO QUANT ENGINE ACTIVE
        </span>
      </div>

      {/* Sub-tab Selectors */}
      <div className="flex gap-2 border-b border-slate-800 pb-3 mb-6 overflow-x-auto">
        <button
          onClick={() => { setActiveSubTab('optimal'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'optimal'
              ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          📈 Almgren-Chriss Execution
        </button>

        <button
          onClick={() => { setActiveSubTab('statArb'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'statArb'
              ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          ⚖️ Cointegration & StatArb (OU)
        </button>

        <button
          onClick={() => { setActiveSubTab('riskParity'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'riskParity'
              ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          🛡️ Risk Parity (ERC + Ledoit-Wolf)
        </button>

        <button
          onClick={() => { setActiveSubTab('dsr'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'dsr'
              ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          🔬 Deflated Sharpe Ratio (DSR)
        </button>

        <button
          onClick={() => { setActiveSubTab('lowLatency'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'lowLatency'
              ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          ⚡ Zero-Alloc Memory Profiler
        </button>

        <button
          onClick={() => { setActiveSubTab('ofi'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'ofi'
              ? 'bg-amber-600 text-white shadow-lg shadow-amber-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          📊 Order Flow Imbalance (OFI)
        </button>

        <button
          onClick={() => { setActiveSubTab('multiAsset'); setResultData(null); }}
          className={`px-4 py-2 text-xs font-semibold rounded-lg transition-all ${
            activeSubTab === 'multiAsset'
              ? 'bg-cyan-600 text-white shadow-lg shadow-cyan-600/30'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          🌐 Multi-Asset Stock Pool Backtest
        </button>
      </div>

      {/* Control Actions & Description */}
      <div className="bg-slate-950/60 p-4 rounded-lg border border-slate-800/80 mb-6">
        {activeSubTab === 'ofi' && (
          <div className="flex justify-between items-center">
            <div>
              <h4 className="text-sm font-bold text-white">Order Flow Imbalance (OFI) & Micro-Price Engine</h4>
              <p className="text-xs text-slate-400 mt-1">
                Computes tick-by-tick OFI supply/demand imbalance and volume-weighted micro-price P_micro.
              </p>
            </div>
            <button
              onClick={runOFI}
              disabled={loading}
              className="px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white font-semibold text-xs rounded-lg transition-all shadow-md"
            >
              {loading ? 'Computing OFI...' : 'Run OFI Microstructure Analysis'}
            </button>
          </div>
        )}

        {activeSubTab === 'multiAsset' && (
          <div className="flex justify-between items-center">
            <div>
              <h4 className="text-sm font-bold text-white">Multi-Asset Stock Pool Vectorized Backtesting Engine</h4>
              <p className="text-xs text-slate-400 mt-1">
                Ranks 7-stock universe (AAPL, MSFT, TSLA, NVDA, AMZN, GOOGL, META) daily and rebalances Top-3 positions.
              </p>
            </div>
            <button
              onClick={runMultiAsset}
              disabled={loading}
              className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white font-semibold text-xs rounded-lg transition-all shadow-md"
            >
              {loading ? 'Backtesting Universe...' : 'Run Portfolio Backtest'}
            </button>
          </div>
        )}
        {activeSubTab === 'optimal' && (
          <div className="flex justify-between items-center">
            <div>
              <h4 className="text-sm font-bold text-white">Almgren-Chriss Optimal Trajectory & Market Impact</h4>
              <p className="text-xs text-slate-400 mt-1">
                Solves min E[Cost] + λ Var[Cost] for 100,000 shares across TWAP/VWAP vs. Almgren-Chriss inventory curves.
              </p>
            </div>
            <button
              onClick={runOptimalExecution}
              disabled={loading}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold text-xs rounded-lg transition-all shadow-md"
            >
              {loading ? 'Simulating...' : 'Run Execution Simulation'}
            </button>
          </div>
        )}

        {activeSubTab === 'statArb' && (
          <div className="flex justify-between items-center">
            <div>
              <h4 className="text-sm font-bold text-white">Engle-Granger Cointegration & Ornstein-Uhlenbeck Process</h4>
              <p className="text-xs text-slate-400 mt-1">
                Backtests KO / PEP pairs arbitrage, estimates hedge ratio (β), OU mean-reversion speed (θ) and half-life.
              </p>
            </div>
            <button
              onClick={runStatArb}
              disabled={loading}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold text-xs rounded-lg transition-all shadow-md"
            >
              {loading ? 'Testing Cointegration...' : 'Run StatArb Analysis'}
            </button>
          </div>
        )}

        {activeSubTab === 'riskParity' && (
          <div className="flex justify-between items-center">
            <div>
              <h4 className="text-sm font-bold text-white">Equal Risk Contribution (ERC) & Ledoit-Wolf Shrinkage</h4>
              <p className="text-xs text-slate-400 mt-1">
                Optimizes portfolio weights for AAPL, MSFT, TSLA, NVDA, AMZN so each asset contributes equally to risk.
              </p>
            </div>
            <button
              onClick={runRiskParity}
              disabled={loading}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold text-xs rounded-lg transition-all shadow-md"
            >
              {loading ? 'Optimizing Weights...' : 'Calculate Risk Parity'}
            </button>
          </div>
        )}

        {activeSubTab === 'dsr' && (
          <div className="flex justify-between items-center">
            <div>
              <h4 className="text-sm font-bold text-white">Marcos López de Prado Deflated Sharpe Ratio (DSR)</h4>
              <p className="text-xs text-slate-400 mt-1">
                Evaluates skewness, kurtosis, and N-trial expected max Sharpe to compute backtest overfitting p-value.
              </p>
            </div>
            <button
              onClick={runDSR}
              disabled={loading}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold text-xs rounded-lg transition-all shadow-md"
            >
              {loading ? 'Evaluating DSR...' : 'Run DSR Overfitting Test'}
            </button>
          </div>
        )}

        {activeSubTab === 'lowLatency' && (
          <div className="flex justify-between items-center">
            <div>
              <h4 className="text-sm font-bold text-white">Zero-Allocation Freelist Memory Pool & Perf Profiler</h4>
              <p className="text-xs text-slate-400 mt-1">
                Measures 500,000 market event hot-path processing comparing baseline heap allocations vs zero-alloc freelist pool.
              </p>
            </div>
            <button
              onClick={runLowLatencyBench}
              disabled={loading}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-semibold text-xs rounded-lg transition-all shadow-md"
            >
              {loading ? 'Profiling Memory...' : 'Run Low-Latency Profiler'}
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded-lg mb-6">
          ❌ Error: {error}
        </div>
      )}

      {/* Results Output Rendering */}
      {resultData && (
        <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 font-mono text-xs overflow-x-auto">
          <div className="flex items-center justify-between border-b border-slate-800 pb-2 mb-3">
            <span className="text-emerald-400 font-semibold">✓ ENGINE OUTPUT RESULTS</span>
            <span className="text-slate-500">JSON Protocol Payload</span>
          </div>

          <pre className="text-slate-300 max-h-96 overflow-y-auto leading-relaxed">
            {JSON.stringify(resultData, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
};
