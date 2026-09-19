"""MCP transport for the tools.

Exposes the same catalogue over the Model Context Protocol (Streamable HTTP),
delegating to the identical enforcement core as the HTTP transport. Tool schemas
are inferred by MCP from each handler's typed signature.

Handlers are written explicitly (rather than generated) so there is no dynamic
code execution anywhere in the codebase.

Authentication: the caller presents its exchanged token as a bearer token. An
ASGI middleware lifts it into a context variable, which the handlers read; the
enforcer then verifies it as usual.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from mcp.server.mcpserver import MCPServer

from app.tools.catalog import TOOLS
from app.tools.enforcement import Outcome, ToolEnforcer
from app.tools.wiring import build_enforcer

_token: ContextVar[str | None] = ContextVar("agent_token", default=None)
# The caller's own SVID, naming the workload (S7) — lifted the same way as the
# user-scoped token above, so the MCP transport enforces exactly what HTTP does.
_workload_token: ContextVar[str | None] = ContextVar("workload_token", default=None)


def build_mcp_server(enforcer: ToolEnforcer | None = None) -> MCPServer:
    enforcer = enforcer or build_enforcer()
    server = MCPServer("agent-tools")

    def dispatch(name: str, args: dict) -> dict:
        result = enforcer.call(
            _token.get(), name, args, workload_token=_workload_token.get()
        )
        if result.outcome is Outcome.OK:
            return result.result or {}
        return {"status": result.outcome.value, "reason": result.reason}

    @server.tool(name="crm.customer.read", description=TOOLS["crm.customer.read"].description)
    async def crm_customer_read(customer_id: str) -> dict:
        return dispatch("crm.customer.read", {"customer_id": customer_id})

    @server.tool(name="crm.orders.list", description=TOOLS["crm.orders.list"].description)
    async def crm_orders_list(customer_id: str) -> dict:
        return dispatch("crm.orders.list", {"customer_id": customer_id})

    @server.tool(name="tickets.read", description=TOOLS["tickets.read"].description)
    async def tickets_read(ticket_id: str) -> dict:
        return dispatch("tickets.read", {"ticket_id": ticket_id})

    @server.tool(name="tickets.reply.draft", description=TOOLS["tickets.reply.draft"].description)
    async def tickets_reply_draft(ticket_id: str, body: str) -> dict:
        return dispatch("tickets.reply.draft", {"ticket_id": ticket_id, "body": body})

    @server.tool(name="refunds.quote", description=TOOLS["refunds.quote"].description)
    async def refunds_quote(order_id: str) -> dict:
        return dispatch("refunds.quote", {"order_id": order_id})

    @server.tool(name="refunds.issue", description=TOOLS["refunds.issue"].description)
    async def refunds_issue(order_id: str, amount: float, approval_id: str | None = None) -> dict:
        args: dict[str, Any] = {"order_id": order_id, "amount": amount}
        if approval_id:
            args["approval_id"] = approval_id
        return dispatch("refunds.issue", args)

    @server.tool(name="privacy.pii.read", description=TOOLS["privacy.pii.read"].description)
    async def privacy_pii_read(customer_id: str) -> dict:
        return dispatch("privacy.pii.read", {"customer_id": customer_id})

    return server


class _TokenMiddleware:
    """ASGI middleware: lift the bearer token into a context variable."""

    def __init__(self, app: Any):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        reset = _token.set(auth.removeprefix("Bearer ").strip() or None)
        reset_workload = _workload_token.set(headers.get("x-workload-token") or None)
        try:
            await self._app(scope, receive, send)
        finally:
            _workload_token.reset(reset_workload)
            _token.reset(reset)


def build_mcp_asgi_app(enforcer: ToolEnforcer | None = None) -> Any:
    """Return an ASGI app serving MCP over Streamable HTTP."""
    server = build_mcp_server(enforcer)
    return _TokenMiddleware(server.streamable_http_app())
