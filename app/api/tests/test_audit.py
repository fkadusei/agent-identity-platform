"""The audit timeline: authenticated, and scoped to the caller's tenant.

It was neither. The trail names users, tools and decisions, so an open endpoint
told anything that could reach the API about every tenant's activity — including
which of its users had looked at personal data.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentnhi import Delegation
from app.api.authz import get_verifier
from app.api.main import app
from app.audit.store import AuditStore

MANAGER = Delegation(
    user="manager", workload="spiffe://agent", audience="mcp-tools", roles=("manager",), tenant="acme"
)


class _Verifier:
    def verify(self, token, **_kwargs):
        return MANAGER


@pytest.fixture
def audit(monkeypatch):
    store = AuditStore()
    monkeypatch.setattr("app.api.main._audit", store)
    return store


@pytest.fixture
def client(audit):
    app.dependency_overrides[get_verifier] = lambda: _Verifier()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_it_needs_a_token():
    assert TestClient(app).get("/audit").status_code == 401


def test_it_shows_your_tenants_events(client, audit):
    audit.append({"ts": 1.0, "event": "tool.allowed", "sub": "priya", "tenant": "acme"})
    got = client.get("/audit", headers={"Authorization": "Bearer x"}).json()
    assert [e["sub"] for e in got] == ["priya"]


def test_another_tenants_events_are_hidden(client, audit):
    audit.append({"ts": 1.0, "event": "tool.allowed", "sub": "grace", "tenant": "globex"})
    assert client.get("/audit", headers={"Authorization": "Bearer x"}).json() == []


def test_it_still_filters(client, audit):
    audit.append({"ts": 1.0, "event": "auth.login", "sub": "alice", "tenant": "acme"})
    audit.append({"ts": 2.0, "event": "tool.denied", "sub": "alice", "tenant": "acme"})
    got = client.get("/audit?event=tool.denied", headers={"Authorization": "Bearer x"}).json()
    assert [e["event"] for e in got] == ["tool.denied"]
