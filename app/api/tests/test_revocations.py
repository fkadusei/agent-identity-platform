"""The revocation endpoints (S23): admin-only writes, a read for our services."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentnhi import Delegation
from app.api import main as api_main
from app.api.authz import get_verifier
from app.api.main import app
from app.api.revocations import RevocationStore
from app.common import workload

AGENT = workload.AGENT
ADMIN = Delegation(
    user="admin", workload="spiffe://agent", audience="mcp-tools", roles=("platform_admin",)
)
ALICE = Delegation(
    user="alice", workload="spiffe://agent", audience="mcp-tools", roles=("support_rep",)
)


class _Verifier:
    def __init__(self, delegation):
        self._delegation = delegation

    def verify(self, token, **_kwargs):
        return self._delegation


@pytest.fixture
def client():
    store = RevocationStore()
    api_main._revocations = store
    app.dependency_overrides[get_verifier] = lambda: _Verifier(ADMIN)
    yield TestClient(app), store
    app.dependency_overrides.clear()


def test_admin_revokes_lists_and_restores(client):
    c, store = client
    resp = c.post(
        "/admin/workloads/revoke",
        json={"spiffe_id": AGENT, "reason": "rogue"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    assert store.ids() == {AGENT}

    listed = c.get("/admin/workloads/revoked", headers={"Authorization": "Bearer x"}).json()
    assert listed[0]["spiffe_id"] == AGENT

    restored = c.post(
        "/admin/workloads/restore",
        json={"spiffe_id": AGENT},
        headers={"Authorization": "Bearer x"},
    ).json()
    assert restored["restored"] is True
    assert store.ids() == set()


def test_a_non_admin_cannot_revoke(client):
    app.dependency_overrides[get_verifier] = lambda: _Verifier(ALICE)
    resp = client[0].post(
        "/admin/workloads/revoke",
        json={"spiffe_id": AGENT},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 403


def test_the_services_read_the_revoked_set(client):
    c, store = client
    store.revoke(AGENT, reason="rogue", by="admin")
    # require_workload is a no-op without WORKLOAD_AUDIENCE (the test environment).
    assert c.get("/workloads/revoked").json() == {"revoked": [AGENT]}
