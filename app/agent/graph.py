"""The agent as a stateful graph with a human-approval interrupt.

    plan ──▶ call_tool ──▶ (ok / denied / error) ──▶ END
                 │
                 └─ approval_required ──▶ create_approval ──▶ await_decision
                                                                   │
                                          approved ──▶ call_tool ◀──┤
                                          denied   ──▶ END      ◀──┘

The LLM chooses *what* to attempt; the tool's enforcement point decides whether
it happens. When policy says `require_approval`, the graph pauses — the run is
checkpointed — and resumes only when a human decision is recorded.

`create_approval` is a separate node from `await_decision` on purpose: the
interrupt node re-executes on resume, so it must have no side effects.
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agent.deps import AgentDeps


class AgentState(TypedDict, total=False):
    task: str
    tool: str
    args: dict
    reason: str
    status: str  # ok | denied | error | approval_required | approved
    result: dict
    approval_id: str


def build_agent(deps: AgentDeps, checkpointer: Any | None = None):
    """Compile the agent graph. Pass a persistent checkpointer in production."""

    def plan(state: AgentState) -> dict:
        decision = deps.decide(state["task"])
        return {
            "tool": decision["tool"],
            "args": decision.get("args", {}),
            "reason": decision.get("reason", ""),
        }

    def call_tool(state: AgentState) -> dict:
        outcome = deps.call_tool(state["tool"], state["args"], state.get("approval_id"))
        return {"status": outcome.status, "result": outcome.result or {}, "reason": outcome.reason}

    def create_approval(state: AgentState) -> dict:
        approval = deps.create_approval(state["tool"], state["args"], state.get("reason", ""))
        return {"approval_id": approval["id"]}

    def await_decision(state: AgentState) -> dict:
        decision = interrupt(
            {
                "type": "approval_required",
                "approval_id": state["approval_id"],
                "tool": state["tool"],
                "args": state["args"],
                "reason": state.get("reason", ""),
            }
        )
        approved = bool((decision or {}).get("approved"))
        return {"status": "approved" if approved else "denied"}

    def after_call(state: AgentState) -> str:
        return "create_approval" if state.get("status") == "approval_required" else END

    def after_decision(state: AgentState) -> str:
        return "call_tool" if state.get("status") == "approved" else END

    graph = StateGraph(AgentState)
    graph.add_node("plan", plan)
    graph.add_node("call_tool", call_tool)
    graph.add_node("create_approval", create_approval)
    graph.add_node("await_decision", await_decision)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "call_tool")
    graph.add_conditional_edges(
        "call_tool", after_call, {"create_approval": "create_approval", END: END}
    )
    graph.add_edge("create_approval", "await_decision")
    graph.add_conditional_edges(
        "await_decision", after_decision, {"call_tool": "call_tool", END: END}
    )

    return graph.compile(checkpointer=checkpointer or InMemorySaver())


def run_task(agent, task: str, thread_id: str, user_token: str) -> dict:
    """Start a run. Returns the final state, or an approval-required payload."""
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke({"task": task}, config=config)
    return _shape(result)


def resume_task(agent, thread_id: str, approved: bool) -> dict:
    """Resume a paused run with a human decision."""
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke(Command(resume={"approved": approved}), config=config)
    return _shape(result)


def _shape(state: dict) -> dict:
    interrupts = state.get("__interrupt__") or ()
    if interrupts:
        payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
        return {"status": "approval_required", **(payload if isinstance(payload, dict) else {})}
    return {
        "status": state.get("status", "unknown"),
        "tool": state.get("tool"),
        "result": state.get("result", {}),
        "reason": state.get("reason", ""),
    }
