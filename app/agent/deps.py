"""What the agent depends on, behind a narrow interface.

Keeping these as a protocol lets the graph be tested with fakes and keeps the
LLM, identity, and HTTP details out of the control flow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ToolCallResult:
    status: str  # "ok" | "denied" | "approval_required" | "error"
    result: dict | None = None
    reason: str = ""


class AgentDeps(Protocol):
    def decide(self, task: str) -> dict:
        """Return {"tool": ..., "args": {...}, "reason": ...} for the task."""
        ...

    def call_tool(self, tool: str, args: dict, approval_id: str | None) -> ToolCallResult:
        """Call the tool through the enforcement point."""
        ...

    def create_approval(self, tool: str, args: dict, reason: str) -> dict:
        """Create a pending approval request; return it (must include an id)."""
        ...


# ---------------------------------------------------------------------------
# A scripted implementation for tests and offline demos.
# ---------------------------------------------------------------------------
class ScriptedDeps:
    """Deterministic deps: a fixed plan and queued tool responses."""

    def __init__(self, plan: dict, responses: list[ToolCallResult]):
        self._plan = plan
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.approvals_created = 0

    def decide(self, task: str) -> dict:
        return dict(self._plan)

    def call_tool(self, tool: str, args: dict, approval_id: str | None) -> ToolCallResult:
        self.calls.append({"tool": tool, "args": args, "approval_id": approval_id})
        if self._responses:
            return self._responses.pop(0)
        return ToolCallResult("error", reason="no scripted response")

    def create_approval(self, tool: str, args: dict, reason: str) -> dict:
        self.approvals_created += 1
        return {"id": "ap-scripted", "tool": tool, "args": args, "reason": reason}
