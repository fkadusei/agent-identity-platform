"""Synthetic data for the support & refunds platform.

Everything here is **generated** and describes no real person, account, or card.
There is no card data (PAN) anywhere — payments use opaque tokens. This is a
hard rule, not a convention: see docs/data-handling.md.
"""
from __future__ import annotations

# Opaque payment tokens — NOT card numbers.
CUSTOMERS: dict[str, dict] = {
    "c-100": {
        "id": "c-100",
        "tenant": "acme",
        "name": "Alice Example",
        "email": "alice@example.com",
        "phone": "+1-555-0100",
        "tier": "gold",
        "region": "us-east",
        "created_at": "2024-03-01",
    },
    "c-200": {
        "id": "c-200",
        "tenant": "acme",
        "name": "Bob Sample",
        "email": "bob@example.com",
        "phone": "+1-555-0200",
        "tier": "silver",
        "region": "eu-west",
        "created_at": "2024-06-14",
    },
    "c-300": {
        "id": "c-300",
        "tenant": "acme",
        "name": "Carol Demo",
        "email": "carol@example.com",
        "phone": "+1-555-0300",
        "tier": "standard",
        "region": "us-west",
        "created_at": "2025-01-09",
    },
    # A second tenant, so isolation is testable: a session scoped to `acme`
    # must not reach any of these.
    "c-900": {
        "id": "c-900",
        "tenant": "globex",
        "name": "Grace Other",
        "email": "grace@globex.example",
        "phone": "+1-555-0900",
        "tier": "gold",
        "region": "us-east",
        "created_at": "2024-11-02",
    },
}

ORDERS: dict[str, dict] = {
    "o-1001": {
        "id": "o-1001",
        "tenant": "acme",
        "customer_id": "c-100",
        "items": [{"sku": "WIDGET-A", "qty": 2, "price": 25.00}],
        "total": 50.00,
        "status": "delivered",
        "payment_token": "tok_demo_4242",
        "created_at": "2025-02-10",
    },
    "o-1002": {
        "id": "o-1002",
        "tenant": "acme",
        "customer_id": "c-100",
        "items": [{"sku": "GADGET-B", "qty": 1, "price": 320.00}],
        "total": 320.00,
        "status": "delivered",
        "payment_token": "tok_demo_1881",
        "created_at": "2025-03-02",
    },
    "o-2001": {
        "id": "o-2001",
        "tenant": "acme",
        "customer_id": "c-200",
        "items": [{"sku": "WIDGET-A", "qty": 1, "price": 25.00}],
        "total": 25.00,
        "status": "shipped",
        "payment_token": "tok_demo_9009",
        "created_at": "2025-04-21",
    },
    "o-3001": {
        "id": "o-3001",
        "tenant": "acme",
        "customer_id": "c-300",
        "items": [{"sku": "SUBSCRIPTION", "qty": 1, "price": 900.00}],
        "total": 900.00,
        "status": "delivered",
        "payment_token": "tok_demo_7777",
        "created_at": "2025-05-30",
    },
    "o-9001": {
        "id": "o-9001",
        "tenant": "globex",
        "customer_id": "c-900",
        "items": [{"sku": "WIDGET-A", "qty": 4, "price": 25.00}],
        "total": 100.00,
        "status": "delivered",
        "payment_token": "tok_demo_0900",
        "created_at": "2025-06-11",
    },
}

TICKETS: dict[str, dict] = {
    "t-5001": {
        "id": "t-5001",
        "tenant": "acme",
        "customer_id": "c-100",
        "subject": "My order arrived damaged",
        "status": "open",
        "messages": [
            {"from": "customer", "body": "The GADGET-B arrived with a cracked screen."}
        ],
    },
    "t-5002": {
        "id": "t-5002",
        "tenant": "acme",
        "customer_id": "c-200",
        "subject": "Where is my order?",
        "status": "open",
        "messages": [{"from": "customer", "body": "It has been a week."}],
    },
    "t-9001": {
        "id": "t-9001",
        "tenant": "globex",
        "customer_id": "c-900",
        "subject": "Invoice question",
        "status": "open",
        "messages": [{"from": "customer", "body": "Please re-send the invoice."}],
    },
}


def scoped(record: dict | None, tenant: str) -> dict | None:
    """Return the record only if it belongs to `tenant`, else None.

    The single rule that makes tenant isolation real: every data access goes
    through here, so a record from another tenant is indistinguishable from a
    record that does not exist.
    """
    if record is None or not tenant:
        return None
    return record if record.get("tenant") == tenant else None
