"""Synthetic CRM: customers and their personal data.

Every accessor takes the caller's `tenant` and returns nothing outside it. That
is the contract the tools depend on, and the seam a real CRM replaces.
"""
from __future__ import annotations

from . import data


def get_customer(customer_id: str, tenant: str) -> dict | None:
    """Return a customer record (non-sensitive fields) or None."""
    customer = data.scoped(data.CUSTOMERS.get(customer_id), tenant)
    if customer is None:
        return None
    # Deliberately exclude direct identifiers from the "profile" view; they are
    # available only through get_pii(), which policy gates separately.
    return {k: v for k, v in customer.items() if k not in {"name", "email", "phone"}}


def list_customers(tenant: str) -> list[dict]:
    return [c for cid in data.CUSTOMERS if (c := get_customer(cid, tenant))]


def get_pii(customer_id: str, tenant: str) -> dict | None:
    """Return direct identifiers. Policy-gated (requires privacy approval)."""
    customer = data.scoped(data.CUSTOMERS.get(customer_id), tenant)
    if customer is None:
        return None
    return {
        "id": customer["id"],
        "name": customer["name"],
        "email": customer["email"],
        "phone": customer["phone"],
    }
