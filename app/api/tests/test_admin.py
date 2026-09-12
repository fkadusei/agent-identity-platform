"""Admin user management: gated on platform_admin, mutations audited."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentnhi import Delegation
from app.api.authz import get_verifier
from app.api.main import app

ALICE = Delegation(user="alice", workload="spiffe://agent", audience="mcp-tools", roles=("support_rep",))
ADMIN = Delegation(user="admin", workload="spiffe://agent", audience="mcp-tools", roles=("platform_admin",))


class _Verifier:
    def __init__(self, delegation):
        self._delegation = delegation

    def verify(self, token, **_kwargs):
        return self._delegation


class FakeAdmin:
    def __init__(self):
        self.granted = None
        self.removed = None
        self.enabled = None
        self.deleted = None

    def list_users(self):
        return [{"id": "u1", "username": "alice", "email": "a@example.com", "enabled": True}]

    def user_role_names(self, user_id):
        return ["support_rep"]

    def assign_role(self, user_id, role):
        self.granted = (user_id, role)

    def remove_role(self, user_id, role):
        self.removed = (user_id, role)

    def set_enabled(self, user_id, enabled):
        self.enabled = (user_id, enabled)

    def reset_password(self, user_id, password):
        self.reset = (user_id, password)

    def delete_user(self, user_id):
        self.deleted = user_id


def _as(delegation):
    app.dependency_overrides[get_verifier] = lambda: _Verifier(delegation)


@pytest.fixture
def client(monkeypatch):
    fake = FakeAdmin()
    monkeypatch.setattr("app.api.admin.admin_from_env", lambda: fake)
    _as(ADMIN)
    yield TestClient(app), fake
    app.dependency_overrides.clear()


def test_list_users(client):
    c, _ = client
    resp = c.get("/admin/users", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert resp.json() == [
        {"id": "u1", "username": "alice", "email": "a@example.com", "enabled": True, "roles": ["support_rep"]}
    ]


def test_requires_the_platform_admin_role(client):
    c, _ = client
    _as(ALICE)  # a support_rep must not administer users
    assert c.get("/admin/users", headers={"Authorization": "Bearer x"}).status_code == 403


def test_grant_role_rejects_unknown_roles(client):
    c, _ = client
    resp = c.post(
        "/admin/users/u1/roles", json={"role": "superuser"}, headers={"Authorization": "Bearer x"}
    )
    assert resp.status_code == 400


def test_grant_role_assigns(client):
    c, fake = client
    resp = c.post(
        "/admin/users/u1/roles", json={"role": "manager"}, headers={"Authorization": "Bearer x"}
    )
    assert resp.status_code == 200
    assert fake.granted == ("u1", "manager")


def test_revoke_role(client):
    c, fake = client
    resp = c.request(
        "DELETE", "/admin/users/u1/roles/manager", headers={"Authorization": "Bearer x"}
    )
    assert resp.status_code == 200
    assert fake.removed == ("u1", "manager")


def test_disable_user(client):
    c, fake = client
    resp = c.post(
        "/admin/users/u1/enabled", json={"enabled": False}, headers={"Authorization": "Bearer x"}
    )
    assert resp.status_code == 200
    assert fake.enabled == ("u1", False)


def test_reset_password_enforces_minimum_length(client):
    c, _ = client
    resp = c.post(
        "/admin/users/u1/password", json={"password": "short"}, headers={"Authorization": "Bearer x"}
    )
    assert resp.status_code == 400


def test_delete_user(client):
    c, fake = client
    resp = c.request("DELETE", "/admin/users/u1", headers={"Authorization": "Bearer x"})
    assert resp.status_code == 200
    assert fake.deleted == "u1"
