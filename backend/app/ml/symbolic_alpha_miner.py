# backend/app/ml/symbolic_alpha_miner.py
"""
Symbolic Alpha Miner & Formulaic Expression Tree Mining Engine.
Implements Genetic Programming (GP) to mine non-linear formulaic alpha expressions
from price-volume time series data.

Evaluates candidates using Rank Information Coefficient (Rank IC) and IC-IR.
"""

import os
import sys
import random
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Callable, Optional

# --- Primitive Operators ---
def ts_mom(series: pd.Series, d: int = 5) -> pd.Series:
    return series.pct_change(d).fillna(0.0)

def ts_std(series: pd.Series, d: int = 5) -> pd.Series:
    return series.rolling(d, min_periods=2).std().fillna(0.0)

def ts_rank(series: pd.Series, d: int = 5) -> pd.Series:
    return series.rolling(d, min_periods=2).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) > 0 else 0.5,
        raw=False
    ).fillna(0.5)

PRIMITIVE_FUNCTIONS = {
    "add": (lambda a, b: a + b, 2),
    "sub": (lambda a, b: a - b, 2),
    "mul": (lambda a, b: a * b, 2),
    "div": (lambda a, b: a / (b.abs() + 1e-6), 2),
    "abs": (lambda a: a.abs(), 1),
    "log": (lambda a: np.log(a.abs() + 1e-6), 1),
    "sqrt": (lambda a: np.sqrt(a.abs()), 1),
    "ts_mom": (lambda a: ts_mom(a, 5), 1),
    "ts_std": (lambda a: ts_std(a, 5), 1),
    "ts_rank": (lambda a: ts_rank(a, 5), 1),
}

class ExpressionNode:
    def __init__(self, op_name: str, children: Optional[List['ExpressionNode']] = None, feature_name: Optional[str] = None):
        self.op_name = op_name
        self.children = children if children is not None else []
        self.feature_name = feature_name  # Set if terminal feature leaf

    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def evaluate(self, df: pd.DataFrame) -> pd.Series:
        if self.is_leaf():
            if self.feature_name in df.columns:
                return df[self.feature_name]
            return pd.Series(0.0, index=df.index)
        
        func, arity = PRIMITIVE_FUNCTIONS[self.op_name]
        child_evals = [child.evaluate(df) for child in self.children]
        if arity == 1:
            return func(child_evals[0])
        elif arity == 2:
            return func(child_evals[0], child_evals[1])
        return pd.Series(0.0, index=df.index)

    def to_string(self) -> str:
        if self.is_leaf():
            return self.feature_name or "0.0"
        if len(self.children) == 1:
            return f"{self.op_name}({self.children[0].to_string()})"
        elif len(self.children) == 2:
            return f"({self.children[0].to_string()} {self.op_name} {self.children[1].to_string()})"
        return "0.0"

class FormulaicAlphaCandidate:
    def __init__(self, root: ExpressionNode):
        self.root = root
        self.expression = root.to_string()
        self.rank_ic: float = 0.0
        self.ic_ir: float = 0.0
        self.fitness: float = -999.0

class SymbolicAlphaMiner:
    def __init__(self, population_size: int = 50, generations: int = 5, max_depth: int = 3):
        self.population_size = population_size
        self.generations = generations
        self.max_depth = max_depth
        self.population: List[FormulaicAlphaCandidate] = []
        self.best_candidate: Optional[FormulaicAlphaCandidate] = None

    def _generate_random_node(self, depth: int, feature_cols: List[str]) -> ExpressionNode:
        if depth >= self.max_depth or (depth > 1 and random.random() < 0.4):
            feat = random.choice(feature_cols)
            return ExpressionNode(op_name="leaf", feature_name=feat)
        
        op_name = random.choice(list(PRIMITIVE_FUNCTIONS.keys()))
        _, arity = PRIMITIVE_FUNCTIONS[op_name]
        children = [self._generate_random_node(depth + 1, feature_cols) for _ in range(arity)]
        return ExpressionNode(op_name=op_name, children=children)

    def _evaluate_candidate(self, candidate: FormulaicAlphaCandidate, df: pd.DataFrame, target_col: str) -> FormulaicAlphaCandidate:
        try:
            signal = candidate.root.evaluate(df).fillna(0.0)
            target = df[target_col].fillna(0.0)

            if signal.std() < 1e-6:
                candidate.fitness = -999.0
                return candidate

            # Calculate Spearman Rank IC
            if "date" in df.columns:
                daily_ics = []
                for _, group in df.groupby("date"):
                    if len(group) > 2 and group[target_col].std() > 1e-6:
                        s_grp = candidate.root.evaluate(group).fillna(0.0)
                        ic = s_grp.corr(group[target_col], method="spearman")
                        if not np.isnan(ic):
                            daily_ics.append(ic)
                if len(daily_ics) > 0:
                    candidate.rank_ic = float(np.mean(daily_ics))
                    std_ic = float(np.std(daily_ics))
                    candidate.ic_ir = candidate.rank_ic / (std_ic + 1e-6) * np.sqrt(252)
                else:
                    candidate.rank_ic = float(signal.corr(target, method="spearman"))
                    candidate.ic_ir = candidate.rank_ic * 2.0
            else:
                ic = signal.corr(target, method="spearman")
                candidate.rank_ic = float(ic) if not np.isnan(ic) else 0.0
                candidate.ic_ir = candidate.rank_ic * 2.0

            candidate.fitness = abs(candidate.rank_ic)
        except Exception:
            candidate.fitness = -999.0
        return candidate

    def fit(self, df: pd.DataFrame, feature_cols: List[str], target_col: str = "future_ret_1d_pct") -> FormulaicAlphaCandidate:
        """
        Runs Genetic Algorithm to mine top formulaic alpha candidate.
        """
        random.seed(42)
        np.random.seed(42)

        # 1. Initialize Population
        self.population = []
        for _ in range(self.population_size):
            node = self._generate_random_node(depth=1, feature_cols=feature_cols)
            cand = FormulaicAlphaCandidate(node)
            self.population.append(cand)

        # 2. Evolve Generations
        for gen in range(self.generations):
            for cand in self.population:
                self._evaluate_candidate(cand, df, target_col)

            self.population.sort(key=lambda x: x.fitness, reverse=True)
            if self.best_candidate is None or self.population[0].fitness > self.best_candidate.fitness:
                self.best_candidate = self.population[0]

            # Elitism: retain top 20%
            n_retain = max(2, int(self.population_size * 0.2))
            new_pop = self.population[:n_retain]

            # Fill rest with random mutations
            while len(new_pop) < self.population_size:
                node = self._generate_random_node(depth=1, feature_cols=feature_cols)
                new_pop.append(FormulaicAlphaCandidate(node))

            self.population = new_pop

        # Final evaluation
        if self.best_candidate:
            self._evaluate_candidate(self.best_candidate, df, target_col)
        return self.best_candidate or self.population[0]

if __name__ == "__main__":
    print("Testing SymbolicAlphaMiner...")
    np.random.seed(42)
    n_samples = 150
    df_test = pd.DataFrame({
        "date": pd.date_range("2026-08-01", periods=15, freq="D").repeat(10),
        "feature_rvol": np.random.uniform(0.5, 3.0, n_samples),
        "feature_vwap_dist_pct": np.random.normal(0, 1.5, n_samples),
        "feature_mom_3_pct": np.random.normal(0, 2.0, n_samples),
        "future_ret_1d_pct": np.random.normal(0.1, 1.2, n_samples)
    })
    
    miner = SymbolicAlphaMiner(population_size=30, generations=3)
    best_alpha = miner.fit(df_test, feature_cols=["feature_rvol", "feature_vwap_dist_pct", "feature_mom_3_pct"])
    
    print("=========================================================================")
    print("SYMBOLIC ALPHA MINER BEST FORMULAIC CANDIDATE")
    print("=========================================================================")
    print(f"  Formula Expression : {best_alpha.expression}")
    print(f"  Rank IC            : {best_alpha.rank_ic:.4f}")
    print(f"  IC-IR (Annualized) : {best_alpha.ic_ir:.4f}")
    print("=========================================================================")
