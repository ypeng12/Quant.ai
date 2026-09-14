import pytest
from types import SimpleNamespace
from test_research_execution import runner_type

from app.broker.credentials import CredentialConfigurationError, resolve_trading_credentials


def account(**extra):
    return dict(ALPACA_ACCOUNT_API_KEY="account-key", ALPACA_ACCOUNT_SECRET_KEY="account-secret", **extra)


def test_paper_display_fallback_uses_complete_pair_and_its_endpoint():
    credentials = resolve_trading_credentials(account(ALPACA_ACCOUNT_BASE_URL="https://paper-api.alpaca.markets/v2"))
    assert (credentials.key, credentials.secret) == ("account-key", "account-secret")
    assert credentials.is_paper and credentials.source == "ALPACA_ACCOUNT_PAPER_FALLBACK"
    assert "account-key" not in repr(credentials) and "account-secret" not in repr(credentials)
    assert "key" not in credentials.public_metadata()


def test_standard_credentials_take_precedence_over_display():
    credentials = resolve_trading_credentials(dict(account(), ALPACA_API_KEY="trading-key", ALPACA_SECRET_KEY="trading-secret"))
    assert credentials.source == "ALPACA" and credentials.key == "trading-key"


def test_legacy_apca_override_remains_a_separate_pair():
    credentials = resolve_trading_credentials(dict(account(), APCA_API_KEY_ID="legacy-key", APCA_API_SECRET_KEY="legacy-secret"))
    assert credentials.source == "APCA" and credentials.secret == "legacy-secret"


@pytest.mark.parametrize("extra", [{"ALPACA_API_KEY": "key-only"}, {"ALPACA_SECRET_KEY": "secret-only"},
                                  {"APCA_API_KEY_ID": "key-only", "ALPACA_SECRET_KEY": "different-secret"}])
def test_partial_configuration_never_mixes_or_switches_accounts(extra):
    with pytest.raises(CredentialConfigurationError, match="Incomplete"):
        resolve_trading_credentials(dict(account(), **extra))


def test_placeholders_are_missing_and_legacy_secret_alias_is_supported():
    assert resolve_trading_credentials({"ALPACA_API_KEY": "your_api_key", "ALPACA_SECRET_KEY": "placeholder"}) is None
    credentials = resolve_trading_credentials({"ALPACA_API_KEY": "key", "ALPACA_API_SECRET": "secret"})
    assert credentials.source == "ALPACA"


@pytest.mark.parametrize("endpoint", ["https://api.alpaca.markets", "https://paper-api.alpaca.markets.bad.example",
                                    "http://paper-api.alpaca.markets", "https://paper-api.alpaca.markets?secret=value"])
def test_display_fallback_cannot_activate_live_trading_or_use_unknown_destination(endpoint):
    with pytest.raises(CredentialConfigurationError):
        resolve_trading_credentials(account(ALPACA_ACCOUNT_BASE_URL=endpoint))


def test_explicit_live_credentials_still_reach_existing_runner_authorization_check():
    credentials = resolve_trading_credentials({"ALPACA_API_KEY": "key", "ALPACA_SECRET_KEY": "secret", "ALPACA_BASE_URL": "https://api.alpaca.markets/v2"})
    assert not credentials.is_paper and credentials.source == "ALPACA"


def clear_credentials(monkeypatch):
    import os
    for key in list(os.environ):
        if key.startswith(("ALPACA_", "APCA_")):
            monkeypatch.delenv(key)


def test_runner_connects_to_paper_display_pair_without_starting_loop(runner_type, monkeypatch):
    clear_credentials(monkeypatch)
    for key, value in account().items():
        monkeypatch.setenv(key, value)
    calls = []
    def adapter(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(get_account_summary=lambda: {"success": True})
    monkeypatch.setitem(runner_type.init_alpaca_adapter.__globals__, "AlpacaAdapter", adapter)
    runner = runner_type.__new__(runner_type)
    runner.init_alpaca_adapter()
    assert runner._broker_connection["connected"]
    assert runner._broker_connection["credential_source"] == "ALPACA_ACCOUNT_PAPER_FALLBACK"
    assert calls[0]["api_secret"] == "account-secret"


def test_connection_failure_is_visible_and_redacts_exception_contents(runner_type, monkeypatch):
    clear_credentials(monkeypatch)
    for key, value in account().items():
        monkeypatch.setenv(key, value)
    def fail(**kwargs):
        raise RuntimeError("sensitive-secret-value")
    monkeypatch.setitem(runner_type.init_alpaca_adapter.__globals__, "AlpacaAdapter", fail)
    runner = runner_type.__new__(runner_type)
    runner.init_alpaca_adapter()
    runner._run_quant_policy_cycle()
    assert not runner._broker_connection["connected"]
    assert runner._quant_status["state"] == "unavailable"
    assert "sensitive-secret-value" not in str(runner._broker_connection)
