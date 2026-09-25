"""The agent graph: happy path, denial, the approval interrupt, and the ask."""
from __future__ import annotations

from app.agent.deps import ScriptedDeps, ToolCallResult
from app.agent.graph import MAX_ASKS, MAX_STEPS, build_agent, resume_task, run_task

PLAN = {"tool": "refunds.issue", "args": {"order_id": "o-1001", "amount": 200}, "reason": "refund"}
ASK = {
    "tool": "refunds.issue",
    "args": {"order_id": "o-1001"},
    "missing": ["amount"],
    "clarify": True,
    "reason": "refunds.issue needs amount",
}


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

    resumed = resume_task(agent, "t-3", {"approved": True})
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

    resumed = resume_task(agent, "t-4", {"approved": False})
    assert resumed["status"] == "denied"
    # The tool was attempted once (which triggered the approval), not twice.
    assert len(deps.calls) == 1


# ---------------------------------------------------------------------------
# S18 — a missing argument is a question, not a dead end
# ---------------------------------------------------------------------------
def test_a_missing_argument_pauses_and_asks():
    deps = ScriptedDeps(ASK, [])
    out = run_task(build_agent(deps), "refund the order", "t-ask", "user-token")
    assert out["status"] == "clarification_required"
    assert out["missing"] == ["amount"]
    assert out["tool"] == "refunds.issue"
    # Nothing was executed and nothing was authorized: the run is simply paused.
    assert deps.calls == []
    assert deps.approvals_created == 0


def test_the_answer_is_merged_and_the_call_proceeds():
    deps = ScriptedDeps(ASK, [ToolCallResult("ok", result={"id": "r-0003"})])
    agent = build_agent(deps)

    paused = run_task(agent, "refund the order", "t-ask2", "user-token")
    assert paused["status"] == "clarification_required"

    out = resume_task(agent, "t-ask2", {"values": {"amount": "200"}})
    assert out["status"] == "ok"
    assert out["result"] == {"id": "r-0003"}
    # The value the person supplied — not one the model invented — reached the
    # same enforcement path as any other argument.
    assert deps.calls[0]["args"] == {"order_id": "o-1001", "amount": "200"}


def test_an_answer_is_not_an_approval():
    """The property that makes clarification safe to offer at all.

    A person supplying the amount is *information*. It does not settle anything:
    the call still goes to policy, which may still hold it for approval.
    """
    deps = ScriptedDeps(
        ASK,
        [
            ToolCallResult("approval_required", reason="needs manager"),
            ToolCallResult("ok", result={"id": "r-0004"}),
        ],
    )
    agent = build_agent(deps)

    run_task(agent, "refund the order", "t-ask3", "user-token")
    held = resume_task(agent, "t-ask3", {"values": {"amount": 200}})
    assert held["status"] == "approval_required"
    assert deps.approvals_created == 1

    done = resume_task(agent, "t-ask3", {"approved": True})
    assert done["status"] == "ok"
    assert deps.calls[1]["approval_id"] == "ap-scripted"


def test_an_unanswered_question_is_refused_not_looped_forever():
    deps = ScriptedDeps(ASK, [])
    agent = build_agent(deps)

    run_task(agent, "refund the order", "t-ask4", "user-token")
    # Ask again while the budget allows...
    for _ in range(MAX_ASKS - 1):
        again = resume_task(agent, "t-ask4", {"values": {}})
        assert again["status"] == "clarification_required"
    # ...then stop. A refusal, because nothing is broken — the agent simply will
    # not invent an identifier.
    out = resume_task(agent, "t-ask4", {"values": {}})
    assert out["status"] == "refused"
    assert "still needs amount" in out["reason"]
    assert deps.calls == []


def test_a_partial_answer_is_asked_for_again():
    two = {"tool": "refunds.issue", "args": {}, "missing": ["order_id", "amount"], "clarify": True}
    deps = ScriptedDeps(two, [ToolCallResult("ok", result={"id": "r-0005"})])
    agent = build_agent(deps)

    run_task(agent, "refund something", "t-ask5", "user-token")
    partial = resume_task(agent, "t-ask5", {"values": {"order_id": "o-1001"}})
    assert partial["status"] == "clarification_required"
    assert partial["missing"] == ["amount"]

    out = resume_task(agent, "t-ask5", {"values": {"amount": 25}})
    assert out["status"] == "ok"
    assert deps.calls[0]["args"] == {"order_id": "o-1001", "amount": 25}


# ---------------------------------------------------------------------------
# S19 — more than one step, but only when the model asks and only within budget
# ---------------------------------------------------------------------------
TICKET = {"tool": "tickets.read", "args": {"ticket_id": "t-1"}, "more": True}


def test_one_step_is_unchanged_when_the_model_does_not_ask_for_more():
    """The whole reason the loop is opt-in: a simple task stays one call, and its
    outcome stays `ok`, so nothing downstream has to learn a new state."""
    deps = ScriptedDeps(PLAN, [ToolCallResult("ok", result={"id": "r-0001"})])
    out = run_task(build_agent(deps), "refund o-1001", "t-single", "user-token")

    assert out["status"] == "ok"
    assert out["steps"] == 1
    assert len(deps.calls) == 1
    # And the model was only asked once.
    assert len(deps.observations_seen) == 1


def test_a_second_step_sees_what_the_first_one_returned():
    plans = [
        TICKET,
        {"tool": "refunds.issue", "args": {"order_id": "o-1001", "amount": 200}},
    ]
    deps = ScriptedDeps(
        {},
        [ToolCallResult("ok", result={"body": "my mug arrived broken"}),
         ToolCallResult("ok", result={"id": "r-0009"})],
        plans=plans,
    )
    out = run_task(build_agent(deps), "refund the order from the last ticket", "t-two", "tok")

    assert out["status"] == "ok"
    assert out["result"] == {"id": "r-0009"}
    assert out["steps"] == 2
    assert [c["tool"] for c in deps.calls] == ["tickets.read", "refunds.issue"]
    # The second decision was made with the first call's result in hand — that is
    # the entire feature: without it the model is guessing.
    assert deps.observations_seen[0] == []
    assert deps.observations_seen[1][0]["tool"] == "tickets.read"
    assert deps.observations_seen[1][0]["result"] == {"body": "my mug arrived broken"}


def test_the_loop_stops_at_the_step_budget():
    def step(i: int) -> dict:
        return {"tool": "crm.customer.read", "args": {"customer_id": f"c-{i}"}, "more": True}

    deps = ScriptedDeps(
        {},
        [ToolCallResult("ok", result={"n": i}) for i in range(MAX_STEPS + 2)],
        plans=[step(i) for i in range(MAX_STEPS + 2)],
    )
    out = run_task(build_agent(deps), "keep going", "t-budget", "tok")

    assert out["status"] == "ok"
    assert out["steps"] == MAX_STEPS
    assert len(deps.calls) == MAX_STEPS
    # It is not asked for a fourth decision: the budget stops the run, not the model.
    assert len(deps.observations_seen) == MAX_STEPS


def test_the_same_call_is_not_made_twice():
    """A repeat would be a second real action for no new information — a second
    refund. The check is in the node that acts, so it cannot be routed around."""
    same = {"tool": "refunds.issue", "args": {"order_id": "o-1001", "amount": 200}, "more": True}
    deps = ScriptedDeps(
        same,
        [ToolCallResult("ok", result={"id": "r-0001"}), ToolCallResult("ok", result={"id": "r-0002"})],
    )
    out = run_task(build_agent(deps), "refund it twice", "t-dup", "tok")

    assert len(deps.calls) == 1
    assert out["status"] == "ok"
    assert out["result"] == {"id": "r-0001"}
    assert "already made" in out["reason"]


def test_an_approval_inside_the_loop_does_not_end_the_run():
    """The pause is a step in the middle, not the end of the task: once decided,
    the loop carries on with what it has learned."""
    plans = [
        TICKET,
        {"tool": "refunds.issue", "args": {"order_id": "o-1001", "amount": 200}, "more": True},
        {"tool": "tickets.read", "args": {"ticket_id": "t-1"}},
    ]
    deps = ScriptedDeps(
        {},
        [
            ToolCallResult("ok", result={"body": "broken mug"}),
            ToolCallResult("approval_required", reason="needs manager"),
            ToolCallResult("ok", result={"id": "r-0010"}),
            ToolCallResult("ok", result={"body": "broken mug"}),
        ],
        plans=plans,
    )
    agent = build_agent(deps)

    # Step 1 happens, step 2 is held, and the run surfaces the hold.
    held = run_task(agent, "refund the order from the ticket, then check it", "t-loop", "tok")
    assert held["status"] == "approval_required"
    assert deps.approvals_created == 1

    final = resume_task(agent, "t-loop", {"approved": True})
    assert final["status"] == "ok"
    # Three *steps* (calls that happened), across four attempts at the tool
    # server — the held one repeated with its approval, which is not a step and
    # not an observation, so the no-repeat guard correctly lets it through.
    assert final["steps"] == 3
    assert [c["tool"] for c in deps.calls] == [
        "tickets.read",
        "refunds.issue",
        "refunds.issue",
        "tickets.read",
    ]
    assert deps.calls[1]["approval_id"] is None
    assert deps.calls[2]["approval_id"] == "ap-scripted"


class _RaisingDeps:
    """A downstream failure (e.g. a refused token exchange) must not 500."""

    def decide(self, task: str, observations=None) -> dict:
        return PLAN

    def call_tool(self, *_args, **_kwargs):
        raise RuntimeError("token exchange failed (403)")

    def create_approval(self, *_args, **_kwargs):
        raise RuntimeError("unreachable")


def test_downstream_failure_is_reported_not_raised():
    out = run_task(build_agent(_RaisingDeps()), "refund o-1001", "t-5", "user-token")
    assert out["status"] == "error"
    assert "token exchange failed" in out["reason"]


def test_a_refusal_is_not_an_error():
    # To whoever is on call these are different events: a refusal is the agent
    # declining to act, an error is something being broken.
    plan = {
        "tool": None,
        "reason": "your role may not call privacy.pii.read",
        "refused": True,
        "refused_tool": "privacy.pii.read",
    }
    out = run_task(build_agent(ScriptedDeps(plan, [])), "read the PII", "t-refuse", "user-token")
    assert out["status"] == "refused"
    assert out["refused_tool"] == "privacy.pii.read"
    assert out["reason"] == "your role may not call privacy.pii.read"


def test_an_unusable_model_answer_is_an_error():
    plan = {"tool": None, "reason": "the model did not choose a usable tool"}
    out = run_task(build_agent(ScriptedDeps(plan, [])), "anything", "t-broken", "user-token")
    assert out["status"] == "error"
