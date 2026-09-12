"""Token exchange: request shape, and error handling."""
from __future__ import annotations

import pytest

from agentnhi import ExchangeError, Settings, TokenExchanger
from tests.constants import ISSUER
from tests.fakes import FakeClient, FakeResponse


def settings() -> Settings:
    return Settings(keycloak_issuer=ISSUER)


def test_exchange_with_client_assertion():
    client = FakeClient(FakeResponse(200, {"access_token": "new-token"}))
    token = TokenExchanger(settings(), client=client).exchange(
        subject_token="user-token", client_id="spiffe://agent", client_assertion="svid"
    )
    assert token == "new-token"
    call = client.calls[0]
    assert call["url"].endswith("/protocol/openid-connect/token")
    data = call["data"]
    assert data["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert data["subject_token"] == "user-token"
    assert data["client_assertion"] == "svid"
    assert data["client_assertion_type"].endswith("jwt-bearer")
    assert "client_secret" not in data


def test_exchange_with_client_secret_and_audience():
    client = FakeClient(FakeResponse(200, {"access_token": "downstream"}))
    token = TokenExchanger(settings(), client=client).exchange(
        subject_token="inbound",
        client_id="tool-server",
        client_secret="server-secret",
        audience="customer-api",
    )
    assert token == "downstream"
    data = client.calls[0]["data"]
    assert data["client_secret"] == "server-secret"
    assert data["audience"] == "customer-api"


def test_missing_credentials_is_an_error():
    client = FakeClient(FakeResponse(200, {"access_token": "x"}))
    with pytest.raises(ExchangeError, match="client_assertion or client_secret"):
        TokenExchanger(settings(), client=client).exchange(
            subject_token="t", client_id="c"
        )


def test_error_status_raises_exchange_error():
    client = FakeClient(FakeResponse(400, text="invalid_client"))
    with pytest.raises(ExchangeError, match="failed"):
        TokenExchanger(settings(), client=client).exchange(
            subject_token="t", client_id="c", client_secret="s"
        )


def test_missing_access_token_raises():
    client = FakeClient(FakeResponse(200, {"token_type": "Bearer"}))
    with pytest.raises(ExchangeError, match="access_token"):
        TokenExchanger(settings(), client=client).exchange(
            subject_token="t", client_id="c", client_secret="s"
        )
