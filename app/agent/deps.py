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
    def decide(self, task: str, observations: list[dict] | None = None) -> dict:
        """Return {"tool": ..., "args": {...}, "reason": ...} for the task.

        `observations` is what earlier tool calls in this run returned, in order —
        empty on the first pass. A second pass is only ever asked for when the
        model asked for it (see `more` in graph.py), so this stays optional.
        """
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
    """Deterministic deps: a fixed plan, or a queue of plans, plus tool responses.

    `plans` is what makes a multi-step run testable: the graph asks for a decision
    once per step, and each call returns the next scripted answer. Without it the
    same plan comes back every time, which is exactly the loop the step budget
    exists to bound.
    """

    def __init__(
        self,
        plan: dict,
        responses: list[ToolCallResult],
        plans: list[dict] | None = None,
    ):
        self._plan = plan
        self._plans = list(plans) if plans is not None else None
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.approvals_created = 0
        # What the model was shown on each pass — so a test can assert the run
        # actually fed its own result back.
        self.observations_seen: list[list[dict]] = []

    def decide(self, task: str, observations: list[dict] | None = None) -> dict:
        self.observations_seen.append(list(observations or []))
        if self._plans:
            return dict(self._plans.pop(0))
        return dict(self._plan)

    def call_tool(self, tool: str, args: dict, approval_id: str | None) -> ToolCallResult:
        self.calls.append({"tool": tool, "args": args, "approval_id": approval_id})
        if self._responses:
            return self._responses.pop(0)
        return ToolCallResult("error", reason="no scripted response")

    def create_approval(self, tool: str, args: dict, reason: str) -> dict:
        self.approvals_created += 1
        return {"id": "ap-scripted", "tool": tool, "args": args, "reason": reason}
