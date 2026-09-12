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
    assert client.get("/auth/config").json() == {"signup_enabled": True}
    monkeypatch.setenv("SIGNUP_ENABLED", "0")
    assert client.get("/auth/config").json() == {"signup_enabled": False}


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
        },
    )
    assert resp.status_code == 200
    assert resp.json()["roles"] == []
    assert "roles" not in captured


def test_enroll_requires_all_fields(client, monkeypatch):
    monkeypatch.setenv("SIGNUP_ENABLED", "1")
    resp = client.post("/enroll", json={"username": "carol"})
    assert resp.status_code == 400


def test_login_roles_are_filtered_to_platform_roles():
    import jwt

    from app.api.auth import _roles_from_token

    token = jwt.encode(
        {"realm_access": {"roles": ["default-roles-agent-platform", "offline_access", "support_rep"]}},
        "unused-because-we-do-not-verify-here",
    )
    assert _roles_from_token(token) == ["support_rep"]
