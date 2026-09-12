"""Shared test fixtures: a throwaway RSA keypair and token factory.

Tests never touch a live cluster or authorization server — the signing key is
injected, so verification logic is exercised in isolation.
"""
from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.constants import AGENT, AUDIENCE, ISSUER


@pytest.fixture(scope="session")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private_pem, key.public_key()


@pytest.fixture
def make_token(keypair):
    private_pem, _ = keypair

    def _make(**overrides):
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "user-123",
            "preferred_username": "alice",
            "azp": AGENT,
            "iat": now,
            "exp": now + 300,
            "jti": "unique-id",
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, private_pem, algorithm="RS256")

    return _make


@pytest.fixture
def resolver(keypair):
    """A signing-key resolver that returns the trusted public key."""
    _, public_key = keypair
    return lambda _token: public_key
