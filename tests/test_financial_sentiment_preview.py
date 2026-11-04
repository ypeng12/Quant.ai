"""The local research preview serves its selected build without trading imports."""
import builtins
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class FinancialSentimentPreviewTests(unittest.TestCase):
    def test_custom_build_preserves_read_only_boundary(self):
        original_import = builtins.__import__
        forbidden = ("main_api", "backend.main_api", "app.broker", "backend.app.broker",
                     "app.config", "backend.app.config", "app.news_monitor")

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if any(name == item or name.startswith(item + ".") for item in forbidden):
                raise AssertionError(f"Preview imported a trading dependency: {name}")
            return original_import(name, globals, locals, fromlist, level)

        script = Path(__file__).resolve().parents[1] / "scripts/serve_financial_sentiment_preview.py"
        with patch("builtins.__import__", side_effect=guarded_import):
            spec = importlib.util.spec_from_file_location("quant_preview_under_test", script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as temporary:
                dist = Path(temporary) / "custom-build"
                (dist / "assets").mkdir(parents=True)
                (dist / "index.html").write_text("<html>Temporary research build</html>", encoding="utf-8")
                (dist / "assets/style.css").write_text("body { color: teal; }", encoding="utf-8")
                with TestClient(module.create_app(dist)) as client:
                    page = client.get("/?tab=financial_sentiment&dist=/unrelated-build")
                    self.assertEqual(page.status_code, 200)
                    self.assertEqual(page.text, "<html>Temporary research build</html>")
                    self.assertIn("connect-src 'self'", page.headers["content-security-policy"])
                    asset = client.get("/assets/style.css")
                    self.assertEqual(asset.status_code, 200)
                    self.assertEqual(asset.text, "body { color: teal; }")
                    capabilities = client.get("/api/runtime/capabilities")
                    self.assertEqual(capabilities.status_code, 200)
                    self.assertEqual(capabilities.json()["mode"], "research_preview")
                    self.assertFalse(capabilities.json()["trading_available"])
                    self.assertFalse(capabilities.json()["account_available"])
                    self.assertFalse(capabilities.json()["market_status_available"])
                    self.assertEqual(client.post("/api/live/start").status_code, 405)
                    self.assertEqual(client.get("/api/broker/account").status_code, 404)


if __name__ == "__main__":
    unittest.main()
