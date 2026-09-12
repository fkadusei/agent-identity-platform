"""MCP transport for the tools.

Exposes the same catalogue over the Model Context Protocol (Streamable HTTP),
delegating to the identical enforcement core as the HTTP transport. Tool schemas
are generated from the catalogue's JSON schemas.

Authentication: the caller presents its exchanged token as a bearer token. An
ASGI middleware lifts it into a context variable, which the generated tool
handlers read; the enforcer then verifies it as usual.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from mcp.server.mcpserver import MCPServer

from app.tools.catalog import TOOLS, Tool
from app.tools.enforcement import Outcome, ToolEnforcer
from app.tools.wiring import build_enforcer

_token: ContextVar[str | None] = ContextVar("agent_token", default=None)

_PY_TYPES = {"string": "str", "number": "float", "integer": "int", "boolean": "bool"}


def _py_type(json_type: str | None) -> str:
    return _PY_TYPES.get(json_type or "string", "str")


def _make_handler(tool: Tool, enforcer: ToolEnforcer):
    """Build a typed async handler so MCP can infer the tool's schema."""
    properties = tool.input_schema.get("properties") or {}
    required = set(tool.input_schema.get("required") or [])

    params = []
    for name, spec in properties.items():
        annotation = _py_type(spec.get("type"))
        params.append(
            f"{name}: {annotation}" if name in required else f"{name}: {annotation} | None = None"
        )
    kwargs = ", ".join(f'"{name}": {name}' for name in properties)

    source = (
        f"async def handler({', '.join(params)}) -> dict:\n"
        f"    return _dispatch({tool.name!r}, {{{kwargs}}})\n"
    )
    namespace = {"_dispatch": lambda name, args: _dispatch(enforcer, name, args)}
    exec(source, namespace)  # noqa: S102 - generated from our own trusted catalogue
    return namespace["handler"]


def _dispatch(enforcer: ToolEnforcer, name: str, args: dict) -> dict:
    result = enforcer.call(_token.get(), name, args)
    if result.outcome is Outcome.OK:
        return result.result or {}
    return {"status": result.outcome.value, "reason": result.reason}


def build_mcp_server(enforcer: ToolEnforcer | None = None) -> MCPServer:
    enforcer = enforcer or build_enforcer()
    server = MCPServer("agent-tools")
    for tool in TOOLS.values():
        server.add_tool(
            _make_handler(tool, enforcer),
            name=tool.name,
            description=tool.description,
        )
    return server


class _TokenMiddleware:
    """ASGI middleware: lift the bearer token into a context variable."""

    def __init__(self, app: Any):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        headers = {
            k.decode().lower(): v.decode() for k, v in scope.get("headers", [])
        }
        auth = headers.get("authorization", "")
        reset = _token.set(auth.removeprefix("Bearer ").strip() or None)
        try:
            await self._app(scope, receive, send)
        finally:
            _token.reset(reset)


def build_mcp_asgi_app(enforcer: ToolEnforcer | None = None) -> Any:
    """Return an ASGI app serving MCP over Streamable HTTP."""
    server = build_mcp_server(enforcer)
    return _TokenMiddleware(server.streamable_http_app())
