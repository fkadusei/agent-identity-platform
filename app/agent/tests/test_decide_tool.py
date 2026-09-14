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


def test_a_declined_task_keeps_the_models_reason(monkeypatch):
    monkeypatch.setattr(
        llm, "_chat", lambda _p: '{"tool": null, "reason": "not permitted for your role"}'
    )
    got = llm.decide_tool("issue a refund of 500", ALLOWED, FORBIDDEN)
    assert got["tool"] is None
    assert got["reason"] == "not permitted for your role"


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
