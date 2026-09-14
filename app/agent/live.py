"""Live dependencies: the real LLM, SPIFFE identity, and HTTP clients.

This is the production wiring behind the same :class:`AgentDeps` interface the
tests use. The agent holds no static credential: it fetches a short-lived SVID
and exchanges the user's token for an audience-scoped one per call.
"""
from __future__ import annotations

import os

import httpx

from agentnhi import Settings, TokenExchanger, audit
from agentnhi.identity import fetch_jwt_svid
from app.agent.deps import ToolCallResult
from app.agent.llm import decide_tool
from app.tools.catalog import TOOLS


class LiveDeps:
    def __init__(
        self,
        user_token: str,
        settings: Settings | None = None,
        tool_server_url: str | None = None,
        approvals_url: str | None = None,
        roles: tuple[str, ...] = (),
    ):
        self._user_token = user_token
        self._roles = tuple(roles)
        self._settings = settings or Settings.from_env()
        self._tool_server_url = (tool_server_url or os.environ.get("TOOL_SERVER_URL", "http://tools:8000")).rstrip("/")
        self._approvals_url = (approvals_url or os.environ.get("APPROVALS_URL", "http://api:8080")).rstrip("/")
        self._agent_id = os.environ.get("AGENT_SPIFFE_ID", "spiffe://acme.com/ns/agent-nhi/sa/agent")

    def _tool_token(self) -> str:
        """SVID -> exchange the user's token for one scoped to the tools."""
        svid = fetch_jwt_svid(self._settings.spiffe_socket, self._settings.keycloak_issuer)
        return TokenExchanger(self._settings).exchange(
            subject_token=self._user_token,
            client_id=self._agent_id,
            client_assertion=svid,
        )

    def allowed_tools(self) -> dict:
        """The catalogue filtered to what this caller's roles may call.

        Read from the policy, so the tools offered and the tools allowed cannot
        drift. Fails closed: if the policy is unreachable, no tools are offered.
        """
        from app.common.policy import tools_for_roles

        allowed = tools_for_roles(self._settings.opa_url, self._roles)
        return {name: tool for name, tool in TOOLS.items() if name in allowed}

    def decide(self, task: str) -> dict:
        return decide_tool(task, self.allowed_tools())

    def call_tool(self, tool: str, args: dict, approval_id: str | None) -> ToolCallResult:
        body = dict(args)
        if approval_id:
            body["approval_id"] = approval_id
        token = self._tool_token()
        try:
            resp = httpx.post(
                f"{self._tool_server_url}/tools/{tool}",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
        except httpx.HTTPError as exc:
            return ToolCallResult("error", reason=f"tool server unreachable: {exc}")

        if resp.status_code == 200:
            return ToolCallResult("ok", result=resp.json().get("result", {}))
        if resp.status_code == 428:
            return ToolCallResult("approval_required", reason=resp.json().get("detail", "approval required"))
        if resp.status_code == 403:
            return ToolCallResult("denied", reason=resp.json().get("detail", "denied"))
        return ToolCallResult("error", reason=f"unexpected status {resp.status_code}")

    def create_approval(self, tool: str, args: dict, reason: str) -> dict:
        token = self._tool_token()
        resp = httpx.post(
            f"{self._approvals_url}/approvals",
            json={"tool": tool, "args": args, "reason": reason},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        approval = resp.json()
        audit("approval.requested", approval_id=approval.get("id"), tool=tool)
        return approval
