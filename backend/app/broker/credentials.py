"""Resolve one complete broker credential family without mixing accounts.

Account-display credentials may supply the user's paper runner fallback. A live
account display is never implicitly promoted into an automatic trading login.
This module performs no network requests and never includes secrets in reprs.
"""
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit


PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
LIVE_ENDPOINT = "https://api.alpaca.markets"


class CredentialConfigurationError(ValueError):
    pass


def configured(value) -> bool:
    text = str(value or "").strip()
    return bool(text) and "your_" not in text.lower() and "placeholder" not in text.lower()


def normalize_endpoint(value: str) -> str:
    endpoint = str(value or PAPER_ENDPOINT).strip().rstrip("/")
    parts = urlsplit(endpoint)
    if (parts.scheme != "https" or parts.username or parts.password or parts.query
            or parts.fragment or parts.path not in ("", "/v2")
            or parts.netloc not in ("paper-api.alpaca.markets", "api.alpaca.markets")):
        raise CredentialConfigurationError("Expected an official Alpaca trading endpoint")
    return f"https://{parts.netloc}"


@dataclass(frozen=True)
class BrokerCredentials:
    key: str = field(repr=False)
    secret: str = field(repr=False)
    endpoint: str
    source: str

    @property
    def is_paper(self):
        return self.endpoint == PAPER_ENDPOINT

    def public_metadata(self):
        return {"credential_source": self.source, "endpoint": self.endpoint,
                "is_paper": self.is_paper}


def resolve_trading_credentials(env: Mapping[str, str]) -> BrokerCredentials | None:
    # Preserve the historical APCA override, but require both values to belong
    # to that family. Explicit partial configuration is an error, not permission
    # to take another account's secret or silently choose a different account.
    families = (
        ("APCA", "APCA_API_KEY_ID", ("APCA_API_SECRET_KEY",), "APCA_API_BASE_URL"),
        ("ALPACA", "ALPACA_API_KEY", ("ALPACA_SECRET_KEY", "ALPACA_API_SECRET"), "ALPACA_BASE_URL"),
        ("ALPACA_ACCOUNT_PAPER_FALLBACK", "ALPACA_ACCOUNT_API_KEY", ("ALPACA_ACCOUNT_SECRET_KEY",), "ALPACA_ACCOUNT_BASE_URL"),
    )
    for source, key_name, secret_names, endpoint_name in families:
        key = env.get(key_name, "")
        secret = next((env.get(name, "") for name in secret_names if configured(env.get(name))), "")
        if not configured(key) and not configured(secret):
            continue
        if not configured(key) or not configured(secret):
            raise CredentialConfigurationError(f"Incomplete {source} credential pair")
        endpoint = normalize_endpoint(env.get(endpoint_name) or PAPER_ENDPOINT)
        if source == "ALPACA_ACCOUNT_PAPER_FALLBACK" and endpoint != PAPER_ENDPOINT:
            raise CredentialConfigurationError("Live account-display credentials require explicit trading configuration")
        return BrokerCredentials(str(key).strip(), str(secret).strip(), endpoint, source)
    return None
