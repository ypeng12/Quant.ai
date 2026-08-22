# backend/app/ml/unified_strategy_pipeline.py
"""
Unified Systematic Quant Trading Pipeline.
Orchestrates:
1. Tier 1: MarketRegimeHMM (Unsupervised Regime Classifier)
2. Tier 2: QuantMLModelZoo (Calibrated ML Alpha & Uncertainty Predictor)
3. Tier 3: RLTradingAgent (Adaptive Reinforcement Learning Policy Engine)

Outputs unified trade recommendations, dynamic stop-loss prices, position sizes, and rationale.
"""

import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional

from backend.app.ml.market_regime_hmm import MarketRegimeHMM
from backend.app.ml.ml_model_zoo import QuantMLModelZoo, FEATURE_COLS
from backend.app.ml.rl_trading_agent import TradingEnvironment, RLTradingAgent, ACTIONS

class UnifiedQuantStrategyPipeline:
    def __init__(self, atr_multiplier: float = 1.5):
        self.hmm_engine: Optional[MarketRegimeHMM] = None
        self.ml_zoo: Optional[QuantMLModelZoo] = None
        self.rl_agent: Optional[RLTradingAgent] = None
        self.atr_multiplier = atr_multiplier

    def initialize_or_load(self):
        """Loads pre-trained models from storage or instantiates default models."""
        self.hmm_engine = MarketRegimeHMM.load()
        self.ml_zoo = QuantMLModelZoo.load_zoo()
        self.rl_agent = RLTradingAgent.load()
        return self

    def fit_all(self, df: pd.DataFrame) -> 'UnifiedQuantStrategyPipeline':
        """Fits HMM, ML Model Zoo, and RL Agent on historical dataframe."""
        # 1. Fit HMM
        self.hmm_engine = MarketRegimeHMM()
        self.hmm_engine.fit(df)

        # 2. Fit ML Model Zoo
        self.ml_zoo = QuantMLModelZoo()
        if "label_win_long" not in df.columns:
            fwd_ret = df["Close"].pct_change().shift(-1) if "Close" in df.columns else pd.Series(np.zeros(len(df)))
            df = df.copy()
            df["future_ret_1d_pct"] = fwd_ret * 100.0
            df["label_win_long"] = (fwd_ret > 0).astype(int)

        # Fill missing features for fitting
        for col in FEATURE_COLS:
            if col not in df.columns:
                df[col] = 0.0

        self.ml_zoo.fit_ridge_baseline(df)
        self.ml_zoo.fit_lgbm_classifier(df)

        # 3. Fit RL Trading Agent
        env = TradingEnvironment(
            df=df,
            feature_cols=FEATURE_COLS,
            fwd_ret_col="future_ret_1d_pct",
            cost_bps=5.0
        )
        self.rl_agent = RLTradingAgent(state_dim=6)
        self.rl_agent.train(env, episodes=10)

        return self

    def predict_trade_decision(self, symbol: str, feature_df: pd.DataFrame, current_price: float) -> Dict:
        """
        Executes unified inference across Tier 1 (HMM) -> Tier 2 (Model Zoo) -> Tier 3 (RL Agent).
        Returns complete trade signal payload with rationale and dynamic stop-loss.
        """
        if self.hmm_engine is None or self.ml_zoo is None or self.rl_agent is None:
            self.initialize_or_load()

        # 1. Tier 1: HMM Regime Analysis
        regime_info = self.hmm_engine.predict_regime_probabilities(feature_df)
        dominant_regime = regime_info.get("dominant_regime", "RANGE_SIDEWAYS")
        vol_penalty = regime_info.get("volatility_penalty", 1.0)

        # 2. Tier 2: Calibrated ML Alpha & Uncertainty
        ml_preds = self.ml_zoo.predict_joint(feature_df)
        p_win = ml_preds.get("p_win", 0.50)
        p_std = ml_preds.get("p_std", 0.05)
        ret_pred = ml_preds.get("return_pred_pct", 0.0)

        # Extract technical features
        mom_5d = float(feature_df["feature_mom_3_pct"].iloc[-1]) if "feature_mom_3_pct" in feature_df.columns else 0.0
        atr_pct = max(0.1, abs(float(feature_df["feature_atr_pct"].iloc[-1]))) if "feature_atr_pct" in feature_df.columns else 2.0

        # Construct RL state vector: [p_win, ret_pred, vol_penalty, mom_5d, atr_pct, cur_pos=0.0]
        rl_state = np.array([p_win, ret_pred, vol_penalty, mom_5d, atr_pct, 0.0])
        rl_decision = self.rl_agent.predict_action(rl_state)

        action_name = rl_decision["action_name"]
        target_pos = rl_decision["target_position"]

        # Calculate dynamic k * ATR stop-loss price
        atr_val = current_price * (atr_pct / 100.0)
        stop_loss_price = round(current_price - (self.atr_multiplier * atr_val), 2)
        take_profit_price = round(current_price + (2.5 * self.atr_multiplier * atr_val), 2)

        # Rationalization Engine
        if action_name == "CASH":
            reason = f"HMM模式识别为[{dominant_regime}]，整体波幅较大或概率置信度较低 (P_win={p_win:.2%})，智能体触发空仓避险 (CASH) 锁定本金。"
        elif action_name == "LONG_FULL":
            reason = f"高概率突破信号 (P_win={p_win:.2%}, 预期收益率={ret_pred:+.2f}%)，处于动量扩张期，智能体触发满仓多头 (LONG_FULL)。"
        else:
            reason = f"行情处于多空拉锯状态 (P_win={p_win:.2%})，智能体触发半仓防御 (LONG_HALF) 以降低回撤 risk。"

        return {
            "symbol": symbol,
            "current_price": current_price,
            "trade_action": action_name,
            "target_position_pct": round(target_pos * 100.0, 1),
            "signal_confidence_pwin": round(p_win * 100.0, 1),
            "uncertainty_std": p_std,
            "market_regime": dominant_regime,
            "volatility_penalty": vol_penalty,
            "stop_loss_price": stop_loss_price,
            "take_profit_price": take_profit_price,
            "recommendation_reason": reason
        }

if __name__ == "__main__":
    print("Testing UnifiedQuantStrategyPipeline...")
    np.random.seed(42)
    n_samples = 100
    dummy_feat = pd.DataFrame({
        "feature_rvol": np.random.uniform(1.0, 2.5, n_samples),
        "feature_vwap_dist_pct": np.random.normal(0, 1, n_samples),
        "feature_mom_3_pct": np.random.normal(0.5, 2.0, n_samples),
        "feature_mom_10_pct": np.random.normal(1.0, 3.0, n_samples),
        "feature_atr_pct": np.random.uniform(1.5, 3.0, n_samples),
        "feature_high_to_now_pct": np.random.uniform(-2, 0, n_samples),
        "feature_low_to_now_pct": np.random.uniform(0, 2, n_samples),
        "feature_session_range_pct": np.random.uniform(1, 3, n_samples),
        "feature_upper_wick_ratio": np.random.uniform(0, 0.4, n_samples),
        "feature_lower_wick_ratio": np.random.uniform(0, 0.4, n_samples),
        "feature_mom_decay": np.random.normal(0, 0.5, n_samples),
        "feature_vwap_overextension": np.random.normal(0, 1, n_samples),
        "Close": 100 + np.cumsum(np.random.normal(0, 1, n_samples))
    })

    pipeline = UnifiedQuantStrategyPipeline()
    pipeline.fit_all(dummy_feat)
    res = pipeline.predict_trade_decision("TSLA", dummy_feat.iloc[[-1]], current_price=362.86)
    print("\nUnified Strategy Signal Payload:")
    for k, v in res.items():
        print(f"  {k:25s}: {v}")
