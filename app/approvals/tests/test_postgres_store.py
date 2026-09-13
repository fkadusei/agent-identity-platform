"""The Postgres approval store: same semantics as the in-memory one, durable.

Runs against a real database when TEST_DATABASE_URL is set (CI provides one),
and is skipped otherwise so the suite stays runnable without Postgres.
"""
from __future__ import annotations

import os
import uuid

import pytest

from app.approvals.store import PostgresApprovalStore

URL = os.environ.get("TEST_DATABASE_URL")
CONFIGURED = bool(URL or os.environ.get("PGHOST"))

pytestmark = pytest.mark.skipif(
    not CONFIGURED, reason="no database configured (set TEST_DATABASE_URL or PG*)"
)


@pytest.fixture
def store():
    # url=None means "use the PG* environment"; a DSN overrides it.
    s = PostgresApprovalStore(URL)
    from app.common.db import connect

    with connect(URL) as conn:
        conn.execute("DELETE FROM approvals")
    return s


def _create(store, **overrides):
    payload = dict(
        tool="refunds.issue",
        args={"order_id": "o-1001", "amount": 200},
        user="alice",
        agent="spiffe://acme.net/agent",
        reason="above the limit",
        tenant="acme",
    )
    payload.update(overrides)
    return store.create(**payload)


def test_create_and_get(store):
    a = _create(store)
    assert a.id.startswith("ap-")
    fetched = store.get(a.id, "acme")
    assert fetched is not None
    assert fetched.status == "pending"
    assert fetched.args == {"order_id": "o-1001", "amount": 200}


def test_approve_then_verify(store):
    a = _create(store)
    decided = store.decide(a.id, approver="manager", approved=True, note="ok", tenant="acme")
    assert decided is not None and decided.status == "approved"
    assert store.verify(
        a.id,
        tool="refunds.issue",
        args={"order_id": "o-1001", "amount": 200},
        user="alice",
        agent="spiffe://acme.net/agent",
        tenant="acme",
    )


def test_verify_rejects_a_different_request(store):
    a = _create(store)
    store.decide(a.id, approver="manager", approved=True, tenant="acme")
    # Same approval id, different amount -> not valid.
    assert not store.verify(
        a.id,
        tool="refunds.issue",
        args={"order_id": "o-1001", "amount": 9999},
        user="alice",
        agent="spiffe://acme.net/agent",
        tenant="acme",
    )


def test_self_approval_is_refused(store):
    a = _create(store, user="alice")
    assert store.decide(a.id, approver="alice", approved=True, tenant="acme") is None
    assert store.get(a.id, "acme").status == "pending"


def test_double_decision_is_refused(store):
    a = _create(store)
    assert store.decide(a.id, approver="manager", approved=True, tenant="acme") is not None
    # Second decision on an already-decided approval loses.
    assert store.decide(a.id, approver="manager", approved=False, tenant="acme") is None


def test_pending_only_lists_pending(store):
    pending = _create(store, reason=f"p-{uuid.uuid4().hex[:6]}")
    decided = _create(store)
    store.decide(decided.id, approver="manager", approved=True)
    ids = {a.id for a in store.pending("acme")}
    assert pending.id in ids
    assert decided.id not in ids


def test_all_lists_every_approval(store):
    a = _create(store)
    b = _create(store, reason="second")
    ids = {x.id for x in store.all("acme")}
    assert {a.id, b.id} <= ids
