# backend/data/run_continuous_ml_research.py
"""
Continuous Autonomous Quant ML Research & Peak-Finding Engine.
Loads historical trade records from Hugging Face dataset (Ypeng12/quant-ai-trade-history),
extracts top profitable trades (PnL > 0, high R-multiple gains), trains calibrated LightGBM
probability models, pre-computes predictions, and synchronizes with LiveTradingRunner.
"""

import os
import sys
import json
import joblib
import datetime
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATASETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "datasets")
MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "ml", "models")
HF_DATASET_REPO = "Ypeng12/quant-ai-trade-history"

def load_hf_trade_history() -> List[dict]:
    """Loads trade history from HuggingFace dataset or local master json."""
    trades = []
    # 1. Try local master trade history
    local_master = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trade_history.json")
    if os.path.exists(local_master):
        try:
            with open(local_master, 'r', encoding='utf-8') as f:
                data = json.load(f)
                trades = data.get("trade_history", [])
                if trades:
                    print(f"[*] 已从本地 master 成功读取 {len(trades)} 笔复盘交易履历。")
                    return trades
        except Exception as e:
            print(f"⚠️ 读取本地 master 失败: {e}")

    # 2. Try HuggingFace dataset hub
    try:
        from huggingface_hub import hf_hub_download
        token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_HUB_TOKEN")
        dl_path = hf_hub_download(repo_id=HF_DATASET_REPO, filename="historical_trades_archive.json", repo_type="dataset", token=token)
        with open(dl_path, 'r', encoding='utf-8') as f:
            trades = json.load(f).get("trade_history", [])
            print(f"[*] 已从 HuggingFace Dataset ({HF_DATASET_REPO}) 成功拉取 {len(trades)} 笔复盘交易履历。")
    except Exception as e:
        print(f"⚠️ HuggingFace Dataset 拉取提示: {e}")

    return trades

def analyze_top_profitable_patterns(trades: List[dict]) -> dict:
    """Analyzes top profitable trades to extract key quantitative win factors."""
    if not trades:
        print("⚠️ 交易履历为空，跳过特征统计。")
        return {}

    df = pd.DataFrame(trades)
    closed = df[df["action"].isin(["SELL", "COVER", "PARTIAL_SELL", "PARTIAL_COVER"])].copy()
    if closed.empty:
        print("⚠️ 没有已平仓交易记录。")
        return {}

    closed["pnl"] = pd.to_numeric(closed["pnl"], errors="coerce").fillna(0.0)
    wins = closed[closed["pnl"] > 0]
    top_wins = closed[closed["pnl"] >= closed["pnl"].quantile(0.75)]

    print(f"\n=========================================================================")
    print(f"📊 [HF 复盘数据挖掘] 历史全量交易分析报告")
    print(f"=========================================================================")
    print(f"  ├─ 总计已归档交易: {len(trades)} 笔 | 平仓核算: {len(closed)} 笔")
    print(f"  ├─ 盈利交易笔数  : {len(wins)} 笔 (胜率: {len(wins)/len(closed)*100:.1f}%)")
    print(f"  ├─ 净已实现盈亏  : ${closed['pnl'].sum():+,.2f} USD")
    print(f"  └─ Top 25% 极佳获利交易笔数: {len(top_wins)} 笔 (平均获利: ${top_wins['pnl'].mean():+,.2f})")
    print(f"=========================================================================\n")

    return {
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "win_count": len(wins),
        "total_pnl": float(closed['pnl'].sum()),
        "top_win_avg_pnl": float(top_wins['pnl'].mean()) if not top_wins.empty else 0.0,
    }

def run_ml_research_pipeline():
    print(f"\n🤖 [Quant ML Engine] 启动全自动机器学习训练、胜率校准与 peak-finding 模型迭代...")
    trades = load_hf_trade_history()
    stats = analyze_top_profitable_patterns(trades)

    # 1. Trigger ML model training & calibration
    from data.train_probability_model import train_and_calibrate_direction
    try:
        from data.build_intraday_5m_dataset import build_intraday_5m_watchlist_dataset
        df_5m = build_intraday_5m_watchlist_dataset(tickers=["SNDK", "TSLA", "NVDA"], period="5d")
        if df_5m is not None and not df_5m.empty:
            train_and_calibrate_direction(df_5m, "label_target_long", "long")
            train_and_calibrate_direction(df_5m, "label_target_short", "short")
    except Exception as e:
        print(f"⚠️ ML 训练管线提示: {e}")

    # 2. Re-build pre-computed predictions cache
    try:
        from data.build_ml_predictions_cache import generate_and_save_ml_cache
        generate_and_save_ml_cache()
    except Exception as e:
        print(f"⚠️ Predictions cache 提示: {e}")

    # 3. Synchronize with Live Trading Runner
    try:
        from app.broker.live_runner import LiveTradingRunner
        runner = LiveTradingRunner()
        runner.strategy_params.update({
            "strategy_version": "ml_peak_finder_5m_v1",
            "timeframe": "5m",
            "entry_score_min": 65.0,
            "min_expected_value_r": 0.15,
            "hold_runner_trend": True,
            "max_daily_trades_total": 5,
            "max_symbol_daily_trades": 2,
        })
        runner.save_runner_config()
        print("✅ 已成功将全新训练校准的 ML Peak-Finder 模型部署至 Quant AI 自动交易引擎！")
    except Exception as e:
        print(f"⚠️ Live runner sync 提示: {e}")

if __name__ == "__main__":
    run_ml_research_pipeline()
