"""Tool selection: a role's forbidden tools are refused, never substituted.

The bug this guards: with the forbidden tools hidden from the model, a small
model picks a *different, allowed* tool and the run reports success — so "issue a
refund" silently becomes "list orders".
"""
from __future__ import annotations

from app.agent import llm
from app.tools.catalog import TOOLS

ALLOWED = {"crm.customer.read": TOOLS["crm.customer.read"]}
FORBIDDEN = {"refunds.issue": TOOLS["refunds.issue"]}


def test_a_forbidden_tool_is_refused_not_substituted(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda _p: '{"tool": "refunds.issue", "args": {"amount": 500}}')
    got = llm.decide_tool("issue a refund of 500", ALLOWED, FORBIDDEN)
    assert got["tool"] is None
    assert "may not call refunds.issue" in got["reason"]


def test_a_declined_task_gets_a_clear_message(monkeypatch):
    # A small model echoes a tool *description* as its reason, which says nothing
    # useful ("High-risk: policy may require approval"). We compose the message.
    monkeypatch.setattr(
        llm, "_chat", lambda _p: '{"tool": null, "reason": "High-risk: policy may require approval"}'
    )
    got = llm.decide_tool("issue a refund of 500", ALLOWED, FORBIDDEN)
    assert got["tool"] is None
    assert got["reason"] == "no tool your role may call fits this task — nothing was executed"


def test_an_allowed_tool_is_chosen(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda _p: '{"tool": "crm.customer.read", "args": {"customer_id": "c-100"}}')
    got = llm.decide_tool("look up c-100", ALLOWED, FORBIDDEN)
    assert got["tool"] == "crm.customer.read"


def test_the_prompt_names_the_forbidden_tools(monkeypatch):
    seen: dict = {}

    def fake_chat(prompt: str) -> str:
        seen["prompt"] = prompt
        return '{"tool": null, "reason": "no"}'

    monkeypatch.setattr(llm, "_chat", fake_chat)
    llm.decide_tool("issue a refund", ALLOWED, FORBIDDEN)
    # The model must be told what it may NOT use, or it substitutes.
    assert "NOT permitted" in seen["prompt"]
    assert "refunds.issue" in seen["prompt"]


def test_a_refusal_says_so(monkeypatch):
    # "refused" is what lets the caller tell "the agent declined to act" from
    # "something is broken" — and refused_tool is the only case where we can name
    # what was asked for, because the model named a real tool it may not call.
    monkeypatch.setattr(llm, "_chat", lambda _p: '{"tool": "refunds.issue", "args": {}}')
    got = llm.decide_tool("issue a refund of 500", ALLOWED, FORBIDDEN)
    assert got["refused"] is True
    assert got["refused_tool"] == "refunds.issue"


def test_a_decline_is_a_refusal_with_nothing_to_name(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda _p: '{"tool": null, "reason": "no"}')
    got = llm.decide_tool("issue a refund of 500", ALLOWED, FORBIDDEN)
    assert got["refused"] is True
    assert "refused_tool" not in got


def test_a_model_call_failure_blames_the_infrastructure(monkeypatch):
    """A model that was never reached must not be reported as choosing badly.

    On 2026-09-16 an expired SVID made every model call raise, and the run said
    "the model did not choose a usable tool" — so the search went to the prompt
    and the model instead of the certificate. Same plea as the ticket: the
    message has to name the real fault.
    """
    import ssl

    def expired_certificate(_prompt: str) -> str:
        raise ssl.SSLCertVerificationError("certificate has expired")

    monkeypatch.setattr(llm, "_chat", expired_certificate)
    got = llm.decide_tool("look up c-100", ALLOWED, FORBIDDEN)
    assert got["tool"] is None
    assert got["cause"] == "unreachable"
    assert "could not be reached" in got["reason"]
    assert "did not choose" not in got["reason"]
    # Not a refusal: graph.mark maps this to "error", not "refused".
    assert "refused" not in got


def test_a_model_call_failure_is_audited_with_its_cause(monkeypatch):
    from agentnhi import set_sink

    def connection_refused(_prompt: str) -> str:
        raise OSError("connection refused")

    captured: list[dict] = []
    monkeypatch.setattr(llm, "_chat", connection_refused)
    set_sink(captured.append)
    try:
        llm.decide_tool("look up c-100", ALLOWED, FORBIDDEN)
    finally:
        set_sink(None)
    events = [r for r in captured if r.get("event") == "llm.fallback"]
    assert events and events[-1]["cause"] == "unreachable"


def test_an_unparseable_reply_is_told_apart_from_a_bad_choice(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda _p: "sorry, I cannot help with that")
    got = llm.decide_tool("look up c-100", ALLOWED, FORBIDDEN)
    assert got["cause"] == "unparseable"
    assert "could not be understood" in got["reason"]


# ---------------------------------------------------------------------------
# S20 — an identifier the model has not seen is asked for, not acted on
# ---------------------------------------------------------------------------
REFUND = {"refunds.issue": TOOLS["refunds.issue"]}


def test_an_invented_identifier_becomes_a_question(monkeypatch):
    """The reported bug, as a test.

    The task names no order, and the model answers with the *field name* as the
    value — which the presence check alone would have accepted, sending a refund
    for an order called "order_id" to a manager for approval.
    """
    monkeypatch.setattr(
        llm, "_chat", lambda _p: '{"tool": "refunds.issue", "args": {"order_id": "order_id", "amount": 200}}'
    )
    got = llm.decide_tool("Issue a refund of 200 dollars for order ", REFUND)
    assert got["tool"] == "refunds.issue"
    assert got["clarify"] is True
    assert got["missing"] == ["order_id"]


def test_the_task_named_the_order_so_the_models_guess_is_replaced(monkeypatch):
    monkeypatch.setattr(
        llm, "_chat", lambda _p: '{"tool": "refunds.issue", "args": {"order_id": "o-9999", "amount": 200}}'
    )
    got = llm.decide_tool("Issue a refund of 200 dollars for order o-1001", REFUND)
    assert got["args"]["order_id"] == "o-1001"
    assert "missing" not in got


def test_a_word_from_the_task_is_not_an_identifier(monkeypatch):
    """Found by retrying against the model, after the first fix.

    The task says "for order " — so a model answering `"order_id": "order"` had used
    a word the task contains, and passed a check that searched the text. Identifiers
    are compared as a set of identifier-*shaped* tokens, not as a substring.
    """
    monkeypatch.setattr(
        llm, "_chat", lambda _p: '{"tool": "refunds.issue", "args": {"order_id": "order", "amount": 200}}'
    )
    got = llm.decide_tool("Issue a refund of 200 dollars for order ", REFUND)
    assert got["clarify"] is True
    assert got["missing"] == ["order_id"]


def test_an_identifier_read_in_an_earlier_call_is_allowed(monkeypatch):
    # The multi-step case: the id came from a tool result, so it was seen (S19).
    monkeypatch.setattr(
        llm, "_chat", lambda _p: '{"tool": "crm.customer.read", "args": {"customer_id": "c-100"}}'
    )
    observations = [
        {"tool": "tickets.read", "args": {"ticket_id": "t-1"}, "result": {"customer_id": "c-100"}}
    ]
    got = llm.decide_tool(
        "read the customer from ticket t-1",
        {"crm.customer.read": TOOLS["crm.customer.read"]},
        observations=observations,
    )
    assert got["tool"] == "crm.customer.read"
    assert got["args"]["customer_id"] == "c-100"
    assert "clarify" not in got


def test_an_identifier_the_model_saw_nowhere_is_audited(monkeypatch):
    from agentnhi import set_sink

    captured: list[dict] = []
    monkeypatch.setattr(
        llm, "_chat", lambda _p: '{"tool": "refunds.issue", "args": {"order_id": "o-1234", "amount": 5}}'
    )
    set_sink(captured.append)
    try:
        llm.decide_tool("refund five dollars", REFUND)
    finally:
        set_sink(None)
    events = [r for r in captured if r.get("event") == "llm.identifier_invented"]
    assert events and events[-1]["args"] == "order_id"
    # The value is not recorded — the point is the behaviour, not the guess.
    assert "o-1234" not in str(events[-1])
