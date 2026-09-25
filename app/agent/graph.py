"""The agent as a stateful graph with a human-approval interrupt.

    plan ──▶ call_tool ──▶ (ok / denied / error) ──▶ END
                 │
                 ├─ approval_required ──▶ create_approval ──▶ await_decision
                 │                                                  │
                 │                     approved ──▶ call_tool ◀──────┤
                 │                     denied   ──▶ END        ◀──────┘
                 │
                 └─ missing an argument ──▶ ask_clarification ──▶ call_tool
                                                  ▲              │
                                                  └── still missing ┘

The LLM chooses *what* to attempt; the tool's enforcement point decides whether
it happens. When policy says `require_approval`, the graph pauses — the run is
checkpointed — and resumes only when a human decision is recorded. When the model
cannot supply a required argument, the graph pauses the same way and asks for it
(S18): an answer is information, not authorization, so it is merged into the
arguments and the call still goes to policy.

`create_approval` is a separate node from `await_decision` on purpose: the
interrupt node re-executes on resume, so it must have no side effects.
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agent.deps import AgentDeps

# How many times the agent may ask for the same missing arguments before it gives
# up. Two, because a partial answer is common; more than that is a person being
# asked to guess what the machine wants.
MAX_ASKS = 2


class AgentState(TypedDict, total=False):
    task: str
    tool: str
    args: dict
    reason: str
    status: str  # ok | denied | refused | error | approval_required | approved | clarification_required
    refused_tool: str  # what the model asked for, when we know
    result: dict
    approval_id: str
    missing: list[str]  # required arguments still to be supplied by a person
    asks: int  # how many times we have asked for them


def build_agent(deps: AgentDeps, checkpointer: Any | None = None):
    """Compile the agent graph. Pass a persistent checkpointer in production."""

    def plan(state: AgentState) -> dict:
        decision = deps.decide(state["task"])
        if decision.get("clarify"):
            # The model named a tool it may use and lacked an argument a person
            # can supply. Ask, rather than refuse — but note what this does *not*
            # do: it never fills the value, and it never authorizes anything. The
            # answer is merged into args and the call still goes to policy.
            return {
                "tool": decision["tool"],
                "args": decision.get("args", {}),
                "missing": list(decision.get("missing") or []),
                "asks": state.get("asks", 0),
                "status": "clarification_required",
                "reason": decision.get("reason", ""),
            }
        if not decision.get("tool"):
            # The model produced no usable decision. Do NOT quietly do something
            # else — a refund request must never turn into a customer lookup.
            #
            # "refused" and "error" are different things to whoever is on call:
            # a refusal is the agent declining to act (the role may not call what
            # was asked for), an error is something being broken (the tool server
            # or the model was unreachable).
            return {
                "status": "refused" if decision.get("refused") else "error",
                "reason": decision.get("reason", "no tool was selected"),
                "refused_tool": decision.get("refused_tool", ""),
            }
        return {
            "tool": decision["tool"],
            "args": decision.get("args", {}),
            "reason": decision.get("reason", ""),
        }

    def call_tool(state: AgentState) -> dict:
        # A downstream failure (e.g. the token exchange is refused) must become a
        # reported error, not an unhandled exception that 500s the request.
        try:
            outcome = deps.call_tool(state["tool"], state["args"], state.get("approval_id"))
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "reason": f"tool call failed: {exc}"}
        return {"status": outcome.status, "result": outcome.result or {}, "reason": outcome.reason}

    def create_approval(state: AgentState) -> dict:
        try:
            approval = deps.create_approval(state["tool"], state["args"], state.get("reason", ""))
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "reason": f"could not request approval: {exc}"}
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

    def ask_clarification(state: AgentState) -> dict:
        """Pause for the arguments only a person can supply.

        Pure, like `await_decision`: the interrupt re-executes on resume, so this
        must not write anything the second time around.
        """
        answer = interrupt(
            {
                "type": "clarification_required",
                "tool": state["tool"],
                "args": state["args"],
                "missing": list(state.get("missing") or []),
            }
        )
        supplied = (answer or {}).get("values") or {}
        # Empty strings count as no answer: a blank form is not a value.
        args = {**state["args"], **{k: v for k, v in supplied.items() if v not in (None, "")}}
        remaining = [name for name in state.get("missing", []) if args.get(name) in (None, "")]
        asks = state.get("asks", 0) + 1
        if not remaining:
            return {"args": args, "missing": [], "asks": asks}
        if asks < MAX_ASKS:
            # A partial answer is worth one more question — asking is cheaper and
            # kinder than refusing on a technicality.
            return {"args": args, "missing": remaining, "asks": asks}
        # Out of asks. This is a refusal, not an error: nothing is broken, the
        # agent simply will not invent an identifier.
        return {
            "args": args,
            "missing": remaining,
            "asks": asks,
            "status": "refused",
            "reason": (
                f"{state['tool']} still needs {', '.join(remaining)} "
                "after asking — nothing was executed"
            ),
        }

    def after_call(state: AgentState) -> str:
        return "create_approval" if state.get("status") == "approval_required" else END

    def after_create(state: AgentState) -> str:
        return END if state.get("status") == "error" else "await_decision"

    def after_decision(state: AgentState) -> str:
        return "call_tool" if state.get("status") == "approved" else END

    def after_plan(state: AgentState) -> str:
        status = state.get("status")
        if status in ("error", "refused"):
            return END
        if status == "clarification_required":
            return "ask_clarification"
        return "call_tool"

    def after_clarification(state: AgentState) -> str:
        # The node leaves `missing` non-empty only while there is an ask left, so
        # the order of these two checks is what keeps the budget honest.
        if state.get("status") == "refused":
            return END
        return "ask_clarification" if state.get("missing") else "call_tool"

    graph = StateGraph(AgentState)
    graph.add_node("plan", plan)
    graph.add_node("call_tool", call_tool)
    graph.add_node("create_approval", create_approval)
    graph.add_node("await_decision", await_decision)
    graph.add_node("ask_clarification", ask_clarification)

    graph.add_edge(START, "plan")
    graph.add_conditional_edges(
        "plan",
        after_plan,
        {"call_tool": "call_tool", "ask_clarification": "ask_clarification", END: END},
    )
    graph.add_conditional_edges(
        "call_tool", after_call, {"create_approval": "create_approval", END: END}
    )
    graph.add_conditional_edges(
        "create_approval", after_create, {"await_decision": "await_decision", END: END}
    )
    graph.add_conditional_edges(
        "await_decision", after_decision, {"call_tool": "call_tool", END: END}
    )
    graph.add_conditional_edges(
        "ask_clarification",
        after_clarification,
        {"call_tool": "call_tool", "ask_clarification": "ask_clarification", END: END},
    )

    return graph.compile(checkpointer=checkpointer or InMemorySaver())


def run_task(agent, task: str, thread_id: str, user_token: str) -> dict:
    """Start a run. Returns the final state, or an approval-required payload."""
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke({"task": task}, config=config)
    return _shape(result)


def resume_task(agent, thread_id: str, decision: dict) -> dict:
    """Resume a paused run with a human's answer.

    One method for both pauses: an approval sends `{"approved": bool}`, a
    clarification sends `{"values": {...}}`. The run's state is durable; the
    token to act with is not, which is why the caller passes it again.
    """
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke(Command(resume=decision), config=config)
    return _shape(result)


def _shape(state: dict) -> dict:
    interrupts = state.get("__interrupt__") or ()
    if interrupts:
        payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
        if isinstance(payload, dict):
            # The payload's own type decides the status: an approval and a
            # clarification both pause the run, but they are different things to
            # the caller — one settles a permission, the other supplies a fact.
            return {"status": payload.get("type", "approval_required"), **payload}
        return {"status": "approval_required"}
    return {
        "status": state.get("status", "unknown"),
        "tool": state.get("tool"),
        "result": state.get("result", {}),
        "reason": state.get("reason", ""),
        "refused_tool": state.get("refused_tool", ""),
    }
