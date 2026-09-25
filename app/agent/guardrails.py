"""Guardrails: what the agent may be *asked*, and what it may *decide*.

Policy constrains what the agent may **do** — the tool server enforces that, and
it is the control. These guardrails cover the two edges policy never sees:

* the **task** handed to the agent, before any model call;
* the model's **decision**, before any tool call.

They are deliberately small and deterministic. The point is not to out-think a
model — it is to refuse the obvious cases cheaply, audibly, and without relying on
a 3B model to ignore a bad instruction.

A decision missing a required argument is the one case that is not a refusal: the
value exists, it is just held by the person who asked for the work, so the run
asks for it (S18) rather than inventing one.
"""
from __future__ import annotations

from app.tools.catalog import Tool

# A task longer than this is not a task, it is an attempt to stuff the context.
MAX_TASK_CHARS = 2000

# Phrases that only make sense as an attempt to override the instructions. This is
# defence in depth: policy still decides what may run.
_INJECTION_PHRASES = (
    "ignore previous instructions",
    "ignore all previous",
    "ignore the above",
    "disregard previous",
    "disregard the above",
    "you are now",
    "reveal your instructions",
    "print your instructions",
    "show me your system prompt",
)


class GuardrailError(Exception):
    """The task or the decision was refused by a guardrail."""


def check_task(task: str) -> None:
    """Refuse a task that should never reach the model. Raises GuardrailError."""
    text = (task or "").strip()
    if not text:
        raise GuardrailError("the task is empty")
    if len(text) > MAX_TASK_CHARS:
        raise GuardrailError(
            f"the task is too long ({len(text)} characters, limit {MAX_TASK_CHARS})"
        )
    lowered = text.lower()
    for phrase in _INJECTION_PHRASES:
        if phrase in lowered:
            raise GuardrailError(
                "the task looks like an attempt to override the agent's "
                f"instructions ({phrase!r}) — refusing it"
            )


def check_decision(tool: Tool, args: dict) -> list[str]:
    """Return the required arguments the model did not supply (empty means fine).

    A missing argument is not a fault, and it is not a guess to be made: it is a
    value only the person asking for the work may have. Since S18 the caller asks
    for it instead of ending the run — so this returns the names rather than
    raising, and the graph decides. What must never happen is inventing the
    value, which is what makes "same argument, supplied by a human" safe to treat
    exactly like one the model produced.
    """
    required = (tool.input_schema or {}).get("required") or []
    return [name for name in required if args.get(name) in (None, "")]
