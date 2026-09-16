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
