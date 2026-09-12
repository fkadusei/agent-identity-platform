"""Synthetic orders."""
from __future__ import annotations

from . import data


def list_orders(customer_id: str) -> list[dict]:
    return [o for o in data.ORDERS.values() if o["customer_id"] == customer_id]


def get_order(order_id: str) -> dict | None:
    return data.ORDERS.get(order_id)
