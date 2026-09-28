"""Login and self-service enrollment."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_auth_config_reflects_the_toggle(client, monkeypatch):
    monkeypatch.setenv("SIGNUP_ENABLED", "1")
    cfg = client.get("/auth/config").json()
    assert cfg["signup_enabled"] is True
    assert cfg["agent_id"].startswith("spiffe://")
    monkeypatch.setenv("SIGNUP_ENABLED", "0")
    assert client.get("/auth/config").json()["signup_enabled"] is False


def test_login_requires_credentials(client):
    assert client.post("/auth/login", json={}).status_code == 400


def test_enroll_is_refused_when_signup_is_disabled(client, monkeypatch):
    monkeypatch.setenv("SIGNUP_ENABLED", "0")
    resp = client.post(
        "/enroll",
        json={"username": "carol", "email": "c@example.com", "password": "password1"},
    )
    assert resp.status_code == 403


def test_enroll_never_takes_roles_from_the_request(client, monkeypatch):
    monkeypatch.setenv("SIGNUP_ENABLED", "1")
    monkeypatch.setenv("DEFAULT_TENANT", "acme")
    captured: dict = {}

    class FakeAdmin:
        def create_user(self, **kwargs):
            captured.update(kwargs)
            return "new-user-id"

    monkeypatch.setattr("app.api.auth.admin_from_env", lambda: FakeAdmin())
    resp = client.post(
        "/enroll",
        json={
            "username": "carol",
            "email": "c@example.com",
            "password": "password1",
            # A malicious signup trying to self-escalate:
            "roles": ["platform_admin"],
            # ...or to choose its own tenant:
            "tenant": "globex",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["roles"] == []
    assert "roles" not in captured
    # The tenant comes from configuration, not the request.
    assert captured["tenant"] == "acme"


def test_enroll_requires_all_fields(client, monkeypatch):
    monkeypatch.setenv("SIGNUP_ENABLED", "1")
    resp = client.post("/enroll", json={"username": "carol"})
    assert resp.status_code == 400


def test_platform_roles_filters_keycloak_builtins():
    from app.api.auth import platform_roles

    assert platform_roles(["default-roles-agent-platform", "offline_access", "support_rep"]) == [
        "support_rep"
    ]


def test_platform_roles_keeps_every_role_the_platform_has_and_no_builtins():
    """Every role the policy enforces must survive this filter.

    `billing` and `read_only` were missing from PLATFORM_ROLES, so a user holding only
    one of them signed in with `roles: []` while the policy still granted them tools —
    the UI said "no roles" and the platform let them work. A list that decides what the
    user sees has to include every role the policy acts on.
    """
    from app.api.auth import PLATFORM_ROLES, platform_roles

    assert set(PLATFORM_ROLES) == {
        "support_rep",
        "billing",
        "read_only",
        "privacy",
        "manager",
        "platform_admin",
    }
    kept = platform_roles(["billing", "default-roles-agent-platform", "offline_access"])
    assert kept == ["billing"]


def test_refresh_renews_the_session_without_a_password(client, monkeypatch):
    """The access token lives five minutes; the refresh token is what stops that
    from meaning "sign in every five minutes" (Q19)."""
    from agentnhi import Delegation
    from app.api.authz import get_verifier

    class _Verifier:
        def verify(self, token, **_):
            return Delegation(
                user="alice",
                workload="spiffe://agent",
                audience="mcp-tools",
                roles=("support_rep",),
                tenant="acme",
                claims={"exp": 999, "preferred_username": "alice"},
            )

    app.dependency_overrides[get_verifier] = lambda: _Verifier()
    monkeypatch.setattr("app.common.policy.tools_for_roles", lambda *a, **k: ["crm.customer.read"])
    sent: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "access_token": "new-access",
                "refresh_token": "rotated",
                "refresh_expires_in": 1800,
            }

    def fake_post(url, data=None, timeout=None):
        sent.update(data or {})
        return _Resp()

    monkeypatch.setattr("app.api.auth.httpx.post", fake_post)

    resp = client.post("/auth/refresh", json={"refresh_token": "old"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "new-access"
    assert body["refresh_token"] == "rotated"  # Keycloak rotates it; return the newest
    assert body["refresh_expires_at"] > 0
    assert body["expires_at"] == 999
    # It used the refresh-token grant, with the refresh token — never a password.
    assert sent["grant_type"] == "refresh_token"
    assert sent["refresh_token"] == "old"
    assert "password" not in sent
    app.dependency_overrides.clear()


def test_refresh_without_a_token_is_refused(client):
    assert client.post("/auth/refresh", json={}).status_code == 400


def test_refresh_that_keycloak_refuses_is_401(client, monkeypatch):
    class _Resp:
        status_code = 401

        def json(self):
            return {}

    monkeypatch.setattr("app.api.auth.httpx.post", lambda *a, **k: _Resp())
    assert client.post("/auth/refresh", json={"refresh_token": "stale"}).status_code == 401
