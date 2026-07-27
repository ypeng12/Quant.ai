import os
import json
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class ExperimentManifest(BaseModel):
    """
    Typed Manifest tracking all dataset, parameter, model, and git metadata
    to ensure 100% reproducible out-of-sample experiment runs.
    """
    experiment_id: str = Field(default_factory=lambda: f"exp_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    dataset_id: str = "us_etf_daily_v1"
    hf_repo: str = "thecharttruth/etf-data"
    hf_revision: str = "main"
    universe_rule: str = "price > 5 & adv20 > 50m & age >= 252"
    asset_universe: List[str] = Field(default_factory=list)
    start_date: str = "2014-01-01"
    end_date: str = "2023-12-31"
    lookback_days: int = 20
    holding_days: int = 5
    rebalance_freq: str = "weekly"
    transaction_cost_bps: float = 5.0
    slippage_bps: float = 2.0
    cv_scheme: str = "purged_walk_forward_v1"
    embargo_days: int = 5
    random_seed: int = 42
    git_commit: str = "unknown"
    feature_config: Dict[str, Any] = Field(default_factory=dict)
    model_hyperparams: Dict[str, Any] = Field(default_factory=dict)
    metrics_summary: Dict[str, Any] = Field(default_factory=dict)


def get_git_commit_hash() -> str:
    """Retrieve current git commit hash if in a git repository."""
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL).decode("utf-8").strip()
        return commit
    except Exception:
        return "uncommitted_workspace"


def create_manifest(
    asset_universe: List[str],
    dataset_id: str = "us_etf_daily_v1",
    hf_repo: str = "thecharttruth/etf-data",
    hf_revision: str = "main",
    lookback_days: int = 20,
    holding_days: int = 5,
    transaction_cost_bps: float = 5.0,
    random_seed: int = 42,
    feature_config: Optional[Dict[str, Any]] = None,
    model_hyperparams: Optional[Dict[str, Any]] = None,
) -> ExperimentManifest:
    """Helper to instantiate an ExperimentManifest with default git commit resolution."""
    return ExperimentManifest(
        dataset_id=dataset_id,
        hf_repo=hf_repo,
        hf_revision=hf_revision,
        asset_universe=asset_universe,
        lookback_days=lookback_days,
        holding_days=holding_days,
        transaction_cost_bps=transaction_cost_bps,
        random_seed=random_seed,
        git_commit=get_git_commit_hash(),
        feature_config=feature_config or {"residual_mom": True, "sortino_mom": True, "volume_z": True},
        model_hyperparams=model_hyperparams or {"type": "lightgbm", "max_depth": 3, "learning_rate": 0.01},
    )


def save_manifest(manifest: ExperimentManifest, filepath: str) -> str:
    """Save manifest to JSON file."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(manifest.model_dump_json(indent=2))
    return filepath


def load_manifest(filepath: str) -> ExperimentManifest:
    """Load manifest from JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return ExperimentManifest(**data)
