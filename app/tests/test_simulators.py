"""Tests for the synthetic simulators."""
from __future__ import annotations

import pytest

from app.simulators import crm, orders, payments, reset, tickets


@pytest.fixture(autouse=True)
def _clean():
    reset()
    yield
    reset()


def test_customer_profile_excludes_direct_identifiers():
    profile = crm.get_customer("c-100")
    assert profile is not None
    assert profile["tier"] == "gold"
    for identifier in ("name", "email", "phone"):
        assert identifier not in profile


def test_pii_is_available_only_through_the_gated_function():
    pii = crm.get_pii("c-100")
    assert pii == {
        "id": "c-100",
        "name": "Alice Example",
        "email": "alice@example.com",
        "phone": "+1-555-0100",
    }


def test_unknown_customer_is_none():
    assert crm.get_customer("nope") is None


def test_orders_for_customer():
    assert len(orders.list_orders("c-100")) == 2
    assert orders.list_orders("nope") == []


def test_quote_refund():
    quote = payments.quote_refund("o-1001")
    assert quote["refundable"] == 50.0


def test_issue_refund_is_idempotent():
    first = payments.issue_refund("o-1001", 25.0, idempotency_key="key-1")
    again = payments.issue_refund("o-1001", 25.0, idempotency_key="key-1")
    assert first["id"] == again["id"]
    assert len(payments.list_refunds("o-1001")) == 1


def test_issue_refund_rejects_unknown_order():
    with pytest.raises(ValueError, match="unknown order"):
        payments.issue_refund("o-nope", 10.0)


def test_issue_refund_rejects_non_positive_amount():
    with pytest.raises(ValueError, match="positive"):
        payments.issue_refund("o-1001", 0)


def test_draft_reply_records_but_does_not_send():
    draft = tickets.draft_reply("t-5001", "Sorry about that — refunding now.")
    assert draft["status"] == "draft"
    assert tickets.list_drafts("t-5001")[0]["id"] == draft["id"]
    # The ticket itself is unchanged (nothing was sent).
    assert tickets.get_ticket("t-5001")["status"] == "open"


def test_draft_reply_rejects_unknown_ticket():
    with pytest.raises(ValueError, match="unknown ticket"):
        tickets.draft_reply("t-nope", "hi")
