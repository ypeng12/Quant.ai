import importlib.util
from pathlib import Path

from app.market_data.history import credentials


def test_environment_credentials_skip_cloud_placeholder(monkeypatch):
    monkeypatch.delenv("ALPACA_ENV_FILE", raising=False)
    monkeypatch.setenv("ALPACA_API_KEY", "env-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "env-secret")
    monkeypatch.setattr("app.market_data.history.dotenv_values", lambda _: (_ for _ in ()).throw(AssertionError("file should not be read")))
    assert credentials() == ("env-key", "env-secret")


def test_explicit_credential_file_does_not_mix_accounts(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("ALPACA_API_KEY=file-key\nALPACA_SECRET_KEY=file-secret\n")
    monkeypatch.setenv("ALPACA_API_KEY", "other-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "other-secret")
    assert credentials(path) == ("file-key", "file-secret")


def test_launch_agent_contains_no_credentials_or_trading_entrypoint(tmp_path):
    path = Path(__file__).resolve().parents[2] / "scripts/manage_l1_capture.py"
    spec = importlib.util.spec_from_file_location("manage_l1_capture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = module.service_config("/usr/bin/python3", tmp_path / "runtime", tmp_path / "events",
                                   tmp_path / ".env", ["SNDK"], "iex", tmp_path / "logs")
    assert config["ProgramArguments"][-2:] == ["--env-file", str(tmp_path / ".env")]
    assert config["EnvironmentVariables"] == {"PYTHONUNBUFFERED": "1"}
    assert "live_runner" not in repr(config)
    assert all("broker" not in filename for filename in module.SOURCES)
