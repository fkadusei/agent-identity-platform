"""Provider-agnostic LLM tool selection.

The model only ever *proposes* a tool and its arguments. It never decides
whether the call is permitted — that is policy's job, enforced at the tool
server.

By default the call goes through the **LLM gateway** over SPIFFE mTLS, so the
agent holds no model credential. Set `LLM_GATEWAY_URL` to enable that path; the
direct-provider fallback exists only for development without a gateway.
"""
from __future__ import annotations

import json
import os
import re
import time

import httpx

from agentnhi import audit

from app.agent.guardrails import GuardrailError, check_decision


def _tool_manifest(tools: dict) -> str:
    lines = []
    for tool in tools.values():
        required = tool.input_schema.get("required") or []
        params = ", ".join(required)
        lines.append(f"- {tool.name}({params}): {tool.description}")
    return "\n".join(lines)


def _prompt(task: str, tools: dict, unavailable: dict | None = None) -> str:
    parts = [
        "You are a customer-support agent. Choose exactly one tool from the "
        "available list to handle the task.\n",
        f"Available tools:\n{_tool_manifest(tools)}\n\n",
    ]
    if unavailable:
        # Naming the forbidden tools matters: if we simply hide them, a small
        # model substitutes a different (allowed) tool and the run *looks* like it
        # succeeded — which is exactly the confusion this avoids.
        parts.append(
            "NOT permitted for this user's role (never choose these):\n"
            f"{_tool_manifest(unavailable)}\n\n"
        )
    parts.append(f'Task: "{task}"\n\n')
    parts.append(
        "If the task needs a tool that is not permitted, or none of the available "
        'tools fits, reply with {"tool": null, "reason": "<why>"}.\n'
        "Otherwise reply with ONLY JSON of the form "
        '{"tool": "<name>", "args": {<arguments>}, "reason": "<short reason>"}.'
    )
    return "".join(parts)


def _extract_args(task: str) -> dict:
    """Best-effort arguments pulled from the task text.

    Small models are unreliable at filling tool arguments, and a missing
    argument would make policy fall through to deny. These are used only to
    fill gaps the model left, so the run reflects policy rather than the
    model's formatting.
    """
    args: dict = {}
    ref = re.search(r"\b([oct]-\d+)\b", task)
    if ref:
        value = ref.group(1)
        args[{"o": "order_id", "c": "customer_id", "t": "ticket_id"}[value[0]]] = value
    amount = re.search(r"(?<![\w-])(\d+(?:\.\d+)?)(?![\w-])", task)
    if amount:
        args["amount"] = float(amount.group(1))
    return args


def _fill_gaps(tool, args: dict, task: str) -> dict:
    properties = tool.input_schema.get("properties") or {}
    extracted = _extract_args(task)
    for key, value in extracted.items():
        if key in properties and args.get(key) in (None, "", 0):
            args[key] = value
    # Coerce to declared types (models often emit numbers as strings).
    from app.common.schema import coerce_args

    return coerce_args(properties, args)


def _mtls_client() -> httpx.Client:
    """An httpx client presenting this workload's X.509-SVID, over the gateway.

    Hostname verification is off because the gateway's identity is a SPIFFE URI
    SAN, not a DNS name; the chain is still verified against the SPIRE bundle.
    """
    from agentnhi.identity import mtls_client_context

    socket = os.environ.get("SPIFFE_SOCKET", "unix:///run/spire/sockets/agent.sock")
    bundle = os.environ.get("SPIFFE_BUNDLE", "/run/spire/bundle/bundle.crt")
    ctx = mtls_client_context(socket, ca_cert_path=bundle, verify_hostname=False)
    return httpx.Client(verify=ctx, timeout=180)


_jwt_svid: tuple[float, str] = (0.0, "")


def _workload_token() -> str:
    """This workload's JWT-SVID, cached briefly.

    mTLS proves *a* workload is calling; the JWT-SVID names *which* one, so the
    gateway can key its per-agent limits on it.
    """
    global _jwt_svid
    issued, token = _jwt_svid
    if token and time.time() - issued < 300:
        return token
    from agentnhi.identity import fetch_jwt_svid

    socket = os.environ.get("SPIFFE_SOCKET", "unix:///run/spire/sockets/agent.sock")
    audience = os.environ.get(
        "LLM_GATEWAY_AUDIENCE", "spiffe://acme.com/ns/agent-platform/sa/gateway"
    )
    token = fetch_jwt_svid(socket, audience)
    _jwt_svid = (time.time(), token)
    return token


def _chat(prompt: str) -> str:
    """Return the model's reply, via the gateway when configured."""
    gateway = os.environ.get("LLM_GATEWAY_URL")
    if gateway:
        client = _mtls_client()
        try:
            resp = client.post(
                f"{gateway.rstrip('/')}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
                headers={"Authorization": f"Bearer {_workload_token()}"},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        finally:
            client.close()

    # Direct provider — development without a gateway. No credential is held
    # here unless a hosted provider is configured (the gateway exists to avoid
    # that; see docs/decisions/ADR-0009).
    provider = os.environ.get("LLM_PROVIDER", "ollama")
    if provider == "ollama":
        url = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
        model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
        resp = httpx.post(
            f"{url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=180,
        )
        return resp.json()["response"]

    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    resp = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}"},
        json={
            "model": os.environ.get("LLM_MODEL") or os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    return resp.json()["choices"][0]["message"]["content"]


def _no_tool(fallback: dict | None, reason: str, cause: str) -> dict:
    """A no-tool decision whose reason names the real fault.

    `cause` is machine-readable so the three ways a run ends without a tool stay
    distinguishable; `fallback` is the caller's escape hatch and wins when set.
    """
    if fallback:
        return fallback
    return {"tool": None, "args": {}, "reason": reason, "cause": cause}


def decide_tool(
    task: str, tools: dict, unavailable: dict | None = None, fallback: dict | None = None
) -> dict:
    """Return {"tool", "args", "reason"}.

    If the model cannot produce a usable decision we return **no tool** — never a
    different one. Silently substituting another action is worse than failing: a
    "refund $1000" that quietly becomes a customer lookup looks like success.

    The ways that happens are kept apart on purpose. "The model did not choose a
    usable tool" used to cover all of them, and during the 2026-09-16 incident
    that message pointed at the model for hours while the real faults were an
    expired SVID and an unreachable gateway — the model was never reached.
    """
    # 1. Did we reach the model at all? An expired certificate, an unreachable
    #    gateway and a timeout land here. This is an infrastructure fault, and
    #    nothing below it has been observed — least of all the model's answer.
    try:
        content = _chat(_prompt(task, tools, unavailable))
    except Exception as exc:  # noqa: BLE001 - never block the run on the model
        audit("llm.fallback", cause="unreachable", reason=str(exc)[:200])
        return _no_tool(
            fallback, "the model could not be reached — nothing was executed", "unreachable"
        )

    # 2. We reached it, but the reply was not JSON.
    try:
        decision = json.loads(content)
    except (ValueError, TypeError) as exc:
        audit("llm.fallback", cause="unparseable", reason=str(exc)[:200])
        return _no_tool(
            fallback,
            "the model's reply could not be understood — nothing was executed",
            "unparseable",
        )

    # 3. It parsed; now it has to name a usable tool. Anything malformed from
    #    here is about the model's answer, so the blame belongs on the model.
    try:
        chosen = decision.get("tool")
        if chosen and chosen in (unavailable or {}):
            # Deterministic: the model asked for a tool this role may not use.
            # Refuse here rather than let it pick something else instead.
            return {
                "tool": None,
                "args": {},
                "reason": f"your role may not call {chosen}",
                "refused": True,
                # The one case where we know what was asked for: the model named a
                # tool that exists but is not offered to this role.
                "refused_tool": chosen,
            }
        if not chosen:
            # The model declined. Its own "reason" is unreliable — a small model
            # tends to echo a tool *description* ("High-risk: policy may require
            # approval"), which tells the user nothing. Say something useful.
            return {
                "tool": None,
                "args": {},
                "reason": "no tool your role may call fits this task — nothing was executed",
                "refused": True,
            }
        if chosen in tools:
            tool = tools[decision["tool"]]
            args = _fill_gaps(tool, dict(decision.get("args") or {}), task)
            try:
                check_decision(tool, args)
            except GuardrailError as exc:
                audit("llm.guardrail", tool=tool.name, reason=str(exc)[:200])
                return {"tool": None, "args": {}, "reason": str(exc), "refused": True,
                        "refused_tool": tool.name}
            return {"tool": tool.name, "args": args, "reason": decision.get("reason", "")}
        audit("llm.invalid_tool", tool=str(decision.get("tool"))[:80])
    except Exception as exc:  # noqa: BLE001 - never block the run on the model
        audit("llm.fallback", cause="unusable", reason=str(exc)[:200])

    return _no_tool(
        fallback,
        "the model did not choose a usable tool — nothing was executed",
        "unusable",
    )
