"""Synthetic ticketing.

`draft_reply` records a draft; it never sends anything. Sending is a separate,
higher-risk action (and out of scope for Phase 1).
"""
from __future__ import annotations

import itertools

from . import data

_drafts: dict[str, dict] = {}
_seq = itertools.count(1)


def get_ticket(ticket_id: str) -> dict | None:
    return data.TICKETS.get(ticket_id)


def list_tickets(customer_id: str | None = None) -> list[dict]:
    tickets = data.TICKETS.values()
    if customer_id:
        tickets = [t for t in tickets if t["customer_id"] == customer_id]
    return list(tickets)


def draft_reply(ticket_id: str, body: str) -> dict:
    """Record a draft reply (does not send)."""
    if ticket_id not in data.TICKETS:
        raise ValueError(f"unknown ticket {ticket_id!r}")
    draft = {"id": f"d-{next(_seq):04d}", "ticket_id": ticket_id, "body": body, "status": "draft"}
    _drafts[draft["id"]] = draft
    return draft


def list_drafts(ticket_id: str | None = None) -> list[dict]:
    values = _drafts.values()
    if ticket_id:
        values = [d for d in values if d["ticket_id"] == ticket_id]
    return list(values)


def reset() -> None:
    global _seq
    _drafts.clear()
    _seq = itertools.count(1)
