"""API tests: approvals bound to the authenticated caller, no self-approval."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentnhi import Delegation, TokenRejected
from app.api.main import app, get_store, get_verifier
from app.approvals import ApprovalStore

ALICE = Delegation(user="alice", workload="spiffe://agent", audience="mcp-tools", roles=("support_rep",))
MANAGER = Delegation(user="manager", workload="spiffe://agent", audience="mcp-tools", roles=("manager",))


class _Verifier:
    def __init__(self, delegation=None, error=None):
        self._delegation = delegation
        self._error = error

    def verify(self, token, **_kwargs):
        if self._error:
            raise self._error
        return self._delegation


@pytest.fixture
def client():
    store = ApprovalStore()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_verifier] = lambda: _Verifier(ALICE)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(verifier_delegation):
    app.dependency_overrides[get_verifier] = lambda: _Verifier(verifier_delegation)


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_missing_token_is_401(client):
    assert client.post("/approvals", json={"tool": "refunds.issue"}).status_code == 401


def test_rejected_token_is_403(client):
    _as(None)
    app.dependency_overrides[get_verifier] = lambda: _Verifier(error=TokenRejected("audience mismatch"))
    resp = client.post(
        "/approvals", json={"tool": "refunds.issue"}, headers={"Authorization": "Bearer x"}
    )
    assert resp.status_code == 403


def test_create_and_verify_approval(client):
    created = client.post(
        "/approvals",
        json={"tool": "refunds.issue", "args": {"order_id": "o-1001", "amount": 200}, "reason": "big"},
        headers={"Authorization": "Bearer x"},
    ).json()
    assert created["status"] == "pending"
    assert created["user"] == "alice"

    # Not yet approved -> verify is false.
    resp = client.post("/approvals/verify", json={
        "approval_id": created["id"], "tool": "refunds.issue",
        "args": {"order_id": "o-1001", "amount": 200}, "user": "alice", "agent": "spiffe://agent",
    })
    assert resp.json() == {"valid": False}

    # Manager approves.
    _as(MANAGER)
    decided = client.post(
        f"/approvals/{created['id']}/decision",
        json={"approved": True, "note": "ok"},
        headers={"Authorization": "Bearer y"},
    ).json()
    assert decided["status"] == "approved"

    resp = client.post("/approvals/verify", json={
        "approval_id": created["id"], "tool": "refunds.issue",
        "args": {"order_id": "o-1001", "amount": 200}, "user": "alice", "agent": "spiffe://agent",
    })
    assert resp.json() == {"valid": True}


def test_self_approval_is_refused(client):
    created = client.post(
        "/approvals", json={"tool": "refunds.issue", "args": {}}, headers={"Authorization": "Bearer x"}
    ).json()
    # Alice (the requester) tries to approve her own request.
    resp = client.post(
        f"/approvals/{created['id']}/decision",
        json={"approved": True},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 409


def test_pending_queue(client):
    client.post("/approvals", json={"tool": "refunds.issue", "args": {}}, headers={"Authorization": "Bearer x"})
    pending = client.get("/approvals?status=pending").json()
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"
