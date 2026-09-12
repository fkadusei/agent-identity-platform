"""Provider-agnostic LLM tool selection.

The model only ever *proposes* a tool and its arguments. It never decides
whether the call is permitted — that is policy's job, enforced at the tool
server.
"""
from __future__ import annotations

import json
import os

import httpx

from agentnhi import audit


def _tool_manifest(tools: dict) -> str:
    lines = []
    for tool in tools.values():
        required = tool.input_schema.get("required") or []
        params = ", ".join(required)
        lines.append(f"- {tool.name}({params}): {tool.description}")
    return "\n".join(lines)


def _prompt(task: str, tools: dict) -> str:
    return (
        "You are a customer-support agent. Choose exactly one tool to handle the task.\n"
        f"Available tools:\n{_tool_manifest(tools)}\n\n"
        f'Task: "{task}"\n\n'
        "Reply with ONLY JSON of the form "
        '{"tool": "<name>", "args": {<arguments>}, "reason": "<short reason>"}.'
    )


def decide_tool(task: str, tools: dict, fallback: dict | None = None) -> dict:
    """Return {"tool", "args", "reason"}; falls back deterministically on error."""
    provider = os.environ.get("LLM_PROVIDER", "ollama")
    fallback = fallback or {
        "tool": "crm.customer.read",
        "args": {"customer_id": "c-100"},
        "reason": "fallback: default lookup",
    }
    try:
        if provider == "ollama":
            url = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
            model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
            resp = httpx.post(
                f"{url}/api/generate",
                json={"model": model, "prompt": _prompt(task, tools), "stream": False, "format": "json"},
                timeout=120,
            )
            content = resp.json()["response"]
        else:
            base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
            model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
            resp = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": _prompt(task, tools)}],
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            content = resp.json()["choices"][0]["message"]["content"]

        decision = json.loads(content)
        if decision.get("tool") in tools:
            return {
                "tool": decision["tool"],
                "args": decision.get("args", {}),
                "reason": decision.get("reason", ""),
            }
        audit("llm.invalid_tool", tool=str(decision.get("tool"))[:80])
    except Exception as exc:  # noqa: BLE001 - never block the run on the model
        audit("llm.fallback", reason=str(exc)[:200])
    return fallback
