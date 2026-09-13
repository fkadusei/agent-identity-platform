"""IdentityAdmin: the least-privilege Keycloak Admin API client.

Tested against httpx's MockTransport, so no live Keycloak is needed.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.api.identity import IdentityAdmin

TOKEN_URL = "http://kc/realms/agent-platform/protocol/openid-connect/token"
ADMIN = "http://kc/admin/realms/agent-platform"


def _client(handler) -> IdentityAdmin:
    return IdentityAdmin(
        admin_url=ADMIN,
        issuer="http://kc/realms/agent-platform",
        client_id="platform-admin",
        client_secret="s3cret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _token_ok(request: httpx.Request) -> httpx.Response:
    assert str(request.url) == TOKEN_URL
    return httpx.Response(200, json={"access_token": "admin-token"})


def test_create_user_returns_id_from_location():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return _token_ok(request)
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer admin-token"
        return httpx.Response(201, headers={"Location": f"{ADMIN}/users/abc-123"})

    assert _client(handler).create_user(
        username="carol", email="carol@example.com", password="password1"
    ) == "abc-123"


def test_create_user_defaults_names_so_the_account_can_log_in():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return _token_ok(request)
        captured.update(json.loads(request.content))
        return httpx.Response(201, headers={"Location": f"{ADMIN}/users/x"})

    _client(handler).create_user(username="carol", email="c@example.com", password="password1")
    # Keycloak rejects logins for a user without names ("not fully set up").
    assert captured["firstName"] == "carol"
    assert captured["lastName"] == "carol"


def test_create_user_sets_the_tenant_attribute():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return _token_ok(request)
        captured.update(json.loads(request.content))
        return httpx.Response(201, headers={"Location": f"{ADMIN}/users/x"})

    _client(handler).create_user(
        username="carol", email="c@example.com", password="password1", tenant="globex"
    )
    # The tenant is an identity attribute; without it the account is unscoped and
    # policy denies everything.
    assert captured["attributes"] == {"tenant": ["globex"]}


def test_duplicate_username_raises_valueerror():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return _token_ok(request)
        return httpx.Response(409)

    with pytest.raises(ValueError, match="already taken"):
        _client(handler).create_user(
            username="alice", email="a@example.com", password="password1"
        )


def test_assign_role_posts_the_role_representation():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return _token_ok(request)
        if request.method == "GET":
            return httpx.Response(200, json={"id": "r1", "name": "manager"})
        assert request.method == "POST"
        assert b"manager" in request.content
        return httpx.Response(204)

    _client(handler).assign_role("abc", "manager")


def test_unknown_role_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return _token_ok(request)
        return httpx.Response(404)

    with pytest.raises(ValueError, match="unknown role"):
        _client(handler).assign_role("abc", "not_a_role")


def test_user_role_names_are_sorted():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return _token_ok(request)
        return httpx.Response(200, json=[{"name": "support_rep"}, {"name": "manager"}])

    assert _client(handler).user_role_names("abc") == ["manager", "support_rep"]
