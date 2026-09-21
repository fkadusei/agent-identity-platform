"""API tests: approvals bound to the authenticated caller, no self-approval."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentnhi import Delegation, TokenRejected
from app.api.authz import get_verifier
from app.api.main import app, get_store
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


def test_decision_requires_a_manager_role(client):
    created = client.post(
        "/approvals", json={"tool": "refunds.issue", "args": {}}, headers={"Authorization": "Bearer x"}
    ).json()
    # alice is a support_rep, not a manager: the role gate refuses before the store.
    resp = client.post(
        f"/approvals/{created['id']}/decision",
        json={"approved": True},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 403


def test_a_platform_admin_cannot_decide(client):
    created = client.post(
        "/approvals", json={"tool": "refunds.issue", "args": {}}, headers={"Authorization": "Bearer x"}
    ).json()
    # Administering users is not the same as approving business actions.
    _as(Delegation(user="admin", workload="spiffe://agent", audience="mcp-tools",
                   roles=("platform_admin",)))
    resp = client.post(
        f"/approvals/{created['id']}/decision",
        json={"approved": True},
        headers={"Authorization": "Bearer y"},
    )
    assert resp.status_code == 403


def test_self_approval_is_refused(client):
    created = client.post(
        "/approvals", json={"tool": "refunds.issue", "args": {}}, headers={"Authorization": "Bearer x"}
    ).json()
    # A manager who is *also* the requester still may not approve their own request.
    _as(Delegation(user="alice", workload="spiffe://agent", audience="mcp-tools", roles=("manager",)))
    resp = client.post(
        f"/approvals/{created['id']}/decision",
        json={"approved": True},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 409


def test_pending_queue(client):
    client.post("/approvals", json={"tool": "refunds.issue", "args": {}}, headers={"Authorization": "Bearer x"})
    # The queue is tenant-scoped, so it needs the caller's token.
    pending = client.get(
        "/approvals?status=pending", headers={"Authorization": "Bearer x"}
    ).json()
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"


def test_the_queue_is_scoped_to_the_callers_tenant(client):
    client.post("/approvals", json={"tool": "refunds.issue", "args": {}}, headers={"Authorization": "Bearer x"})
    # A session in another tenant sees nothing.
    _as(Delegation(user="grace", workload="spiffe://agent", audience="mcp-tools",
                   roles=("manager",), tenant="globex"))
    resp = client.get("/approvals", headers={"Authorization": "Bearer y"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_a_manager_cannot_decide_another_tenants_approval(client):
    created = client.post(
        "/approvals", json={"tool": "refunds.issue", "args": {}}, headers={"Authorization": "Bearer x"}
    ).json()
    _as(Delegation(user="grace", workload="spiffe://agent", audience="mcp-tools",
                   roles=("manager",), tenant="globex"))
    resp = client.post(
        f"/approvals/{created['id']}/decision",
        json={"approved": True},
        headers={"Authorization": "Bearer y"},
    )
    assert resp.status_code == 409  # not found in this tenant


def test_the_cache_policy_revalidates_the_shell_and_immortalises_bundles():
    """A stale build in a browser looks exactly like a bug, so the policy is asserted.

    `Cache-Control: no-cache` does not mean "do not cache" — it means "revalidate",
    which the ETag makes cheap. The bundles carry a content hash, so they never need to
    be re-fetched at all. Checked by driving the middleware directly, so this runs even
    where the UI has not been built (the app-tests job does not build it).
    """
    import asyncio

    from starlette.requests import Request
    from starlette.responses import Response

    from app.api.main import _cache_headers

    def header_for(path: str) -> str | None:
        scope = {"type": "http", "method": "GET", "path": path, "headers": []}
        request = Request(scope)

        async def call_next(_request):
            return Response("x")

        return asyncio.run(_cache_headers(request, call_next)).headers.get("cache-control")

    assert header_for("/") == "no-cache"
    assert header_for("/index.html") == "no-cache"
    assert header_for("/assets/index-abc123.js") == "public, max-age=31536000, immutable"
    # the API itself is not part of the caching story
    assert header_for("/healthz") is None
