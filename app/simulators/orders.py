"""Synthetic orders, scoped by tenant."""
from __future__ import annotations

from . import data


def list_orders(customer_id: str, tenant: str) -> list[dict]:
    return [
        o
        for o in data.ORDERS.values()
        if o["customer_id"] == customer_id and o["tenant"] == tenant
    ]


def get_order(order_id: str, tenant: str) -> dict | None:
    return data.scoped(data.ORDERS.get(order_id), tenant)
