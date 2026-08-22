# backend/app/ml/rl_trading_agent.py
"""
Reinforcement Learning (RL) Trading Agent & Custom Trading Environment.
Implements Q-Learning / Deep Q-Network Policy for Adaptive Trading Execution:
- States: Technical Indicators (Momentum, Volatility, ATR, VWAP distance) + HMM Regime Probabilities + Current Position State
- Actions: 0 = CASH / OUT_OF_MARKET, 1 = LONG_FULL, 2 = LONG_HALF / DEFENSIVE
- Reward: Differential Return - Drawdown Penalty - Turnover / Transaction Cost Penalty
"""

import os
import sys
import joblib
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional

MODELS_DIR = os.path.dirname(os.path.abspath(__file__))

ACTIONS = {
    0: "CASH",
    1: "LONG_FULL",
    2: "LONG_HALF"
}

class TradingEnvironment:
    """
    Simulated Market Trading Environment for Reinforcement Learning Agent.
    """
    def __init__(
        self,
        df: pd.DataFrame,
        feature_cols: List[str],
        price_col: str = "Close",
        fwd_ret_col: str = "future_ret_1d_pct",
        cost_bps: float = 5.0,
        drawdown_penalty_factor: float = 0.5
    ):
        self.df = df.reset_index(drop=True)
        self.feature_cols = [c for c in feature_cols if c in self.df.columns]
        self.price_col = price_col if price_col in self.df.columns else "Close"
        self.fwd_ret_col = fwd_ret_col if fwd_ret_col in self.df.columns else "future_ret_1d_pct"
        self.cost_bps = cost_bps
        self.drawdown_penalty_factor = drawdown_penalty_factor

        self.current_step = 0
        self.max_steps = len(self.df) - 1
        self.current_position = 0.0  # 0.0 = CASH, 1.0 = LONG_FULL, 0.5 = LONG_HALF
        self.equity_curve = [1.0]

    def reset(self) -> np.ndarray:
        self.current_step = 0
        self.current_position = 0.0
        self.equity_curve = [1.0]
        return self._get_state()

    def _get_state(self) -> np.ndarray:
        if self.current_step >= len(self.df):
            row_features = np.zeros(len(self.feature_cols))
        else:
            row_features = self.df.iloc[self.current_step][self.feature_cols].astype(float).fillna(0.0).values
        # Append current position state (0.0, 1.0, 0.5) to feature vector
        state = np.append(row_features, self.current_position)
        return state

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict]:
        target_position = 0.0 if action == 0 else (1.0 if action == 1 else 0.5)
        position_change = abs(target_position - self.current_position)
        
        # Calculate gross return of the underlying bar
        raw_ret = float(self.df.iloc[self.current_step][self.fwd_ret_col]) / 100.0 if self.fwd_ret_col in self.df.columns else 0.0
        
        # Gross strategy return = target position * market forward return
        gross_ret = target_position * raw_ret
        
        # Deduct transaction cost bps on position rebalancing
        tc_deduction = (position_change * self.cost_bps) / 10000.0
        net_ret = gross_ret - tc_deduction

        # Update equity curve & position
        prev_equity = self.equity_curve[-1]
        new_equity = prev_equity * (1.0 + net_ret)
        self.equity_curve.append(new_equity)
        self.current_position = target_position

        # Drawdown calculation
        peak_equity = max(self.equity_curve)
        drawdown = (peak_equity - new_equity) / peak_equity if peak_equity > 0 else 0.0

        # Reward formulation: Upside Incentive + Net Return - Drawdown Penalty
        upside_incentive = 1.5 * net_ret if net_ret > 0 else 0.0
        reward = net_ret + upside_incentive - (self.drawdown_penalty_factor * drawdown)
        if action == 0 and raw_ret < 0:
            # Reward cash allocation during market downturns!
            reward += abs(raw_ret) * 0.5

        self.current_step += 1
        done = self.current_step >= self.max_steps
        next_state = self._get_state()

        info = {
            "net_return": net_ret,
            "equity": new_equity,
            "drawdown": drawdown,
            "action_name": ACTIONS.get(action, "CASH")
        }
        return next_state, reward, done, info

class RLTradingAgent:
    """
    Q-Learning / Policy Reinforcement Learning Trading Agent.
    Uses discretized state representation & Q-Table / Policy Network for Action Selection.
    """
    def __init__(
        self,
        state_dim: int,
        action_dim: int = 3,
        learning_rate: float = 0.05,
        discount_factor: float = 0.95,
        epsilon_start: float = 1.0,
        epsilon_min: float = 0.05,
        epsilon_decay: float = 0.995,
        n_bins: int = 4
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.lr = learning_rate
        self.gamma = discount_factor
        self.epsilon = epsilon_start
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.n_bins = n_bins

        # Discretization bins for Q-table states
        self.q_table: Dict[Tuple, np.ndarray] = {}

    def _discretize_state(self, state: np.ndarray) -> Tuple:
        """Converts continuous feature vector into a discrete tuple key for Q-table indexing."""
        clipped = np.clip(state, -3.0, 3.0)
        bins = np.linspace(-3.0, 3.0, self.n_bins)
        discrete_indices = tuple(np.digitize(clipped, bins))
        return discrete_indices

    def select_action(self, state: np.ndarray, evaluate: bool = False) -> int:
        """Selects action via Epsilon-Greedy Exploration or Greedy Policy."""
        if not evaluate and np.random.rand() < self.epsilon:
            return int(np.random.choice(self.action_dim))
        
        disc_state = self._discretize_state(state)
        if disc_state not in self.q_table:
            self.q_table[disc_state] = np.zeros(self.action_dim)
        
        return int(np.argmax(self.q_table[disc_state]))

    def train_step(self, state: np.ndarray, action: int, reward: float, next_state: np.ndarray, done: bool):
        """Performs Temporal Difference (TD) Q-Learning update."""
        s = self._discretize_state(state)
        s_next = self._discretize_state(next_state)

        if s not in self.q_table:
            self.q_table[s] = np.zeros(self.action_dim)
        if s_next not in self.q_table:
            self.q_table[s_next] = np.zeros(self.action_dim)

        best_next_q = 0.0 if done else np.max(self.q_table[s_next])
        td_target = reward + self.gamma * best_next_q
        td_error = td_target - self.q_table[s][action]

        self.q_table[s][action] += self.lr * td_error

        # Decay Epsilon
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

    def train(self, env: TradingEnvironment, episodes: int = 15) -> List[float]:
        """Trains RL Agent over specified number of market episodes."""
        episode_rewards = []
        for ep in range(episodes):
            state = env.reset()
            total_reward = 0.0
            done = False

            while not done:
                action = self.select_action(state, evaluate=False)
                next_state, reward, done, info = env.step(action)
                self.train_step(state, action, reward, next_state, done)
                state = next_state
                total_reward += reward

            episode_rewards.append(total_reward)
        return episode_rewards

    def predict_action(self, state: np.ndarray) -> Dict:
        """Evaluates best greedy action and action probabilities for single state vector."""
        action_idx = self.select_action(state, evaluate=True)
        s = self._discretize_state(state)
        q_vals = self.q_table.get(s, np.zeros(self.action_dim))
        
        # Softmax over Q-values for action probability estimation
        exp_q = np.exp(q_vals - np.max(q_vals))
        probs = exp_q / np.sum(exp_q)

        return {
            "action_id": action_idx,
            "action_name": ACTIONS[action_idx],
            "target_position": 0.0 if action_idx == 0 else (1.0 if action_idx == 1 else 0.5),
            "action_probabilities": {ACTIONS[i]: round(float(probs[i]), 4) for i in range(self.action_dim)}
        }

    def save(self, filepath: str = None):
        if filepath is None:
            filepath = os.path.join(MODELS_DIR, "models", "rl_trading_agent.joblib")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        joblib.dump(self, filepath)
        print(f"✅ RLTradingAgent successfully saved to {filepath}")

    @staticmethod
    def load(filepath: str = None) -> 'RLTradingAgent':
        if filepath is None:
            filepath = os.path.join(MODELS_DIR, "models", "rl_trading_agent.joblib")
        if os.path.exists(filepath):
            return joblib.load(filepath)
        return RLTradingAgent(state_dim=10)

if __name__ == "__main__":
    print("Testing TradingEnvironment & RLTradingAgent...")
    np.random.seed(42)
    n_bars = 100
    df_dummy = pd.DataFrame({
        "Close": 100 + np.cumsum(np.random.normal(0, 1, n_bars)),
        "feature_mom_5d": np.random.normal(0, 1, n_bars),
        "feature_atr_pct": np.random.uniform(1.0, 3.0, n_bars),
        "future_ret_1d_pct": np.random.normal(0.05, 1.2, n_bars)
    })
    
    env = TradingEnvironment(df_dummy, feature_cols=["feature_mom_5d", "feature_atr_pct"])
    agent = RLTradingAgent(state_dim=len(env.feature_cols) + 1)
    
    rewards = agent.train(env, episodes=5)
    print("Episode Training Rewards:", rewards)
    
    sample_state = env.reset()
    pred = agent.predict_action(sample_state)
    print("Sample State Greedy Prediction:", pred)
    agent.save()
