"""Tool backends: where the tools actually go.

The tool catalogue is a thin interface over a *backend*.

* :class:`SimulatorBackend` — the in-process synthetic data (the default).
* :class:`HttpBackend` — calls a sandbox/vendor REST API.

Swapping the simulator for a real system is therefore a configuration change
(`TOOLS_BACKEND`, `SANDBOX_BASE_URL`), not a code change — and the policy layer
above never knows the difference. See `docs/integrations.md`.
"""
from __future__ import annotations

import os
from typing import Any, Protocol

import httpx

from app.simulators import crm, orders, payments, tickets


class Backend(Protocol):
    """What a tool backend must provide. One method per external capability."""

    def get_customer(self, customer_id: str) -> dict | None: ...
    def get_pii(self, customer_id: str) -> dict | None: ...
    def list_orders(self, customer_id: str) -> list[dict]: ...
    def get_ticket(self, ticket_id: str) -> dict | None: ...
    def draft_reply(self, ticket_id: str, body: str) -> dict: ...
    def quote_refund(self, order_id: str) -> dict | None: ...
    def issue_refund(self, order_id: str, amount: float) -> dict: ...


class SimulatorBackend:
    """In-process synthetic data."""

    def get_customer(self, customer_id: str) -> dict | None:
        return crm.get_customer(customer_id)

    def get_pii(self, customer_id: str) -> dict | None:
        return crm.get_pii(customer_id)

    def list_orders(self, customer_id: str) -> list[dict]:
        return orders.list_orders(customer_id)

    def get_ticket(self, ticket_id: str) -> dict | None:
        return tickets.get_ticket(ticket_id)

    def draft_reply(self, ticket_id: str, body: str) -> dict:
        return tickets.draft_reply(ticket_id, body)

    def quote_refund(self, order_id: str) -> dict | None:
        return payments.quote_refund(order_id)

    def issue_refund(self, order_id: str, amount: float) -> dict:
        return payments.issue_refund(order_id, float(amount))


class HttpBackend:
    """Calls a REST API (a sandbox, or the real vendor).

    A 404 maps to "not found" (``None``) so the tools behave the same as with the
    simulator; anything else raises, which the enforcement core turns into a
    tool error rather than a silent success.
    """

    def __init__(
        self,
        base_url: str,
        token: str = "",
        client: Any | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._client = client or httpx.Client()
        self._timeout = timeout

    def _request(self, method: str, path: str, **kwargs) -> Any:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        resp = self._client.request(
            method, f"{self._base}{path}", headers=headers, timeout=self._timeout, **kwargs
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_customer(self, customer_id: str) -> dict | None:
        return self._request("GET", f"/customers/{customer_id}")

    def get_pii(self, customer_id: str) -> dict | None:
        return self._request("GET", f"/customers/{customer_id}/pii")

    def list_orders(self, customer_id: str) -> list[dict]:
        body = self._request("GET", f"/customers/{customer_id}/orders") or {}
        return body.get("orders", [])

    def get_ticket(self, ticket_id: str) -> dict | None:
        return self._request("GET", f"/tickets/{ticket_id}")

    def draft_reply(self, ticket_id: str, body: str) -> dict:
        return self._request("POST", f"/tickets/{ticket_id}/drafts", json={"body": body})

    def quote_refund(self, order_id: str) -> dict | None:
        return self._request("GET", f"/orders/{order_id}/refund-quote")

    def issue_refund(self, order_id: str, amount: float) -> dict:
        return self._request(
            "POST", f"/orders/{order_id}/refunds", json={"amount": float(amount)}
        )


def get_backend() -> Backend:
    """`http` when TOOLS_BACKEND=http, else the in-process simulator."""
    if os.environ.get("TOOLS_BACKEND", "simulator").lower() == "http":
        return HttpBackend(
            base_url=os.environ.get("SANDBOX_BASE_URL", "http://sandbox:8090"),
            token=os.environ.get("SANDBOX_TOKEN", ""),
        )
    return SimulatorBackend()
