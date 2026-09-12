"""Synthetic CRM: customers and their personal data.

The seam for real systems: replace these functions with calls to a real CRM.
The signatures are the contract the tools depend on.
"""
from __future__ import annotations

from . import data


def get_customer(customer_id: str) -> dict | None:
    """Return a customer record (non-sensitive fields) or None."""
    customer = data.CUSTOMERS.get(customer_id)
    if customer is None:
        return None
    # Deliberately exclude direct identifiers from the "profile" view; they are
    # available only through get_pii(), which policy gates separately.
    return {k: v for k, v in customer.items() if k not in {"name", "email", "phone"}}


def list_customers() -> list[dict]:
    return [get_customer(cid) for cid in data.CUSTOMERS]


def get_pii(customer_id: str) -> dict | None:
    """Return direct identifiers. Policy-gated (requires privacy approval)."""
    customer = data.CUSTOMERS.get(customer_id)
    if customer is None:
        return None
    return {
        "id": customer["id"],
        "name": customer["name"],
        "email": customer["email"],
        "phone": customer["phone"],
    }
