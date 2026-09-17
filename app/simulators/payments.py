"""Synthetic payments and refunds, scoped by tenant.

No card data is handled anywhere: orders carry opaque payment tokens, and a
refund only references the order and an amount.

`issue_refund` is idempotent on `idempotency_key`, which matters because a
human approval may resume an agent run more than once.
"""
from __future__ import annotations

import itertools

from . import data, orders
from .errors import NotFound

_refunds: dict[str, dict] = {}
_seq = itertools.count(1)


def quote_refund(order_id: str, tenant: str) -> dict | None:
    """Return how much of an order is refundable (None outside the tenant)."""
    order = orders.get_order(order_id, tenant)
    if order is None:
        return None
    already = sum(
        r["amount"] for r in _refunds.values() if r["order_id"] == order_id and r["status"] == "issued"
    )
    return {
        "order_id": order_id,
        "total": order["total"],
        "already_refunded": round(already, 2),
        "refundable": round(max(0.0, order["total"] - already), 2),
    }


def issue_refund(
    order_id: str, amount: float, tenant: str, idempotency_key: str | None = None
) -> dict:
    """Issue a refund. Idempotent when an idempotency_key is supplied."""
    if idempotency_key and idempotency_key in _refunds:
        return _refunds[idempotency_key]

    order = orders.get_order(order_id, tenant)
    if order is None:
        raise NotFound(f"unknown order {order_id!r}")
    if amount <= 0:
        raise ValueError("refund amount must be positive")

    refund = {
        "id": f"r-{next(_seq):04d}",
        "order_id": order_id,
        "tenant": tenant,
        "amount": round(float(amount), 2),
        "status": "issued",
        "idempotency_key": idempotency_key,
    }
    key = idempotency_key or refund["id"]
    _refunds[key] = refund
    return refund


def list_refunds(tenant: str, order_id: str | None = None) -> list[dict]:
    values = [r for r in _refunds.values() if r["tenant"] == tenant]
    if order_id:
        values = [r for r in values if r["order_id"] == order_id]
    return list(values)


def snapshot() -> list[dict]:
    """The issued refunds, for a caller that keeps them across restarts (S9)."""
    return list(_refunds.values())


def restore(records: list[dict]) -> None:
    """Replace the runtime state with a previous process's refunds (S9)."""
    global _seq
    _refunds.clear()
    for record in records:
        # Re-key the way `issue_refund` does, so idempotency still holds after a
        # restart: the same key returns the same refund instead of a second one.
        _refunds[record.get("idempotency_key") or record["id"]] = record
    _seq = itertools.count(data.next_id_number(records))


def reset() -> None:
    """Clear runtime state (tests)."""
    global _seq
    _refunds.clear()
    _seq = itertools.count(1)
