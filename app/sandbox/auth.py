"""Verify a caller's on-behalf-of token (S28).

When `SANDBOX_AUDIENCE` is set, a request must present a bearer token audienced to
this service, minted by Keycloak in the tool server's RFC 8693 exchange. Its
`tenant` and `sub` are then the caller's identity — so the vendor sees the *user*,
not just an `X-Tenant` header.

With no audience configured (a local run, the test suite) verification is skipped
and the caller uses `X-Tenant` as before.
"""
from __future__ import annotations

import os

import jwt
from jwt import PyJWKClient

_jwks: PyJWKClient | None = None


def enabled() -> bool:
    return bool(os.environ.get("SANDBOX_AUDIENCE", "").strip())


def _issuer() -> str:
    return os.environ.get("KC_ISSUER", "").rstrip("/")


def _client() -> PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(f"{_issuer()}/protocol/openid-connect/certs")
    return _jwks


def verify(authorization: str | None) -> dict:
    """Return the token's claims, or raise `jwt.PyJWTError`/`ValueError`."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise ValueError("missing bearer token")
    key = _client().get_signing_key_from_jwt(token).key
    return jwt.decode(
        token,
        key,
        algorithms=["RS256", "ES256"],
        audience=os.environ.get("SANDBOX_AUDIENCE", "").strip(),
        issuer=_issuer(),
    )
