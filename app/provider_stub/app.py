"""A tiny OpenAI-compatible provider, for exercising the hosted path (S17).

It stands in for a cloud provider so the gateway's hosted branch can be run end
to end with nobody's key. It is deliberately strict about the two things S17
fixed:

* it requires a ``model``, like every real provider — a request with none is a
  400, which is exactly what the gateway used to send;
* with ``STUB_STRICT=1`` it rejects ``response_format``, so stripping it (the
  gateway's ``LLM_STRIP_RESPONSE_FORMAT``) can be shown to matter;
* if ``STUB_API_KEY`` is set it requires it as a bearer, proving the gateway
  sends the key.

It answers with a plausible tool decision parsed from the prompt, so a real agent
run completes through it. It is a test double, not a model.
"""
from __future__ import annotations

import json
import os
import re

from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI(title="stub OpenAI-compatible provider")


def _check_key(authorization: str | None) -> None:
    key = os.environ.get("STUB_API_KEY", "")
    if not key:
        return
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token != key:
        raise HTTPException(status_code=401, detail="invalid api key")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "service": "provider-stub"}


def _task_text(prompt: str) -> str:
    """The task from the agent's prompt, not the whole thing.

    The prompt also lists the tool catalogue, which mentions "refund" and friends
    — deciding on all of it made the stub pick a refund tool for a customer lookup.
    The agent quotes the task as ``Task: "..."``.
    """
    match = re.search(r'Task:\s*"(.+?)"', prompt, re.S)
    return match.group(1) if match else prompt


def _decide(prompt: str) -> dict:
    """A deterministic tool choice, so a run through the stub does something."""
    task = _task_text(prompt)
    p = task.lower()
    ids = re.findall(r"\b(?:o|c|t)-\d{3,4}\b", task)
    order = next((i for i in ids if i.startswith("o-")), None)
    customer = next((i for i in ids if i.startswith("c-")), None)
    ticket = next((i for i in ids if i.startswith("t-")), None)
    if "refund" in p:
        if "quote" in p or "how much" in p or "refundable" in p:
            return {"tool": "refunds.quote", "args": {"order_id": order or "o-1001"}}
        amount = re.search(r"refund (?:of )?(\d+(?:\.\d+)?)", p)
        return {
            "tool": "refunds.issue",
            "args": {"order_id": order or "o-1001", "amount": float(amount.group(1)) if amount else 25},
        }
    if "ticket" in p:
        return {"tool": "tickets.read", "args": {"ticket_id": ticket or "t-5001"}}
    if "order" in p:
        return {"tool": "crm.orders.list", "args": {"customer_id": customer or "c-100"}}
    return {"tool": "crm.customer.read", "args": {"customer_id": customer or "c-100"}}


@app.post("/v1/chat/completions")
async def chat(request: Request, authorization: str | None = Header(default=None)) -> dict:
    _check_key(authorization)
    body = await request.json()
    if not body.get("model"):
        raise HTTPException(status_code=400, detail="you must provide a model parameter")
    if os.environ.get("STUB_STRICT", "").strip() in ("1", "true", "yes") and "response_format" in body:
        raise HTTPException(status_code=400, detail="unsupported parameter: response_format")

    prompt = "\n".join(str(m.get("content", "")) for m in (body.get("messages") or []))
    content = json.dumps(_decide(prompt))
    total = max(2, (len(prompt) + len(content)) // 4)
    return {
        "id": "chatcmpl-stub",
        "object": "chat.completion",
        "model": body.get("model"),
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": max(1, len(prompt) // 4),
            "completion_tokens": max(1, len(content) // 4),
            "total_tokens": total,
        },
    }
