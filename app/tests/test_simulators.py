"""Tests for the synthetic simulators, including tenant isolation."""
from __future__ import annotations

import pytest

from app import simulators
from app.simulators import crm, orders, payments, reset, tickets
from app.simulators.errors import NotFound

ACME = "acme"
GLOBEX = "globex"


@pytest.fixture(autouse=True)
def _clean():
    reset()
    yield
    reset()


def test_customer_profile_excludes_direct_identifiers():
    profile = crm.get_customer("c-100", ACME)
    assert profile is not None
    assert profile["tier"] == "gold"
    for identifier in ("name", "email", "phone"):
        assert identifier not in profile


def test_pii_is_available_only_through_the_gated_function():
    assert crm.get_pii("c-100", ACME) == {
        "id": "c-100",
        "name": "Alice Example",
        "email": "alice@example.com",
        "phone": "+1-555-0100",
    }


def test_unknown_customer_is_none():
    assert crm.get_customer("nope", ACME) is None


def test_orders_for_customer():
    assert len(orders.list_orders("c-100", ACME)) == 2
    assert orders.list_orders("nope", ACME) == []


def test_quote_refund():
    assert payments.quote_refund("o-1001", ACME)["refundable"] == 50.0


def test_issue_refund_is_idempotent():
    first = payments.issue_refund("o-1001", 25.0, ACME, idempotency_key="key-1")
    again = payments.issue_refund("o-1001", 25.0, ACME, idempotency_key="key-1")
    assert first["id"] == again["id"]
    assert len(payments.list_refunds(ACME, "o-1001")) == 1


def test_issue_refund_rejects_unknown_order():
    with pytest.raises(ValueError, match="unknown order"):
        payments.issue_refund("o-nope", 10.0, ACME)


def test_a_missing_record_raises_the_typed_not_found():
    """`NotFound` is what lets the backend seam tell "not there" from "bad input"
    and map it to the `None` a read returns (and the HTTP contract's 404). It
    subclasses ValueError, so callers that treat it as invalid input still work."""
    with pytest.raises(NotFound):
        payments.issue_refund("o-nope", 10.0, ACME)
    with pytest.raises(NotFound):
        tickets.draft_reply("t-nope", "hi", ACME)
    # ...but a bad amount is *not* a missing record.
    with pytest.raises(ValueError) as exc:
        payments.issue_refund("o-1001", 0, ACME)
    assert not isinstance(exc.value, NotFound)


def test_state_survives_a_snapshot_and_a_restore():
    """The sandbox's durability (S9) rests on these two functions, so the details
    that make a *restart* invisible are pinned here: the records come back, the
    ids do not collide, and idempotency still holds."""
    reset()
    refund = payments.issue_refund("o-1001", 25.0, ACME, idempotency_key="key-1")
    draft = tickets.draft_reply("t-5001", "hello", ACME)

    payload = simulators.snapshot()
    reset()  # a new process, same volume
    assert payments.list_refunds(ACME) == []

    simulators.restore(**payload)
    assert [r["id"] for r in payments.list_refunds(ACME)] == [refund["id"]]
    assert [d["id"] for d in tickets.list_drafts(ACME)] == [draft["id"]]

    # The same idempotency key returns the restored refund, not a second one.
    again = payments.issue_refund("o-1001", 25.0, ACME, idempotency_key="key-1")
    assert again["id"] == refund["id"]

    # And a genuinely new record resumes after the restored ones.
    fresh = payments.issue_refund("o-1001", 5.0, ACME)
    assert fresh["id"] == "r-0002"
    assert tickets.draft_reply("t-5001", "more", ACME)["id"] == "d-0002"


def test_issue_refund_rejects_non_positive_amount():
    with pytest.raises(ValueError, match="positive"):
        payments.issue_refund("o-1001", 0, ACME)


def test_draft_reply_records_but_does_not_send():
    draft = tickets.draft_reply("t-5001", "Sorry about that — refunding now.", ACME)
    assert draft["status"] == "draft"
    assert tickets.list_drafts(ACME, "t-5001")[0]["id"] == draft["id"]
    assert tickets.get_ticket("t-5001", ACME)["status"] == "open"


def test_draft_reply_rejects_unknown_ticket():
    with pytest.raises(ValueError, match="unknown ticket"):
        tickets.draft_reply("t-nope", "hi", ACME)


# --- tenant isolation (threat T9) -------------------------------------------
# A record outside the caller's tenant must be indistinguishable from one that
# does not exist.

def test_a_customer_from_another_tenant_is_invisible():
    assert crm.get_customer("c-900", ACME) is None
    assert crm.get_customer("c-900", GLOBEX) is not None


def test_pii_from_another_tenant_is_invisible():
    assert crm.get_pii("c-900", ACME) is None


def test_orders_from_another_tenant_are_invisible():
    assert orders.list_orders("c-900", ACME) == []
    assert orders.list_orders("c-900", GLOBEX) != []


def test_refund_for_another_tenants_order_is_rejected():
    with pytest.raises(ValueError, match="unknown order"):
        payments.issue_refund("o-9001", 10.0, ACME)
    assert payments.quote_refund("o-9001", ACME) is None


def test_ticket_from_another_tenant_is_invisible():
    assert tickets.get_ticket("t-9001", ACME) is None
    with pytest.raises(ValueError, match="unknown ticket"):
        tickets.draft_reply("t-9001", "hi", ACME)


def test_an_empty_tenant_sees_nothing():
    # Fail closed: no tenant, no data.
    assert crm.get_customer("c-100", "") is None
    assert orders.list_orders("c-100", "") == []
