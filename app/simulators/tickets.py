"""Synthetic ticketing, scoped by tenant.

`draft_reply` records a draft; it never sends anything. Sending is a separate,
higher-risk action (and out of scope for Phase 1).
"""
from __future__ import annotations

import itertools

from . import data
from .errors import NotFound

_drafts: dict[str, dict] = {}
_seq = itertools.count(1)


def get_ticket(ticket_id: str, tenant: str) -> dict | None:
    return data.scoped(data.TICKETS.get(ticket_id), tenant)


def list_tickets(tenant: str, customer_id: str | None = None) -> list[dict]:
    tickets = [t for t in data.TICKETS.values() if t["tenant"] == tenant]
    if customer_id:
        tickets = [t for t in tickets if t["customer_id"] == customer_id]
    return tickets


def draft_reply(ticket_id: str, body: str, tenant: str) -> dict:
    """Record a draft reply (does not send)."""
    if data.scoped(data.TICKETS.get(ticket_id), tenant) is None:
        raise NotFound(f"unknown ticket {ticket_id!r}")
    draft = {
        "id": f"d-{next(_seq):04d}",
        "ticket_id": ticket_id,
        "tenant": tenant,
        "body": body,
        "status": "draft",
    }
    _drafts[draft["id"]] = draft
    return draft


def list_drafts(tenant: str, ticket_id: str | None = None) -> list[dict]:
    values = [d for d in _drafts.values() if d["tenant"] == tenant]
    if ticket_id:
        values = [d for d in values if d["ticket_id"] == ticket_id]
    return list(values)


def reset() -> None:
    global _seq
    _drafts.clear()
    _seq = itertools.count(1)
