# backend/app/ml/lob_microstructure_ml.py
"""
LOB Market Microstructure ML Suite:
1. Net Expected Edge Model (E[r_t] - Slippage - Adverse Selection - Fees)
2. Limit Order Fill Probability Model P(Fill in 100ms / 500ms | X)
3. Adverse Selection Model P(Adverse | X, Filled) & Maker vs Taker Smart Order Router (SOR).

Connects C++ LOB (orderbook.hpp & orderbook_ofi.py) with Machine Learning.
"""

import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.calibration import CalibratedClassifierCV
from lightgbm import LGBMClassifier, LGBMRegressor

MODELS_DIR = os.path.dirname(os.path.abspath(__file__))

MICRO_FEATURE_COLS = [
    "imbalance",
    "spread_bps",
    "microprice_minus_mid",
    "ofi",
    "depth_top5",
    "volatility_1m",
    "trade_sign",
    "momentum_3m",
    "queue_ahead"
]

class LOBMicrostructureMLSuite:
    def __init__(self):
        self.edge_regressor: Optional[LGBMRegressor] = None
        self.fill_prob_clf: Optional[CalibratedClassifierCV] = None
        self.adverse_selection_clf: Optional[CalibratedClassifierCV] = None
        self.feature_cols = MICRO_FEATURE_COLS

    def fit_synthetic_microstructure(self, df: Optional[pd.DataFrame] = None):
        """
        Trains the 3 Microstructure ML models on LOB event features.
        """
        if df is None:
            np.random.seed(42)
            n_samples = 1000
            df = pd.DataFrame({
                "imbalance": np.random.uniform(-1.0, 1.0, n_samples),
                "spread_bps": np.random.uniform(0.5, 3.0, n_samples),
                "microprice_minus_mid": np.random.normal(0, 0.05, n_samples),
                "ofi": np.random.normal(0, 50, n_samples),
                "depth_top5": np.random.uniform(100, 5000, n_samples),
                "volatility_1m": np.random.uniform(0.5, 2.5, n_samples),
                "trade_sign": np.random.choice([-1, 0, 1], n_samples),
                "momentum_3m": np.random.normal(0, 0.5, n_samples),
                "queue_ahead": np.random.randint(0, 500, n_samples),
                "target_mid_return_bps": np.random.normal(2.0, 5.0, n_samples),
                "target_filled_500ms": np.random.choice([0, 1], n_samples, p=[0.4, 0.6]),
                "target_adverse_fill": np.random.choice([0, 1], n_samples, p=[0.75, 0.25]),
            })

        X = df[self.feature_cols]

        # 1. Net Return Edge Model (Regression)
        y_edge = df["target_mid_return_bps"]
        self.edge_regressor = LGBMRegressor(n_estimators=40, learning_rate=0.05, max_depth=3, random_state=42, verbose=-1)
        self.edge_regressor.fit(X, y_edge)

        # 2. Limit Order Fill Probability Model P(Fill | X)
        y_fill = df["target_filled_500ms"]
        base_fill = LGBMClassifier(n_estimators=40, learning_rate=0.05, max_depth=3, random_state=42, verbose=-1)
        self.fill_prob_clf = CalibratedClassifierCV(estimator=base_fill, method="sigmoid", cv=3)
        self.fill_prob_clf.fit(X, y_fill)

        # 3. Adverse Selection Model P(Adverse | X, Filled)
        y_adverse = df["target_adverse_fill"]
        base_adverse = LGBMClassifier(n_estimators=40, learning_rate=0.05, max_depth=3, random_state=42, verbose=-1)
        self.adverse_selection_clf = CalibratedClassifierCV(estimator=base_adverse, method="sigmoid", cv=3)
        self.adverse_selection_clf.fit(X, y_adverse)

        return self

    def evaluate_maker_vs_taker_sor(
        self,
        lob_features: Dict,
        fees_bps: float = 0.2,
        fixed_adverse_cost_bps: float = 0.8
    ) -> Dict:
        """
        Smart Order Router (SOR) Decision Engine:
        Evaluates EV_maker vs EV_taker using ML predictions.
        Returns:
            Dict containing expected_edge_bps, p_fill, p_adverse, ev_maker_bps, ev_taker_bps, and recommended_order_type (LIMIT / MARKET / REJECT).
        """
        if self.edge_regressor is None:
            self.fit_synthetic_microstructure()

        df_feat = pd.DataFrame([{col: float(lob_features.get(col, 0.0)) for col in self.feature_cols}])

        # 1. Expected Mid Return
        exp_return_bps = float(self.edge_regressor.predict(df_feat)[0])

        # 2. Fill Probability
        p_fill = float(self.fill_prob_clf.predict_proba(df_feat)[0, 1])

        # 3. Adverse Selection Probability
        p_adverse = float(self.adverse_selection_clf.predict_proba(df_feat)[0, 1])

        spread_bps = float(lob_features.get("spread_bps", 1.5))
        slippage_bps = spread_bps / 2.0

        # Net Taker Expected Value (Cross Spread immediately)
        ev_taker_bps = exp_return_bps - slippage_bps - fees_bps

        # Expected Adverse Cost if filled
        expected_adverse_loss_bps = p_adverse * fixed_adverse_cost_bps

        # Net Maker Expected Value (Limit Order at Bid)
        ev_maker_bps = p_fill * (exp_return_bps - fees_bps - expected_adverse_loss_bps)

        # Smart Order Router Decision Rule
        min_trade_edge_threshold_bps = 0.5

        if max(ev_maker_bps, ev_taker_bps) < min_trade_edge_threshold_bps:
            recommendation = "REJECT_NO_EDGE"
        elif ev_maker_bps >= ev_taker_bps:
            recommendation = "LIMIT_MAKER"
        else:
            recommendation = "MARKET_TAKER"

        return {
            "expected_return_bps": round(exp_return_bps, 2),
            "p_fill_500ms": round(p_fill, 4),
            "p_adverse_selection": round(p_adverse, 4),
            "ev_maker_bps": round(ev_maker_bps, 2),
            "ev_taker_bps": round(ev_taker_bps, 2),
            "expected_net_edge_bps": round(max(ev_maker_bps, ev_taker_bps), 2),
            "recommended_order_type": recommendation,
            "decision_reason": (
                f"EV_maker ({ev_maker_bps:.2f} bps) > EV_taker ({ev_taker_bps:.2f} bps)"
                if recommendation == "LIMIT_MAKER"
                else (
                    f"EV_taker ({ev_taker_bps:.2f} bps) > EV_maker ({ev_maker_bps:.2f} bps)"
                    if recommendation == "MARKET_TAKER"
                    else f"Expected edge below threshold ({min_trade_edge_threshold_bps} bps)"
                )
            )
        }

if __name__ == "__main__":
    print("Testing LOBMicrostructureMLSuite Smart Order Router...")
    suite = LOBMicrostructureMLSuite().fit_synthetic_microstructure()

    sample_lob = {
        "imbalance": 0.65,
        "spread_bps": 1.2,
        "microprice_minus_mid": 0.04,
        "ofi": 35.0,
        "depth_top5": 1200.0,
        "volatility_1m": 1.1,
        "trade_sign": 1,
        "momentum_3m": 0.35,
        "queue_ahead": 45
    }

    decision = suite.evaluate_maker_vs_taker_sor(sample_lob)
    print("=========================================================================")
    print("LOB MICROSTRUCTURE ML & SMART ORDER ROUTER (SOR) DECISION")
    print("=========================================================================")
    for k, v in decision.items():
        print(f"  {k:<28}: {v}")
    print("=========================================================================")
