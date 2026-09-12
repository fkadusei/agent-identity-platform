"""HTTP transport for the tools — the Phase 1 interface.

The MCP transport (app/tools/mcp_server.py) exposes the same tools over the
Model Context Protocol; both delegate to the identical enforcement core, so the
security behaviour is the same either way.
"""
from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

from app.tools.catalog import TOOLS
from app.tools.enforcement import Outcome, ToolEnforcer
from app.tools.wiring import build_enforcer

app = FastAPI(title="agent tools (policy enforcement point)")

_enforcer: ToolEnforcer | None = None


def enforcer() -> ToolEnforcer:
    global _enforcer
    if _enforcer is None:
        _enforcer = build_enforcer()
    return _enforcer


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/tools")
def list_tools() -> list[dict]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "risk": t.risk,
            "input_schema": t.input_schema,
        }
        for t in TOOLS.values()
    ]


@app.post("/tools/{tool_name}")
def call_tool(
    tool_name: str,
    args: dict,
    authorization: str | None = Header(default=None),
) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip() or None
    result = enforcer().call(token, tool_name, args)

    if result.outcome is Outcome.OK:
        return {"tool": result.tool, "decision": result.decision, "result": result.result}
    if result.outcome is Outcome.DENIED:
        raise HTTPException(status_code=403, detail=result.reason)
    if result.outcome is Outcome.APPROVAL_REQUIRED:
        # 428 Precondition Required: the action is valid but needs a human.
        raise HTTPException(status_code=428, detail=result.reason)
    raise HTTPException(status_code=400, detail=result.reason)
