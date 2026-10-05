"""Tool backends: where the tools actually go.

The tool catalogue is a thin interface over a *backend*.

* :class:`SimulatorBackend` — the in-process synthetic data (the default).
* :class:`HttpBackend` — calls a sandbox/vendor REST API.

**Every method takes the caller's `tenant`.** That is deliberate: there is no way
to read or write without naming the tenant you are acting for, so isolation
cannot be forgotten at a call site. The HTTP backend sends it as `X-Tenant`, the
header a real multi-tenant API would scope on.

Swapping the simulator for a real system is a configuration change
(`TOOLS_BACKEND`, `SANDBOX_BASE_URL`), not a code change — and the policy layer
above never knows the difference. See `docs/integrations.md`.
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any, Protocol

import httpx

from agentnhi import Settings, TokenExchanger
from app.simulators import crm, orders, payments, tickets
from app.simulators.errors import NotFound

#: The inbound user token for the current tool call, so the HTTP backend can
#: exchange it for a vendor-audienced one (downstream on-behalf-of, S28). A
#: contextvar, not an argument, so the tool-handler signatures do not all grow a
#: parameter only one backend uses.
_subject_token: ContextVar[str | None] = ContextVar("subject_token", default=None)


def set_subject_token(token: str | None):
    return _subject_token.set(token)


def reset_subject_token(handle) -> None:
    _subject_token.reset(handle)


class Backend(Protocol):
    """What a tool backend must provide. One method per external capability.

    Every method returns `None` for a record that is not there for this tenant —
    reads and writes alike — so a tool reports "not found" the same way whichever
    backend is configured.
    """

    def get_customer(self, customer_id: str, tenant: str) -> dict | None: ...
    def get_pii(self, customer_id: str, tenant: str) -> dict | None: ...
    def list_orders(self, customer_id: str, tenant: str) -> list[dict]: ...
    def get_ticket(self, ticket_id: str, tenant: str) -> dict | None: ...
    def draft_reply(self, ticket_id: str, body: str, tenant: str) -> dict | None: ...
    def quote_refund(self, order_id: str, tenant: str) -> dict | None: ...
    def issue_refund(
        self, order_id: str, amount: float, tenant: str, idempotency_key: str | None = None
    ) -> dict | None: ...


class SimulatorBackend:
    """In-process synthetic data, scoped by tenant.

    A record that is not there for this tenant returns `None` — the same as the
    HTTP backend's 404 — so the tools cannot tell which backend they are on. The
    simulators raise `NotFound` for that case (a write cannot proceed), and this
    is where it becomes the `None` the seam promised.
    """

    def get_customer(self, customer_id: str, tenant: str) -> dict | None:
        return crm.get_customer(customer_id, tenant)

    def get_pii(self, customer_id: str, tenant: str) -> dict | None:
        return crm.get_pii(customer_id, tenant)

    def list_orders(self, customer_id: str, tenant: str) -> list[dict]:
        return orders.list_orders(customer_id, tenant)

    def get_ticket(self, ticket_id: str, tenant: str) -> dict | None:
        return tickets.get_ticket(ticket_id, tenant)

    def draft_reply(self, ticket_id: str, body: str, tenant: str) -> dict | None:
        try:
            return tickets.draft_reply(ticket_id, body, tenant)
        except NotFound:
            return None

    def quote_refund(self, order_id: str, tenant: str) -> dict | None:
        return payments.quote_refund(order_id, tenant)

    def issue_refund(
        self, order_id: str, amount: float, tenant: str, idempotency_key: str | None = None
    ) -> dict | None:
        try:
            return payments.issue_refund(order_id, float(amount), tenant, idempotency_key)
        except NotFound:
            return None


class HttpBackend:
    """Calls a REST API (a sandbox, or the real vendor), scoped by `X-Tenant`.

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

    def _downstream_token(self) -> str | None:
        """Exchange the inbound user token for a vendor-audienced one (S28).

        On-behalf-of: the vendor then sees the user's subject, not only the tenant.
        The audience (`sandbox`) comes from the `tools` client's mapper. Returns
        None — and the caller falls back to the static token / `X-Tenant` — when
        OBO is unconfigured or the exchange fails, so a plain deployment still works.
        """
        subject = _subject_token.get()
        client_id = os.environ.get("TOOLS_CLIENT_ID", "")
        client_secret = os.environ.get("TOOLS_CLIENT_SECRET", "")
        if not subject or not client_id or not client_secret:
            return None
        try:
            return TokenExchanger(Settings.from_env()).exchange(
                subject_token=subject, client_id=client_id, client_secret=client_secret
            )
        except Exception:  # noqa: BLE001 - never fail the call on the exchange
            return None

    def _request(self, method: str, path: str, tenant: str, **kwargs) -> Any:
        headers = {"X-Tenant": tenant}
        # Prefer the user-delegated token; fall back to the static sandbox token.
        bearer = self._downstream_token() or self._token
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        resp = self._client.request(
            method, f"{self._base}{path}", headers=headers, timeout=self._timeout, **kwargs
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_customer(self, customer_id: str, tenant: str) -> dict | None:
        return self._request("GET", f"/customers/{customer_id}", tenant)

    def get_pii(self, customer_id: str, tenant: str) -> dict | None:
        return self._request("GET", f"/customers/{customer_id}/pii", tenant)

    def list_orders(self, customer_id: str, tenant: str) -> list[dict]:
        body = self._request("GET", f"/customers/{customer_id}/orders", tenant) or {}
        return body.get("orders", [])

    def get_ticket(self, ticket_id: str, tenant: str) -> dict | None:
        return self._request("GET", f"/tickets/{ticket_id}", tenant)

    def draft_reply(self, ticket_id: str, body: str, tenant: str) -> dict | None:
        return self._request("POST", f"/tickets/{ticket_id}/drafts", tenant, json={"body": body})

    def quote_refund(self, order_id: str, tenant: str) -> dict | None:
        return self._request("GET", f"/orders/{order_id}/refund-quote", tenant)

    def issue_refund(
        self, order_id: str, amount: float, tenant: str, idempotency_key: str | None = None
    ) -> dict | None:
        body: dict = {"amount": float(amount)}
        # Omit the key when there is none, so a plain refund keeps the original
        # request shape (and a real vendor that ignores the field sees no change).
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", f"/orders/{order_id}/refunds", tenant, json=body)


def get_backend() -> Backend:
    """`http` when TOOLS_BACKEND=http, else the in-process simulator."""
    if os.environ.get("TOOLS_BACKEND", "simulator").lower() == "http":
        return HttpBackend(
            base_url=os.environ.get("SANDBOX_BASE_URL", "http://sandbox:8090"),
            token=os.environ.get("SANDBOX_TOKEN", ""),
        )
    return SimulatorBackend()
