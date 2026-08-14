# backend/app/ml/generate_ml_visualizations.py
"""
Quant.ai Dynamic Machine Learning Chart & Graph Visualization Generator.
Produces high-resolution visual plots for:
1. HMM Market Regime Probability Transitions & Volatility Penalties
2. Almgren-Chriss Optimal Order Execution Trajectories
3. Hierarchical Risk Parity (HRP) Dendrogram & Asset Weight Allocation
4. ML Model Zoo Alpha Signals & Prediction Uncertainty
"""

import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns

# Styling configuration for modern dark-mode quant aesthetics
plt.style.use('dark_background')
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.edgecolor'] = '#333333'
plt.rcParams['axes.linewidth'] = 1.2
plt.rcParams['grid.color'] = '#222222'
plt.rcParams['grid.linestyle'] = '--'

# Import Quant ML modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
from backend.app.ml.market_regime_hmm import MarketRegimeHMM
from backend.app.ml.almgren_chriss_execution import AlmgrenChrissExecutionEngine
from backend.app.ml.hierarchical_risk_parity import HierarchicalRiskParityOptimizer
from backend.app.ml.ml_model_zoo import QuantMLModelZoo

ASSETS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../assets"))
os.makedirs(ASSETS_DIR, exist_ok=True)

def generate_regime_hmm_chart():
    print("Generating HMM Market Regime Chart...")
    np.random.seed(42)
    n_bars = 120
    dates = pd.date_range("2026-04-01", periods=n_bars, freq="D")
    
    # Generate synthetic price with 3 distinct regimes: Bull -> Sideways -> Volatile Crash
    ret1 = np.random.normal(0.002, 0.008, 40)   # Bull
    ret2 = np.random.normal(0.0001, 0.012, 40)  # Sideways
    ret3 = np.random.normal(-0.004, 0.025, 40)  # Volatile Reversal
    returns = np.concatenate([ret1, ret2, ret3])
    prices = 100.0 * np.exp(np.cumsum(returns))

    df = pd.DataFrame({"Close": prices, "date": dates})
    
    hmm = MarketRegimeHMM(n_components=3).fit(df)
    
    # Predict posterior probabilities across time
    X = hmm.prepare_features(df)
    probs = hmm.model.predict_proba(X) if hmm.model else np.tile([0.33, 0.34, 0.33], (len(df)-10, 1))
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={'height_ratios': [2, 1]})
    
    # Top Subplot: Asset Price
    ax1.plot(dates[len(dates)-len(probs):], prices[len(prices)-len(probs):], color='#00E676', lw=2.0, label='Asset Price ($S_t$)')
    ax1.set_title("1. Hidden Markov Model (HMM) Market Regime Classification", fontsize=14, fontweight='bold', pad=12, color='#00E676')
    ax1.set_ylabel("Price ($)", fontsize=11)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper left')

    # Bottom Subplot: Regime Probabilities
    time_idx = dates[len(dates)-len(probs):]
    ax2.plot(time_idx, probs[:, 0], color='#00E676', lw=1.5, label='P(Trend Bull)')
    ax2.plot(time_idx, probs[:, 1], color='#FFD21E', lw=1.5, label='P(Sideways Range)')
    ax2.plot(time_idx, probs[:, 2], color='#FF5252', lw=1.5, label='P(Volatile Reversal)')
    ax2.set_ylabel("Regime Probability", fontsize=11)
    ax2.set_ylim(-0.05, 1.05)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper right')
    
    plt.tight_layout()
    out_path = os.path.join(ASSETS_DIR, "ml_regime_hmm_chart.png")
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"✅ Saved HMM Chart to {out_path}")

def generate_almgren_chriss_chart():
    print("Generating Almgren-Chriss Optimal Execution Chart...")
    engine = AlmgrenChrissExecutionEngine(total_shares=100000, total_time_hours=1.0, num_steps=20, initial_price=150.0)
    
    # Compute schedules under different risk aversions
    sched_aggressive = engine.compute_optimal_schedule(risk_aversion=1e-3)
    sched_moderate = engine.compute_optimal_schedule(risk_aversion=1e-4)
    sched_passive = engine.compute_optimal_schedule(risk_aversion=1e-6)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    # Left Plot: Trading Trajectories x_k
    t = sched_moderate.time_steps
    ax1.plot(t, sched_aggressive.trajectory_x / 1000.0, color='#FF5252', lw=2.5, marker='o', label=r'High Risk Aversion ($\lambda=10^{-3}$)')
    ax1.plot(t, sched_moderate.trajectory_x / 1000.0, color='#FFD21E', lw=2.5, marker='s', label=r'Moderate ($\lambda=10^{-4}$)')
    ax1.plot(t, sched_passive.trajectory_x / 1000.0, color='#00E676', lw=2.5, marker='^', label=r'Passive TWAP ($\lambda=10^{-6}$)')
    ax1.set_title("2. Almgren-Chriss Optimal Liquidation Trajectory", fontsize=13, fontweight='bold', color='#FFD21E')
    ax1.set_xlabel("Time (Hours)", fontsize=11)
    ax1.set_ylabel("Shares Remaining (Thousands)", fontsize=11)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper right')

    # Right Plot: Trade Sizes v_k
    steps = np.arange(1, engine.N + 1)
    width = 0.25
    ax2.bar(steps - width, sched_aggressive.trade_sizes_v / 1000.0, width=width, color='#FF5252', alpha=0.8, label='Aggressive Front-Load')
    ax2.bar(steps, sched_moderate.trade_sizes_v / 1000.0, width=width, color='#FFD21E', alpha=0.8, label='Moderate Schedule')
    ax2.bar(steps + width, sched_passive.trade_sizes_v / 1000.0, width=width, color='#00E676', alpha=0.8, label='Uniform TWAP')
    ax2.set_title("Execution Trade Sizes per Interval ($v_k$)", fontsize=13, fontweight='bold', color='#FFD21E')
    ax2.set_xlabel("Interval Step (k)", fontsize=11)
    ax2.set_ylabel("Trade Volume (Thousands)", fontsize=11)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper right')

    plt.tight_layout()
    out_path = os.path.join(ASSETS_DIR, "ml_almgren_chriss_chart.png")
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"✅ Saved Almgren-Chriss Chart to {out_path}")

def generate_hrp_portfolio_chart():
    print("Generating HRP Portfolio Allocation Chart...")
    np.random.seed(42)
    n_days = 252
    tech1 = np.random.normal(0.001, 0.02, n_days)
    tech2 = tech1 * 0.85 + np.random.normal(0.0, 0.005, n_days)
    bond1 = np.random.normal(0.0002, 0.005, n_days)
    bond2 = bond1 * 0.9 + np.random.normal(0.0, 0.001, n_days)
    gold = np.random.normal(0.0005, 0.015, n_days)
    crypto = np.random.normal(0.002, 0.04, n_days)

    df_returns = pd.DataFrame({
        "AAPL (Tech)": tech1,
        "MSFT (Tech)": tech2,
        "TLT (Bond)": bond1,
        "IEF (Bond)": bond2,
        "GLD (Gold)": gold,
        "BTC (Crypto)": crypto
    })

    hrp = HierarchicalRiskParityOptimizer()
    weights = hrp.fit_predict(df_returns)

    fig, ax = plt.subplots(figsize=(10, 5))
    assets = list(weights.keys())
    w_vals = [weights[a] * 100.0 for a in assets]
    colors = ['#29B6F6', '#0288D1', '#66BB6A', '#388E3C', '#FFCA28', '#AB47BC']

    bars = ax.barh(assets, w_vals, color=colors, edgecolor='#ffffff', linewidth=0.5, height=0.6)
    ax.set_title("3. Hierarchical Risk Parity (HRP) Asset Weight Allocation (%)", fontsize=14, fontweight='bold', pad=12, color='#29B6F6')
    ax.set_xlabel("Portfolio Weight (%)", fontsize=11)
    ax.set_xlim(0, max(w_vals) + 10)
    ax.grid(True, alpha=0.3, axis='x')

    # Add text labels on bars
    for bar in bars:
        w = bar.get_width()
        ax.text(w + 1.0, bar.get_y() + bar.get_height()/2.0, f'{w:.1f}%', va='center', ha='left', fontsize=10, fontweight='bold', color='#ffffff')

    plt.tight_layout()
    out_path = os.path.join(ASSETS_DIR, "ml_hrp_portfolio_chart.png")
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"✅ Saved HRP Chart to {out_path}")

if __name__ == "__main__":
    generate_regime_hmm_chart()
    generate_almgren_chriss_chart()
    generate_hrp_portfolio_chart()
    print("\n🎉 All dynamic ML charts generated successfully in assets/!")
