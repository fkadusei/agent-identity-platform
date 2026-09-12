"""Synthetic payments and refunds.

No card data is handled anywhere: orders carry opaque payment tokens, and a
refund only references the order and an amount.

`issue_refund` is idempotent on `idempotency_key`, which matters because a
human approval may resume an agent run more than once.
"""
from __future__ import annotations

import itertools

from . import data, orders

_refunds: dict[str, dict] = {}
_seq = itertools.count(1)


def quote_refund(order_id: str) -> dict | None:
    """Return how much of an order is refundable."""
    order = orders.get_order(order_id)
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


def issue_refund(order_id: str, amount: float, idempotency_key: str | None = None) -> dict:
    """Issue a refund. Idempotent when an idempotency_key is supplied."""
    if idempotency_key and idempotency_key in _refunds:
        return _refunds[idempotency_key]

    order = orders.get_order(order_id)
    if order is None:
        raise ValueError(f"unknown order {order_id!r}")
    if amount <= 0:
        raise ValueError("refund amount must be positive")

    refund = {
        "id": f"r-{next(_seq):04d}",
        "order_id": order_id,
        "amount": round(float(amount), 2),
        "status": "issued",
        "idempotency_key": idempotency_key,
    }
    key = idempotency_key or refund["id"]
    _refunds[key] = refund
    return refund


def list_refunds(order_id: str | None = None) -> list[dict]:
    values = _refunds.values()
    if order_id:
        values = [r for r in values if r["order_id"] == order_id]
    return list(values)


def reset() -> None:
    """Clear runtime state (tests)."""
    global _seq
    _refunds.clear()
    _seq = itertools.count(1)
