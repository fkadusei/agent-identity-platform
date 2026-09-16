"""The role -> tool matrix endpoint (it renders the policy, so it cannot drift)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentnhi import Delegation
from app.api.authz import get_verifier
from app.api.main import app

DANA = Delegation(user="dana", workload="spiffe://agent", audience="mcp-tools",
                  roles=("read_only",), tenant="acme")


class _Verifier:
    def verify(self, token, **_kwargs):
        return DANA


@pytest.fixture
def client(monkeypatch):
    seen: dict = {}

    def fake_matrix(opa, tenant, **kwargs):
        seen["tenant"] = tenant
        return {"read_only": ["crm.customer.read"]}

    monkeypatch.setattr("app.api.roles.role_matrix", fake_matrix)
    monkeypatch.setattr("app.api.roles.catalogue", lambda *a, **k: ["crm.customer.read", "refunds.issue"])
    monkeypatch.setattr("app.api.roles.refund_limits", lambda *a, **k: {"auto": 50, "approval": 500})
    app.dependency_overrides[get_verifier] = lambda: _Verifier()
    yield TestClient(app), seen
    app.dependency_overrides.clear()


def test_the_matrix_comes_from_the_policy(client):
    http, seen = client
    body = http.get("/roles", headers={"Authorization": "Bearer x"}).json()
    assert body["roles"] == {"read_only": ["crm.customer.read"]}
    assert body["tools"] == ["crm.customer.read", "refunds.issue"]
    assert body["limits"] == {"auto": 50, "approval": 500}
    assert body["you"] == {"roles": ["read_only"], "tenant": "acme"}


def test_the_matrix_is_the_callers_own_tenant(client):
    """The same role can differ between tenants (S8), so the page must ask about
    the caller's — showing the global default would misdescribe their powers."""
    http, seen = client
    http.get("/roles", headers={"Authorization": "Bearer x"})
    assert seen["tenant"] == "acme"


def test_it_needs_a_token():
    assert TestClient(app).get("/roles").status_code == 401
