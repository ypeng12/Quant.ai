"""Read-only research display contracts, independent of trading and training.

Only complete local research artifacts are displayed. Hash verification means
the displayed files agree; it does not certify predictive performance.
"""
import hashlib
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Research bundles live beside backend/, including inside the Space image.
REPOSITORY_ROOT = ROOT.parent
SUMMARY_PATH = Path(os.getenv("QUANT_RESEARCH_SUMMARY", str(REPOSITORY_ROOT / "reports/quant_research_20260913/research_summary.json")))


def _finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite research metric")
    if isinstance(value, dict):
        for item in value.values():
            _finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            _finite_tree(item)


def _file_hash(path):
    from app.research.artifacts import published_input_path
    path = Path(path)
    if 'reports' in path.parts:
        path = published_input_path(path, REPOSITORY_ROOT)
    elif not path.is_absolute():
        path = ROOT / path
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_research():
    try:
        data = json.loads(SUMMARY_PATH.read_text())
        _finite_tree(data)
        if data.get("schema_version") != 1 or data.get("status") != "complete":
            raise ValueError("Research run is incomplete")
        if not data["selection_cutoff"] < data["evaluation_start"] <= data["evaluation_end"]:
            raise ValueError("Selection dates overlap evaluation dates")
        if data["starting_equity"] <= 0 or data["cost_bps_per_side"] < 0:
            raise ValueError("Invalid capital or cost assumption")
        if data["trial_count"] != len(data["trials"]) or not data["trials"]:
            raise ValueError("Trial registry is incomplete")
        if (not data["data_hashes"] or set(data["data_hashes"]) != set(data["data_paths"])
                or set(data["data_hashes"]) != set(data["per_ticker"])):
            raise ValueError("Data provenance is incomplete")
        for ticker, expected in data["data_hashes"].items():
            if _file_hash(data["data_paths"][ticker]) != expected:
                raise ValueError("Research source data changed")
        if _file_hash(data["selected_policy_path"]) != data["selected_policy_sha256"]:
            raise ValueError("Selected policy changed")
        for source, expected in data.get("source_hashes", {}).items():
            if _file_hash(source) != expected:
                raise ValueError("Research implementation changed")
        for window in ("two_week", "recent_week"):
            for key in ("net_pnl", "net_return", "max_drawdown", "costs"):
                if not isinstance(data["portfolio"][window][key], (float, int)):
                    raise ValueError("Missing measured portfolio metric")
        selected = [trial for trial in data["trials"] if trial.get("selected")]
        if len(selected) != 1 or selected[0]["spec"] != data["selected_spec"]:
            raise ValueError("Selected candidate disagrees with registry")
        return data, None
    except FileNotFoundError:
        return None, "研究产物或对应行情/模型文件尚未生成。"
    except (OSError, ValueError, KeyError, TypeError):
        return None, "研究产物不完整、日期不一致或文件哈希已变化，请重新生成并核对。"


def _unavailable_provenance(reason=None):
    return {
        "source": None,
        "as_of": None,
        "model_version": None,
        "verification_status": "unverified",
        "reason": reason or "尚未接入可核验的数据集、模型版本和样本外评估产物。",
    }


def get_ml_lab_payload(ticker: str = "MSTR") -> dict:
    payload = {
        "success": True,
        "status": "unavailable",
        "ticker": ticker.strip().upper(),
        "data_provenance": _unavailable_provenance(),
        "dataset_rows": None,
        "scatter_points": [],
        "pca_factors": [],
        "regime_clusters": [],
        "loss_mse_final": None,
        "platt_scale_slope": None,
        "platt_scale_intercept": None,
        "training_status": "unavailable",
    }
    research, error = _read_research()
    if research is not None and payload["ticker"] in research.get("per_ticker", {}):
        payload.update(status="complete", research=research, training_status="completed_offline")
        payload["data_provenance"] = {
            "source": "local_retrospective_policy_research",
            "as_of": research["generated_at"],
            "model_version": research["selected_spec"]["name"],
            "verification_status": "artifact_verified",
            "reason": "已核对研究产物、模型和行情文件哈希。收益来自历史逐日模拟；下方教学图形仍不是训练成果。",
        }
    else:
        payload["data_provenance"] = _unavailable_provenance(error or "该股票没有对应研究结果。")
    return payload


def get_latest_research_payload() -> dict:
    payload = {
        "success": True,
        "status": "unavailable",
        "data_provenance": _unavailable_provenance(),
        "results": [],
        "drift_audit": [],
        "trading_dates": None,
        "universe_size": None,
        "cost_bps": None,
    }
    research, error = _read_research()
    if research is not None:
        payload.update(status="complete", research=research,
                       universe_size=len(research["data_hashes"]), cost_bps=research["cost_bps_per_side"])
        payload["data_provenance"] = {
            "source": "local_retrospective_policy_research", "as_of": research["generated_at"],
            "model_version": research["selected_spec"]["name"], "verification_status": "artifact_verified",
            "reason": "本地研究产物与模型/行情哈希一致；不代表已经通过未来实盘验证。",
        }
    else:
        payload["data_provenance"] = _unavailable_provenance(error)
    return payload
