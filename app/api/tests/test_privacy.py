"""The privacy view: who looked at personal data, why, and who approved it."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentnhi import Delegation
from app.api.authz import get_verifier
from app.api.main import app, get_store
from app.audit.store import AuditStore
from app.approvals import ApprovalStore

MANAGER = Delegation(
    user="manager", workload="spiffe://agent", audience="mcp-tools", roles=("manager",), tenant="acme"
)
PRIYA = Delegation(
    user="priya", workload="spiffe://agent", audience="mcp-tools", roles=("privacy",), tenant="acme"
)


class _Verifier:
    def __init__(self, delegation):
        self._delegation = delegation

    def verify(self, token, **_kwargs):
        return self._delegation


@pytest.fixture
def store():
    return ApprovalStore()


@pytest.fixture
def audit(monkeypatch):
    """A fresh audit store per test, swapped into the API module."""
    store = AuditStore()
    monkeypatch.setattr("app.api.main._audit", store)
    return store


@pytest.fixture
def client(store, audit):
    app.dependency_overrides[get_verifier] = lambda: _Verifier(MANAGER)
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _pii_event(**over):
    event = {
        "event": "tool.allowed",
        "sub": "priya",
        "tool": "privacy.pii.read",
        "tenant": "acme",
        "decision": "allow",
        "reason": "requires privacy approval: PII access",
        "policy_version": "rev-7",
        "ts": 1_700_000_000.0,
    }
    event.update(over)
    return event


def _get(client, **kw):
    return client.get("/privacy/access", headers={"Authorization": "Bearer x"}, **kw).json()


def test_it_shows_the_access_trail(client, audit):
    audit.append(_pii_event())
    body = _get(client)
    assert body["tool"] == "privacy.pii.read"
    assert body["tenant"] == "acme"
    (row,) = body["access"]
    assert row["user"] == "priya"
    assert row["decision"] == "allow"
    assert row["policy_version"] == "rev-7"


def test_a_refused_attempt_is_on_the_trail_too(client, audit):
    # The refusals are the point: "who tried" matters as much as "who read".
    audit.append(_pii_event(event="tool.denied", decision="deny", sub="alice"))
    (row,) = _get(client)["access"]
    assert (row["user"], row["decision"]) == ("alice", "deny")


def test_a_held_attempt_reads_as_approval_required(client, audit):
    audit.append(_pii_event(event="tool.approval_required", decision=None))
    assert _get(client)["access"][0]["decision"] == "approval_required"


def test_other_tools_are_not_personal_data(client, audit):
    audit.append(_pii_event(tool="crm.customer.read"))
    assert _get(client)["access"] == []


def test_it_is_scoped_to_your_tenant(client, audit):
    audit.append(_pii_event(tenant="globex"))
    assert _get(client)["access"] == []


def test_it_carries_the_approval_trail(client, store):
    store.create(
        tool="privacy.pii.read", args={"customer_id": "c-100"}, user="priya",
        agent="spiffe://agent", reason="need the phone number", tenant="acme",
    )
    store.create(
        tool="refunds.issue", args={"order_id": "o-1001"}, user="alice",
        agent="spiffe://agent", reason="goodwill", tenant="acme",
    )
    (approval,) = _get(client)["approvals"]
    assert approval["tool"] == "privacy.pii.read"
    assert approval["args"] == {"customer_id": "c-100"}
    assert approval["status"] == "pending"


def test_another_tenants_approvals_are_hidden(client, store):
    store.create(
        tool="privacy.pii.read", args={}, user="grace", agent="spiffe://agent",
        reason="", tenant="globex",
    )
    assert _get(client)["approvals"] == []


def test_it_is_not_for_the_privacy_role_itself(store):
    # Oversight of who reads personal data belongs to the approver, not to the
    # role that does the reading.
    app.dependency_overrides[get_verifier] = lambda: _Verifier(PRIYA)
    app.dependency_overrides[get_store] = lambda: store
    try:
        res = TestClient(app).get("/privacy/access", headers={"Authorization": "Bearer x"})
        assert res.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_it_needs_a_token():
    assert TestClient(app).get("/privacy/access").status_code == 401
