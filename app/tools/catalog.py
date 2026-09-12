"""The tool catalogue: what the agent can ask for, and how it is executed.

Each tool declares its input schema (for MCP discovery) and a handler that calls
a simulator. The handlers contain **no authorization logic** — that lives in the
enforcement core and OPA.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.simulators import crm, orders, payments, tickets


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    risk: str  # "low" | "high"
    input_schema: dict
    handler: Callable[..., Any] = field(repr=False)


def _customer_id_schema() -> dict:
    return {
        "type": "object",
        "properties": {"customer_id": {"type": "string"}},
        "required": ["customer_id"],
    }


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            name="crm.customer.read",
            description="Read a customer's profile (non-sensitive fields).",
            risk="low",
            input_schema=_customer_id_schema(),
            handler=lambda customer_id: crm.get_customer(customer_id) or _not_found("customer"),
        ),
        Tool(
            name="crm.orders.list",
            description="List a customer's orders.",
            risk="low",
            input_schema=_customer_id_schema(),
            handler=lambda customer_id: {"orders": orders.list_orders(customer_id)},
        ),
        Tool(
            name="tickets.read",
            description="Read a support ticket and its messages.",
            risk="low",
            input_schema={
                "type": "object",
                "properties": {"ticket_id": {"type": "string"}},
                "required": ["ticket_id"],
            },
            handler=lambda ticket_id: tickets.get_ticket(ticket_id) or _not_found("ticket"),
        ),
        Tool(
            name="tickets.reply.draft",
            description="Draft a reply to a ticket. Does NOT send it.",
            risk="low",
            input_schema={
                "type": "object",
                "properties": {"ticket_id": {"type": "string"}, "body": {"type": "string"}},
                "required": ["ticket_id", "body"],
            },
            handler=lambda ticket_id, body: tickets.draft_reply(ticket_id, body),
        ),
        Tool(
            name="refunds.quote",
            description="Quote how much of an order is refundable.",
            risk="low",
            input_schema={
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
            handler=lambda order_id: payments.quote_refund(order_id) or _not_found("order"),
        ),
        Tool(
            name="refunds.issue",
            description="Issue a refund for an order. High-risk: policy may require approval.",
            risk="high",
            input_schema={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": ["order_id", "amount"],
            },
            handler=lambda order_id, amount: payments.issue_refund(order_id, float(amount)),
        ),
        Tool(
            name="privacy.pii.read",
            description="Read a customer's direct identifiers (name, email, phone). High-risk.",
            risk="high",
            input_schema=_customer_id_schema(),
            handler=lambda customer_id: crm.get_pii(customer_id) or _not_found("customer"),
        ),
    ]
}


def _not_found(what: str) -> dict:
    return {"error": f"unknown {what}"}
