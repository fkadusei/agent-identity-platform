"""Tests for the approval store: binding, separation of duties, idempotence."""
from __future__ import annotations

from app.approvals import ApprovalStore


def make(store: ApprovalStore):
    return store.create(
        tool="refunds.issue",
        args={"order_id": "o-1001", "amount": 200},
        user="alice",
        agent="spiffe://agent",
        reason="refund above the auto-approval limit",
    )


def test_verify_requires_approval():
    store = ApprovalStore()
    approval = make(store)
    assert store.verify(approval.id, tool="refunds.issue", args={"amount": 200, "order_id": "o-1001"}, user="alice", agent="spiffe://agent") is False


def test_approved_approval_verifies_for_the_exact_request():
    store = ApprovalStore()
    approval = make(store)
    store.decide(approval.id, approver="manager", approved=True)
    assert store.verify(approval.id, tool="refunds.issue", args={"order_id": "o-1001", "amount": 200}, user="alice", agent="spiffe://agent")


def test_approval_does_not_verify_for_different_args():
    store = ApprovalStore()
    approval = make(store)
    store.decide(approval.id, approver="manager", approved=True)
    assert not store.verify(approval.id, tool="refunds.issue", args={"order_id": "o-1001", "amount": 9999}, user="alice", agent="spiffe://agent")


def test_approval_does_not_verify_for_a_different_tool():
    store = ApprovalStore()
    approval = make(store)
    store.decide(approval.id, approver="manager", approved=True)
    assert not store.verify(approval.id, tool="privacy.pii.read", args={"order_id": "o-1001", "amount": 200}, user="alice", agent="spiffe://agent")


def test_denied_approval_does_not_verify():
    store = ApprovalStore()
    approval = make(store)
    store.decide(approval.id, approver="manager", approved=False)
    assert not store.verify(approval.id, tool="refunds.issue", args={"order_id": "o-1001", "amount": 200}, user="alice", agent="spiffe://agent")


def test_no_self_approval():
    store = ApprovalStore()
    approval = make(store)
    assert store.decide(approval.id, approver="alice", approved=True) is None
    assert store.get(approval.id).status == "pending"


def test_cannot_decide_twice():
    store = ApprovalStore()
    approval = make(store)
    assert store.decide(approval.id, approver="manager", approved=True) is not None
    assert store.decide(approval.id, approver="manager", approved=False) is None
