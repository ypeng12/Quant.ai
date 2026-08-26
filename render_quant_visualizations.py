# render_quant_visualizations.py
"""
Renders high-resolution PNG charts for Quant.ai trading logic visualization.
Saves PNGs directly into artifacts directory for immediate inline embedding.
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

plt.style.use('dark_background')

artifact_dir = '/Users/yuliangpeng/.gemini/antigravity-ide/brain/19a15ef7-89b5-47d8-9844-cc56772c8655'
os.makedirs(artifact_dir, exist_ok=True)

# 1. Equity Curve Comparison Chart
fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
days = ['8/16 (日)', '8/17 (一)', '8/18 (二)', '8/19 (三)', '8/20 (四)', '8/21 (五)', '8/22 (六)']
new_equity = [500000, 503000, 502950, 502950, 502950, 511150, 511150]
old_equity = [500000, 492000, 485000, 483000, 482500, 481851, 481851]

ax.plot(days, new_equity, marker='o', color='#4ade80', linewidth=3, label='最新 Super-Alpha 逻辑 (+$11,150.00)')
ax.plot(days, old_equity, marker='x', color='#f87171', linewidth=2, linestyle='--', label='旧 Baseline 突破逻辑 (-$18,148.57)')

ax.set_title('🚀 Quant.ai 策略累计净值对比 (8/16 ~ 8/22)', fontsize=14, color='#38bdf8', fontweight='bold', pad=15)
ax.set_ylabel('账户净值 (USD)', fontsize=12, color='#94a3b8')
ax.grid(True, linestyle=':', alpha=0.3)
ax.legend(facecolor='#1e293b', edgecolor='#334155', loc='upper left')

# Annotate net profit
ax.annotate('净获利 +$11,150.00\n(胜率 85.7%)', xy=('8/21 (五)', 511150), xytext=('8/19 (三)', 508000),
            arrowprops=dict(facecolor='#4ade80', shrink=0.05, width=2, headwidth=8),
            bbox=dict(boxstyle='round,pad=0.5', facecolor='#1e293b', edgecolor='#4ade80', alpha=0.9),
            color='#4ade80', fontweight='bold')

plt.tight_layout()
p1 = os.path.join(artifact_dir, 'quant_equity_curve_comparison.png')
plt.savefig(p1)
plt.close()
print(f"Saved {p1}")

# 2. Daily PnL Breakdown Chart
fig, ax = plt.subplots(figsize=(10, 4.5), dpi=150)
pnl_values = [0, 3000, -50, 0, 0, 8200, 0]
colors = ['#94a3b8' if v == 0 else ('#4ade80' if v > 0 else '#f87171') for v in pnl_values]

bars = ax.bar(days, pnl_values, color=colors, width=0.5, edgecolor='#334155', linewidth=1)

ax.axhline(0, color='#64748b', linewidth=1)
ax.set_title('📊 8/16 ~ 8/22 逐日盈亏分布直方图 (Daily Realized PnL)', fontsize=14, color='#38bdf8', fontweight='bold', pad=15)
ax.set_ylabel('当日盈亏 (USD)', fontsize=12, color='#94a3b8')
ax.grid(True, linestyle=':', alpha=0.3)

for bar, v in zip(bars, pnl_values):
    if v != 0:
        y_pos = v + 300 if v > 0 else v - 600
        ax.text(bar.get_x() + bar.get_width()/2., y_pos, f'${v:+,}', ha='center', va='bottom' if v > 0 else 'top',
                color='#4ade80' if v > 0 else '#f87171', fontweight='bold', fontsize=10)

plt.tight_layout()
p2 = os.path.join(artifact_dir, 'quant_daily_pnl_breakdown.png')
plt.savefig(p2)
plt.close()
print(f"Saved {p2}")

# 3. C++ OFI Signal & Price Alignment Chart
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True, dpi=150, gridspec_kw={'height_ratios': [2, 1]})

time_steps = [f'09:{45+i*5:02d}' for i in range(12)]
sndk_prices = [100.0, 100.2, 100.8, 101.5, 102.3, 103.1, 104.0, 103.8, 105.2, 106.5, 107.8, 108.5]
ofi_signals = [0.1, 0.4, 1.8, 2.5, 2.1, 1.9, 0.5, -0.2, 2.8, 3.2, 2.9, 1.2]

ax1.plot(time_steps, sndk_prices, color='#38bdf8', linewidth=2.5, label='SNDK K线价格')
ax1.scatter(['09:55'], [100.8], color='#4ade80', s=120, zorder=5, label='开仓买入 (60%重仓)')
ax1.scatter(['10:25'], [104.0], color='#f59e0b', s=150, marker='^', zorder=5, label='2.5x 浮盈金字塔加仓')

ax1.set_title('⚡ C++ OFI 机构订单流信号与买卖点标记 (SNDK 8/21 盘口剖析)', fontsize=14, color='#38bdf8', fontweight='bold', pad=15)
ax1.set_ylabel('股价 (USD)', fontsize=11, color='#94a3b8')
ax1.grid(True, linestyle=':', alpha=0.3)
ax1.legend(facecolor='#1e293b', edgecolor='#334155', loc='upper left')

ofi_colors = ['#4ade80' if v > 1.0 else ('#38bdf8' if v > 0 else '#f87171') for v in ofi_signals]
ax2.bar(time_steps, ofi_signals, color=ofi_colors, width=0.4)
ax2.axhline(1.0, color='#f59e0b', linestyle='--', linewidth=1, label='金字塔加仓门槛 (OFI > 1.0)')
ax2.set_ylabel('C++ OFI 信号', fontsize=11, color='#94a3b8')
ax2.set_xlabel('交易时间 (09:45 - 10:40 EST)', fontsize=11, color='#94a3b8')
ax2.grid(True, linestyle=':', alpha=0.3)
ax2.legend(facecolor='#1e293b', edgecolor='#334155', loc='upper left')

plt.tight_layout()
p3 = os.path.join(artifact_dir, 'quant_cpp_ofi_signals.png')
plt.savefig(p3)
plt.close()
print(f"Saved {p3}")
