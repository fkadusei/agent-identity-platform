"""Tests for the approval store: binding, separation of duties, tenancy."""
from __future__ import annotations

from app.approvals import ApprovalStore

ACME = "acme"
GLOBEX = "globex"


def make(store: ApprovalStore, tenant: str = ACME):
    return store.create(
        tool="refunds.issue",
        args={"order_id": "o-1001", "amount": 200},
        user="alice",
        agent="spiffe://agent",
        reason="refund above the auto-approval limit",
        tenant=tenant,
    )


def verify(store, approval_id, tenant=ACME, **overrides):
    payload = dict(
        tool="refunds.issue",
        args={"order_id": "o-1001", "amount": 200},
        user="alice",
        agent="spiffe://agent",
        tenant=tenant,
    )
    payload.update(overrides)
    return store.verify(approval_id, **payload)


def test_verify_requires_approval():
    store = ApprovalStore()
    approval = make(store)
    assert verify(store, approval.id, args={"amount": 200, "order_id": "o-1001"}) is False


def test_approved_approval_verifies_for_the_exact_request():
    store = ApprovalStore()
    approval = make(store)
    store.decide(approval.id, approver="manager", approved=True, tenant=ACME)
    assert verify(store, approval.id)


def test_approval_does_not_verify_for_different_args():
    store = ApprovalStore()
    approval = make(store)
    store.decide(approval.id, approver="manager", approved=True, tenant=ACME)
    assert not verify(store, approval.id, args={"order_id": "o-1001", "amount": 9999})


def test_approval_does_not_verify_for_a_different_tool():
    store = ApprovalStore()
    approval = make(store)
    store.decide(approval.id, approver="manager", approved=True, tenant=ACME)
    assert not verify(store, approval.id, tool="privacy.pii.read")


def test_denied_approval_does_not_verify():
    store = ApprovalStore()
    approval = make(store)
    store.decide(approval.id, approver="manager", approved=False, tenant=ACME)
    assert not verify(store, approval.id)


def test_no_self_approval():
    store = ApprovalStore()
    approval = make(store)
    assert store.decide(approval.id, approver="alice", approved=True, tenant=ACME) is None
    assert store.get(approval.id, ACME).status == "pending"


def test_cannot_decide_twice():
    store = ApprovalStore()
    approval = make(store)
    assert store.decide(approval.id, approver="manager", approved=True, tenant=ACME) is not None
    assert store.decide(approval.id, approver="manager", approved=False, tenant=ACME) is None


# --- tenancy: the platform's own state, not just the data behind the tools ---

def test_another_tenants_approval_is_invisible():
    store = ApprovalStore()
    make(store, tenant=GLOBEX)
    assert store.pending(ACME) == []
    assert store.all(ACME) == []
    assert store.get(store.all(GLOBEX)[0].id, ACME) is None
    assert len(store.pending(GLOBEX)) == 1


def test_another_tenants_approval_cannot_be_decided():
    store = ApprovalStore()
    approval = make(store, tenant=GLOBEX)
    # An acme manager cannot decide a globex approval...
    assert store.decide(approval.id, approver="manager", approved=True, tenant=ACME) is None
    assert store.get(approval.id, GLOBEX).status == "pending"
    # ...but a globex manager can.
    assert store.decide(approval.id, approver="manager", approved=True, tenant=GLOBEX) is not None


def test_an_approval_does_not_verify_across_tenants():
    store = ApprovalStore()
    approval = make(store, tenant=GLOBEX)
    store.decide(approval.id, approver="manager", approved=True, tenant=GLOBEX)
    assert verify(store, approval.id, tenant=GLOBEX)
    assert not verify(store, approval.id, tenant=ACME)
