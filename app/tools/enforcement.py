"""The policy enforcement point.

Every tool call goes through :meth:`ToolEnforcer.call`, which:

1. **Verifies the token** — signature, issuer, audience, and the workload it was
   issued to (`azp`). A forwarded token never gets past this.
2. **Asks OPA** — allow / deny / require-approval, deny by default.
3. **Requires a real approval** when policy demands one — confirmed by the
   approvals service, not asserted by the caller.
4. **Executes** the tool only then, and records one audit line either way.

The agent's token is never used to call anything else; this component is where
"the LLM proposes, policy disposes" is actually enforced.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from agentnhi import Decision, PolicyClient, Settings, TokenRejected, TokenVerifier, audit

from app.common.schema import coerce_args
from app.common.telemetry import span
from app.tools.approvals import ApprovalsClient
from app.tools.catalog import TOOLS, Tool


class Outcome(str, Enum):
    OK = "ok"
    DENIED = "denied"
    APPROVAL_REQUIRED = "approval_required"
    ERROR = "error"


@dataclass(frozen=True)
class ToolResult:
    outcome: Outcome
    tool: str
    reason: str = ""
    decision: str | None = None
    result: dict | None = None


def _clean_args(tool: Tool, args: dict) -> dict:
    """Keep only the tool's declared arguments, coerced to their types."""
    return coerce_args(tool.input_schema.get("properties") or {}, args)


class ToolEnforcer:
    def __init__(
        self,
        settings: Settings,
        verifier: TokenVerifier,
        policy: PolicyClient,
        approvals: ApprovalsClient,
        tools: dict[str, Tool] | None = None,
    ):
        self._settings = settings
        self._verifier = verifier
        self._policy = policy
        self._approvals = approvals
        self._tools = tools if tools is not None else TOOLS

    def call(self, token: str | None, tool_name: str, args: dict) -> ToolResult:
        if not token:
            return ToolResult(Outcome.DENIED, tool_name, "no token presented")

        try:
            delegation = self._verifier.verify(token)
        except TokenRejected as exc:
            audit("tool.identity_rejected", tool=tool_name, reason=str(exc))
            return ToolResult(Outcome.DENIED, tool_name, f"identity rejected: {exc}")

        tool = self._tools.get(tool_name)
        if tool is None:
            audit("tool.unknown", tool=tool_name, sub=delegation.user)
            return ToolResult(Outcome.DENIED, tool_name, "unknown tool")

        call_args = _clean_args(tool, args)
        # A span carrying the identity, so a trace answers "which agent, for
        # which user, and what did policy decide?" — the same question the audit
        # log answers, but end to end.
        with span(
            "policy.decision",
            spiffe_id=delegation.workload,
            sub=delegation.user,
            tool=tool_name,
        ) as current:
            decision = self._policy.decide(
                agent=delegation.workload,
                user=delegation.user,
                tool=tool_name,
                context={"roles": list(delegation.roles), **call_args},
            )
            current.set_attribute("decision", decision.decision.value)
            current.set_attribute("reason", decision.reason)

        if decision.decision is Decision.DENY:
            audit(
                "tool.denied",
                spiffe_id=delegation.workload,
                sub=delegation.user,
                tool=tool_name,
                decision=decision.decision.value,
                reason=decision.reason,
            )
            return ToolResult(Outcome.DENIED, tool_name, decision.reason, decision.decision.value)

        if decision.decision is Decision.REQUIRE_APPROVAL:
            approval_id = args.get("approval_id")
            approved = bool(approval_id) and self._approvals.verify(
                str(approval_id),
                tool=tool_name,
                args=call_args,
                user=delegation.user,
                agent=delegation.workload,
            )
            if not approved:
                audit(
                    "tool.approval_required",
                    spiffe_id=delegation.workload,
                    sub=delegation.user,
                    tool=tool_name,
                    reason=decision.reason,
                )
                return ToolResult(
                    Outcome.APPROVAL_REQUIRED,
                    tool_name,
                    decision.reason,
                    decision.decision.value,
                )

        try:
            result = tool.handler(**call_args)
        except Exception as exc:  # noqa: BLE001 - report, do not crash the server
            audit(
                "tool.error",
                spiffe_id=delegation.workload,
                sub=delegation.user,
                tool=tool_name,
                reason=str(exc)[:200],
            )
            return ToolResult(Outcome.ERROR, tool_name, f"tool failed: {exc}")

        audit(
            "tool.allowed",
            spiffe_id=delegation.workload,
            sub=delegation.user,
            tool=tool_name,
            decision=decision.decision.value,
            reason=decision.reason,
        )
        return ToolResult(
            Outcome.OK,
            tool_name,
            decision.reason,
            decision=decision.decision.value,
            result=result if isinstance(result, dict) else {"result": result},
        )
