"""Synthetic simulators for the platform's downstream systems.

These stand in for real services (CRM, orders, payments, ticketing) so the
platform runs anywhere with no external accounts. They are the seam to replace
with real sandboxes later: the tool servers call these functions, and swapping
the implementation (or pointing at a real API) does not change the tools.

All data is synthetic; no real customer, card, or personal data is present.
"""
from . import crm, orders, payments, tickets

__all__ = ["crm", "orders", "payments", "tickets"]


def reset() -> None:
    """Reset runtime state across all simulators (tests)."""
    payments.reset()
    tickets.reset()


def snapshot() -> dict[str, list[dict]]:
    """The runtime state of the simulated systems.

    For a process that wants to keep it across restarts (S9) — the sandbox does,
    on its own volume; the platform's database is not a vendor's storage.
    """
    return {"refunds": payments.snapshot(), "drafts": tickets.snapshot()}


def restore(*, refunds: list[dict] | None = None, drafts: list[dict] | None = None) -> None:
    """Replace the runtime state with a previous process's (S9)."""
    payments.restore(list(refunds or []))
    tickets.restore(list(drafts or []))
