"""The agent graph: happy path, denial, and the approval interrupt/resume."""
from __future__ import annotations

from app.agent.deps import ScriptedDeps, ToolCallResult
from app.agent.graph import build_agent, resume_task, run_task

PLAN = {"tool": "refunds.issue", "args": {"order_id": "o-1001", "amount": 200}, "reason": "refund"}


def test_happy_path_returns_the_result():
    deps = ScriptedDeps(PLAN, [ToolCallResult("ok", result={"id": "r-0001"})])
    agent = build_agent(deps)
    out = run_task(agent, "refund o-1001", "t-1", "user-token")
    assert out["status"] == "ok"
    assert out["result"] == {"id": "r-0001"}
    assert deps.approvals_created == 0


def test_denied_tool_stops_the_run():
    deps = ScriptedDeps(PLAN, [ToolCallResult("denied", reason="policy")])
    out = run_task(build_agent(deps), "refund o-1001", "t-2", "user-token")
    assert out["status"] == "denied"
    assert deps.approvals_created == 0


def test_approval_required_then_approved_executes():
    deps = ScriptedDeps(
        PLAN,
        [
            ToolCallResult("approval_required", reason="needs manager"),
            ToolCallResult("ok", result={"id": "r-0002"}),
        ],
    )
    agent = build_agent(deps)

    paused = run_task(agent, "refund o-1001", "t-3", "user-token")
    assert paused["status"] == "approval_required"
    assert paused["approval_id"] == "ap-scripted"
    assert deps.approvals_created == 1

    resumed = resume_task(agent, "t-3", approved=True)
    assert resumed["status"] == "ok"
    assert resumed["result"] == {"id": "r-0002"}

    # The second tool call carried the approval id; the first did not.
    assert deps.calls[0]["approval_id"] is None
    assert deps.calls[1]["approval_id"] == "ap-scripted"
    # create_approval ran once, not again on resume.
    assert deps.approvals_created == 1


def test_approval_denied_does_not_execute():
    deps = ScriptedDeps(PLAN, [ToolCallResult("approval_required", reason="needs manager")])
    agent = build_agent(deps)
    run_task(agent, "refund o-1001", "t-4", "user-token")

    resumed = resume_task(agent, "t-4", approved=False)
    assert resumed["status"] == "denied"
    # The tool was attempted once (which triggered the approval), not twice.
    assert len(deps.calls) == 1
