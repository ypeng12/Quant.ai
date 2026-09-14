"""Account display works independently of the order runner and keeps account identity."""
from types import SimpleNamespace

from app.broker import account_view as module


def test_configured_account_failure_does_not_fall_back_to_another_account(monkeypatch):
    monkeypatch.setenv("ALPACA_ACCOUNT_API_KEY", "display-test")
    monkeypatch.delenv("ALPACA_ACCOUNT_SECRET_KEY", raising=False)
    assert module.read_configured_account_view("account")["success"] is False
    monkeypatch.delenv("ALPACA_ACCOUNT_API_KEY", raising=False)
    assert module.read_configured_account_view("account") is None


def test_reads_are_cached_and_fractional_positions_are_preserved(monkeypatch):
    calls = []
    position = SimpleNamespace(symbol="TEST", qty="-0.25", avg_entry_price="100",
                               market_value="-26", current_price="104", unrealized_pl="-1",
                               unrealized_plpc="-0.04")
    class Adapter:
        def __init__(self, *args):
            self.client = SimpleNamespace(get_all_positions=lambda: [position])
        def get_account_summary(self):
            calls.append("account")
            return dict(success=True, equity=1234.56, cash=1234.56, buying_power=2000, is_paper=True)
    monkeypatch.setattr(module, "AlpacaAdapter", Adapter)
    view = module.AccountView("test", "test", "https://paper-api.alpaca.markets")
    assert view.read("account")["equity"] == 1234.56
    assert view.read("account")["is_paper"] is True
    assert calls == ["account"]
    assert view.read("positions")["positions"][0]["shares"] == -0.25


def test_account_display_rejects_unrecognized_endpoint_before_connecting(monkeypatch):
    monkeypatch.setenv("ALPACA_ACCOUNT_API_KEY", "test")
    monkeypatch.setenv("ALPACA_ACCOUNT_SECRET_KEY", "test")
    monkeypatch.setenv("ALPACA_ACCOUNT_BASE_URL", "https://unrelated.invalid")
    monkeypatch.setattr(module, "_view", lambda *args: (_ for _ in ()).throw(AssertionError("Unexpected connection")))
    assert module.read_configured_account_view("account")["success"] is False
