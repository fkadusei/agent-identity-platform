"""The MCP transport exposes the same catalogue with inferred schemas."""
from __future__ import annotations

import asyncio

from agentnhi import Decision, Delegation, PolicyResult, Settings
from app.tools.catalog import TOOLS
from app.tools.enforcement import ToolEnforcer
from app.tools.mcp_server import build_mcp_server

AGENT = "spiffe://acme.com/ns/agent-nhi/sa/agent"


class _Verifier:
    def verify(self, token, **_kwargs):
        return Delegation(user="alice", workload=AGENT, audience="mcp-tools", roles=("support_rep",))


class _Policy:
    def decide(self, **_kwargs):
        return PolicyResult(Decision.ALLOW, "ok")


class _Approvals:
    def verify(self, *_a, **_k):
        return False


def _enforcer():
    return ToolEnforcer(
        settings=Settings(keycloak_issuer="http://kc", audience="mcp-tools", trusted_workload=AGENT),
        verifier=_Verifier(),
        policy=_Policy(),
        approvals=_Approvals(),
    )


def test_mcp_server_exposes_every_tool_with_a_schema():
    server = build_mcp_server(_enforcer())
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == set(TOOLS)
    for tool in tools:
        assert tool.description
        assert tool.input_schema is not None
