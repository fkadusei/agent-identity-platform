"""OAuth 2.0 token exchange (RFC 8693).

Two shapes are supported:

* **Client-assertion** (a workload proving identity with its SVID): pass
  ``client_assertion``. This is how the agent authenticates without a secret.
* **Client-secret** (a service exchanging for a downstream audience): pass
  ``client_secret``. Used by tool servers for their own hop.

The caller is responsible for *not forwarding* the token it received: every hop
should call this to obtain a token scoped to the next audience.
"""
from __future__ import annotations

from typing import Any

import httpx

from .audit import audit
from .config import Settings
from .errors import ExchangeError

TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
JWT_BEARER_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


class TokenExchanger:
    def __init__(
        self,
        settings: Settings,
        client: Any | None = None,
        timeout: float = 15.0,
    ):
        self._settings = settings
        self._client = client
        self._timeout = timeout

    def _post(self, data: dict) -> Any:
        if self._client is not None:
            return self._client.post(self._settings.token_endpoint, data=data, timeout=self._timeout)
        with httpx.Client() as client:
            return client.post(self._settings.token_endpoint, data=data, timeout=self._timeout)

    def exchange(
        self,
        *,
        subject_token: str,
        client_id: str,
        client_assertion: str | None = None,
        client_secret: str | None = None,
        audience: str | None = None,
        scope: str | None = None,
        extra: dict | None = None,
    ) -> str:
        """Exchange ``subject_token`` for a new access token.

        Returns the new access token. Raises :class:`ExchangeError` on failure.
        """
        if not client_assertion and not client_secret:
            raise ExchangeError("one of client_assertion or client_secret is required")

        data: dict[str, str] = {
            "grant_type": TOKEN_EXCHANGE_GRANT,
            "client_id": client_id,
            "subject_token": subject_token,
            "subject_token_type": ACCESS_TOKEN_TYPE,
            "requested_token_type": ACCESS_TOKEN_TYPE,
        }
        if client_assertion:
            data["client_assertion_type"] = JWT_BEARER_ASSERTION_TYPE
            data["client_assertion"] = client_assertion
        if client_secret:
            data["client_secret"] = client_secret
        if audience:
            data["audience"] = audience
        if scope:
            data["scope"] = scope
        if extra:
            data.update({k: str(v) for k, v in extra.items()})

        resp = self._post(data)
        if getattr(resp, "status_code", 0) != 200:
            body = getattr(resp, "text", "")[:300]
            audit("exchange.failed", status=getattr(resp, "status_code", None), body=body)
            raise ExchangeError(f"token exchange failed ({getattr(resp, 'status_code', '?')})")
        try:
            return resp.json()["access_token"]
        except (KeyError, ValueError) as exc:
            raise ExchangeError("token exchange response had no access_token") from exc
