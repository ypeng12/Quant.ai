"""Display contract checks without importing the API's live trading runner."""

import ast
import json
import hashlib
from pathlib import Path
import sys
import unittest
import tempfile
import types
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.research_lab_data import get_latest_research_payload, get_ml_lab_payload
from app import research_lab_data


class ResearchLabDataTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.summary = self.directory / "research_summary.json"
        patcher = patch.object(research_lab_data, "SUMMARY_PATH", self.summary)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _complete_artifact(self):
        bars = self.directory / "SNDK.parquet"
        bars.write_bytes(b"fixture source data")
        policy = self.directory / "policy.json"
        policy.write_text('{"spec": {"name": "fixture"}}')
        metrics = {"net_pnl": -25.0, "net_return": -0.00025, "max_drawdown": -0.01, "costs": 12.0}
        data = {
            "schema_version": 1, "status": "complete", "generated_at": "2026-09-13T12:00:00Z",
            "selection_cutoff": "2026-08-28", "evaluation_start": "2026-08-31", "evaluation_end": "2026-09-11",
            "starting_equity": 100000, "cost_bps_per_side": 2, "trial_count": 1,
            "selected_spec": {"name": "fixture"},
            "trials": [{"selected": True, "spec": {"name": "fixture"}}],
            "data_paths": {"SNDK": str(bars)}, "data_hashes": {"SNDK": hashlib.sha256(bars.read_bytes()).hexdigest()},
            "selected_policy_path": str(policy), "selected_policy_sha256": hashlib.sha256(policy.read_bytes()).hexdigest(),
            "portfolio": {"two_week": metrics, "recent_week": metrics},
            "per_ticker": {"SNDK": {"two_week": metrics, "recent_week": metrics}},
        }
        self.summary.write_text(json.dumps(data))
        return data, bars

    def test_complete_research_displays_losses_without_inventing_probabilities(self):
        self._complete_artifact()
        data = get_ml_lab_payload("SNDK")
        self.assertEqual(data["status"], "complete")
        self.assertEqual(data["data_provenance"]["verification_status"], "artifact_verified")
        self.assertEqual(data["research"]["portfolio"]["two_week"]["net_pnl"], -25.0)
        self.assertIsNone(data["loss_mse_final"])
        self.assertEqual(get_latest_research_payload()["status"], "complete")

    def test_changed_data_or_overlapping_selection_is_unavailable(self):
        _, bars = self._complete_artifact()
        bars.write_bytes(b"revised data")
        self.assertEqual(get_latest_research_payload()["status"], "unavailable")
        data, _ = self._complete_artifact()
        data["selection_cutoff"] = data["evaluation_end"]
        self.summary.write_text(json.dumps(data))
        self.assertEqual(get_latest_research_payload()["status"], "unavailable")

    def test_missing_metrics_are_not_fabricated_for_any_ticker(self):
        for ticker in ("MSTR", "TSLA", "NVDA", "SNDK"):
            with self.subTest(ticker=ticker):
                data = get_ml_lab_payload(f" {ticker.lower()} ")
                self.assertEqual(data["ticker"], ticker)
                self.assertEqual(data["status"], "unavailable")
                self.assertEqual(data["data_provenance"]["verification_status"], "unverified")
                for key in ("scatter_points", "pca_factors", "regime_clusters"):
                    self.assertEqual(data[key], [])
                for key in ("dataset_rows", "loss_mse_final", "platt_scale_slope", "platt_scale_intercept"):
                    self.assertIsNone(data[key])
                self.assertIsNone(data["data_provenance"]["source"])
                self.assertIsNone(data["data_provenance"]["as_of"])
                self.assertEqual(data["training_status"], "unavailable")
                json.dumps(data, allow_nan=False)

    def test_research_endpoint_has_explainable_empty_results(self):
        data = get_latest_research_payload()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "unavailable")
        self.assertEqual(data["results"], [])
        self.assertEqual(data["drift_audit"], [])
        self.assertTrue(data["data_provenance"]["reason"])
        for key in ("trading_dates", "universe_size", "cost_bps"):
            self.assertIsNone(data[key])
        json.dumps(data, allow_nan=False)

    def test_api_routes_forward_contracts_without_starting_api(self):
        tree = ast.parse((BACKEND / "main_api.py").read_text())
        functions = {
            node.name: node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"get_ml_lab_data", "get_latest_research_results"}
        }
        expected_paths = {
            "get_ml_lab_data": "/api/ml/lab_data",
            "get_latest_research_results": "/api/research/latest_results",
        }
        self.assertEqual(set(functions), set(expected_paths))
        for name, node in functions.items():
            self.assertEqual(ast.literal_eval(node.decorator_list[0].args[0]), expected_paths[name])
            node.decorator_list = []
        namespace = {}
        exec(compile(ast.Module(body=list(functions.values()), type_ignores=[]), "lab_routes", "exec"), namespace)
        self.assertEqual(namespace["get_ml_lab_data"](" sndk "), get_ml_lab_payload("SNDK"))
        self.assertEqual(namespace["get_latest_research_results"](), get_latest_research_payload())

    def test_broker_failure_and_retired_comparison_never_return_sample_money(self):
        tree = ast.parse((BACKEND / "main_api.py").read_text())
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"get_broker_account", "get_broker_positions", "get_trade_comparison_data"}]
        for node in nodes:
            node.decorator_list = []
        class MockAdapter:
            pass
        module = types.ModuleType("app.broker.mock_adapter")
        module.MockAlpacaAdapter = MockAdapter
        runner = types.SimpleNamespace(adapter=MockAdapter())
        namespace = {"live_runner": runner}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "broker_display_routes", "exec"), namespace)
        with patch.dict(sys.modules, {"app.broker.mock_adapter": module}):
            for name in ("get_broker_account", "get_broker_positions", "get_trade_comparison_data"):
                result = namespace[name]()
                self.assertFalse(result["success"])
                self.assertEqual(result["status"], "unavailable")
                self.assertNotIn("equity", result)
            runner.adapter = object()
            runner.get_cached_account_summary = lambda: {"success": True, "equity": 123.45}
            runner.get_cached_open_positions = lambda: []
            self.assertEqual(namespace["get_broker_account"]()["equity"], 123.45)
            self.assertEqual(namespace["get_broker_positions"]()["positions"], [])
            runner.get_cached_account_summary = lambda: {"success": False}
            runner.get_cached_open_positions = lambda: None
            self.assertFalse(namespace["get_broker_account"]()["success"])
            self.assertFalse(namespace["get_broker_positions"]()["success"])


if __name__ == "__main__":
    unittest.main()
