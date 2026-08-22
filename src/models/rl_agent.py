# src/models/rl_agent.py
"""
Quant.ai Model Wrapper for Reinforcement Learning Trading Agent.
Implements standard fit(df, feature_cols, target_col) and predict(df, feature_cols) interface.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional
from backend.app.ml.rl_trading_agent import TradingEnvironment, RLTradingAgent

class RLAgentModel:
    def __init__(self, episodes: int = 20, learning_rate: float = 0.05, cost_bps: float = 5.0):
        self.episodes = episodes
        self.learning_rate = learning_rate
        self.cost_bps = cost_bps
        self.agent: Optional[RLTradingAgent] = None

    def fit(self, train_df: pd.DataFrame, feature_cols: List[str], target_col: str = "fwd_ret_5d"):
        """Fits RL Agent policy on training dataset over multiple market episodes."""
        env = TradingEnvironment(
            df=train_df,
            feature_cols=feature_cols,
            fwd_ret_col=target_col,
            cost_bps=self.cost_bps
        )
        state_dim = len(env.feature_cols) + 1
        self.agent = RLTradingAgent(
            state_dim=state_dim,
            learning_rate=self.learning_rate,
            epsilon_start=0.8,
            epsilon_decay=0.98
        )
        self.agent.train(env, episodes=self.episodes)
        return self

    def predict(self, test_df: pd.DataFrame, feature_cols: List[str]) -> np.ndarray:
        """
        Predicts continuous alpha score / target portfolio position for out-of-sample test dataset.
        Returns target position weights [0.0, 1.0, 0.5] mapped as alpha score.
        """
        if self.agent is None:
            return np.zeros(len(test_df))

        scores = []
        cur_pos = 0.0
        
        for idx, row in test_df.iterrows():
            feat_vals = row[[c for c in feature_cols if c in test_df.columns]].fillna(0.0).values
            state = np.append(feat_vals, cur_pos)
            
            action_res = self.agent.predict_action(state)
            target_pos = action_res["target_position"]
            cur_pos = target_pos
            scores.append(target_pos)

        return np.array(scores)
