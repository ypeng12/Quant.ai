# run_daily_reflection.py
"""
Quant.ai Autonomous Daily Reflection & Auto-Optimization CLI
Executes end-of-day trade attribution analysis, RL/ML self-tuning, and generates markdown reflection reports.
Usage:
    python run_daily_reflection.py --date 2026-08-12
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from backend.app.ml.auto_reflection_engine import AutoReflectionEngine

def main():
    parser = argparse.ArgumentParser(description="Quant.ai Daily Self-Reflection Runner")
    parser.add_argument("--date", type=str, default="2026-08-12", help="Date string YYYY-MM-DD")
    args = parser.parse_args()

    print("\n" + "=" * 80)
    print(f"      QUANT.AI AUTONOMOUS DAILY SELF-REFLECTION & AUTO-TUNING")
    print(f"      Target Reflection Date: {args.date}")
    print("=" * 80 + "\n")

    engine = AutoReflectionEngine()
    report_path, attribution = engine.run_daily_reflection(args.date)

    print(f"✅ 【反思报告生成成功】: [reflection_{args.date}.md]({report_path})")
    print(f"  • 当日交易笔数: {attribution['total_trades']} 笔")
    print(f"  • 当日胜率:     {attribution['win_rate_%']}%")
    print(f"  • 当日实现盈亏: ${attribution['total_pnl']:+.2f}")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
