"""The Postgres approval store: same semantics as the in-memory one, durable.

Runs against a real database when TEST_DATABASE_URL (or PG*) is set (CI provides
one), and is skipped otherwise so the suite stays runnable without Postgres.
"""
from __future__ import annotations

import os
import uuid

import pytest

from app.approvals.store import PostgresApprovalStore
from app.common.db import connect

URL = os.environ.get("TEST_DATABASE_URL")
CONFIGURED = bool(URL or os.environ.get("PGHOST"))

ACME = "acme"
GLOBEX = "globex"

pytestmark = pytest.mark.skipif(
    not CONFIGURED, reason="no database configured (set TEST_DATABASE_URL or PG*)"
)


@pytest.fixture
def store():
    # url=None means "use the PG* environment"; a DSN overrides it.
    s = PostgresApprovalStore(URL)
    with connect(URL) as conn:
        conn.execute("DELETE FROM approvals")
    return s


def _create(store, tenant: str = ACME, **overrides):
    payload = dict(
        tool="refunds.issue",
        args={"order_id": "o-1001", "amount": 200},
        user="alice",
        agent="spiffe://acme.net/agent",
        reason="above the limit",
        tenant=tenant,
    )
    payload.update(overrides)
    return store.create(**payload)


def test_create_and_get(store):
    a = _create(store)
    assert a.id.startswith("ap-")
    fetched = store.get(a.id, ACME)
    assert fetched is not None
    assert fetched.status == "pending"
    assert fetched.tenant == ACME
    assert fetched.args == {"order_id": "o-1001", "amount": 200}


def test_approve_then_verify(store):
    a = _create(store)
    decided = store.decide(a.id, approver="manager", approved=True, note="ok", tenant=ACME)
    assert decided is not None and decided.status == "approved"
    assert store.verify(
        a.id,
        tool="refunds.issue",
        args={"order_id": "o-1001", "amount": 200},
        user="alice",
        agent="spiffe://acme.net/agent",
        tenant=ACME,
    )


def test_verify_rejects_a_different_request(store):
    a = _create(store)
    store.decide(a.id, approver="manager", approved=True, tenant=ACME)
    assert not store.verify(
        a.id,
        tool="refunds.issue",
        args={"order_id": "o-1001", "amount": 9999},
        user="alice",
        agent="spiffe://acme.net/agent",
        tenant=ACME,
    )


def test_self_approval_is_refused(store):
    a = _create(store, user="alice")
    assert store.decide(a.id, approver="alice", approved=True, tenant=ACME) is None
    assert store.get(a.id, ACME).status == "pending"


def test_double_decision_is_refused(store):
    a = _create(store)
    assert store.decide(a.id, approver="manager", approved=True, tenant=ACME) is not None
    assert store.decide(a.id, approver="manager", approved=False, tenant=ACME) is None


def test_pending_only_lists_pending(store):
    pending = _create(store, reason=f"p-{uuid.uuid4().hex[:6]}")
    decided = _create(store)
    store.decide(decided.id, approver="manager", approved=True, tenant=ACME)
    ids = {a.id for a in store.pending(ACME)}
    assert pending.id in ids
    assert decided.id not in ids


def test_all_lists_every_approval(store):
    a = _create(store)
    b = _create(store, reason="second")
    ids = {x.id for x in store.all(ACME)}
    assert {a.id, b.id} <= ids


# --- tenancy ----------------------------------------------------------------

def test_another_tenants_approval_is_invisible(store):
    _create(store, tenant=GLOBEX)
    assert store.pending(ACME) == []
    assert store.all(ACME) == []
    assert len(store.pending(GLOBEX)) == 1


def test_another_tenants_approval_cannot_be_decided(store):
    a = _create(store, tenant=GLOBEX)
    # An acme manager cannot decide a globex approval...
    assert store.decide(a.id, approver="manager", approved=True, tenant=ACME) is None
    assert store.get(a.id, GLOBEX).status == "pending"
    # ...but a globex manager can.
    assert store.decide(a.id, approver="manager", approved=True, tenant=GLOBEX) is not None


def test_an_approval_does_not_verify_across_tenants(store):
    a = _create(store, tenant=GLOBEX)
    store.decide(a.id, approver="manager", approved=True, tenant=GLOBEX)
    assert store.verify(
        a.id,
        tool="refunds.issue",
        args={"order_id": "o-1001", "amount": 200},
        user="alice",
        agent="spiffe://acme.net/agent",
        tenant=GLOBEX,
    )
    assert not store.verify(
        a.id,
        tool="refunds.issue",
        args={"order_id": "o-1001", "amount": 200},
        user="alice",
        agent="spiffe://acme.net/agent",
        tenant=ACME,
    )
