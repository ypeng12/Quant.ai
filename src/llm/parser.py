import re
from typing import Dict, Any
from src.data.manifest import ExperimentManifest, create_manifest


class LLMHypothesisParser:
    """
    Typed LLM Guardrail Parser:
    Converts natural language user research prompts (e.g. "Test whether 20-day momentum predicts 5-day returns among sector ETFs at 5 bps cost")
    into validated, deterministic Pydantic ExperimentManifest configurations.
    """

    @staticmethod
    def parse_hypothesis(prompt: str) -> ExperimentManifest:
        prompt_lower = prompt.lower()

        # Extract lookback days
        lookback_match = re.search(r"(\d+)[ -]?day momentum", prompt_lower)
        lookback_days = int(lookback_match.group(1)) if lookback_match else 20

        # Extract holding days
        holding_match = re.search(r"(\d+)[ -]?day return", prompt_lower)
        holding_days = int(holding_match.group(1)) if holding_match else 5

        # Extract transaction cost bps
        cost_match = re.search(r"(\d+)[ -]?bps", prompt_lower)
        cost_bps = float(cost_match.group(1)) if cost_match else 5.0

        # Universe defaults
        universe = [
            "SPY", "QQQ", "IWM", "MDY",
            "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLC", "XLRE",
            "SMH", "XBI", "KRE", "ITB",
            "TLT", "IEF", "SHY", "LQD", "HYG", "TIP",
            "GLD", "SLV", "USO", "DBA",
            "EEM", "EFA", "FXI", "EWJ",
            "MTUM", "USMV", "QUAL", "IWD", "IWF"
        ]

        manifest = create_manifest(
            asset_universe=universe,
            lookback_days=lookback_days,
            holding_days=holding_days,
            transaction_cost_bps=cost_bps,
            feature_config={
                "raw_mom": True,
                "sortino_mom": "sortino" in prompt_lower or "volatility" in prompt_lower,
                "residual_mom": "residual" in prompt_lower,
                "volume_z": "volume" in prompt_lower,
            },
            model_config={
                "type": "lightgbm" if "tree" in prompt_lower or "lightgbm" in prompt_lower else "ridge",
                "max_depth": 3,
                "learning_rate": 0.01
            }
        )

        return manifest
