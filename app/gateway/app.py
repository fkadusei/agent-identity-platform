"""LLM gateway: the only component that talks to a model provider.

The agent calls this over **SPIFFE mTLS** (its X.509-SVID as the client cert,
verified against the SPIRE trust bundle), and additionally presents a
**JWT-SVID** in `Authorization` so the gateway knows *which* workload is calling
— that identity keys the per-agent rate and cost limits. The gateway holds the
provider key, so the agent needs no LLM credential at all.

It exposes an OpenAI-compatible `/v1/chat/completions` and translates to the
configured provider (local Ollama by default; any OpenAI-compatible endpoint
when a key is present).
"""
from __future__ import annotations

import os

import httpx
import jwt
from fastapi import FastAPI, Header, HTTPException
from jwt import PyJWKClient
from pydantic import BaseModel

from agentnhi import audit
from app.common.telemetry import instrument_fastapi, setup_telemetry, span
from app.gateway.limits import estimate_tokens, limiter_from_env

app = FastAPI(title="LLM gateway")
setup_telemetry("gateway")
instrument_fastapi(app)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

# The caller's JWT-SVID is verified against SPIRE's JWKS; its `sub` is the
# caller's SPIFFE ID and the key for the limits below.
SPIRE_JWKS_URL = os.environ.get(
    "SPIRE_JWKS_URL",
    "http://spire-oidc-discovery.agent-platform.svc.cluster.local:11080/keys",
)
GATEWAY_AUDIENCE = os.environ.get(
    "LLM_GATEWAY_AUDIENCE", "spiffe://acme.com/ns/agent-platform/sa/gateway"
)
LIMITER = limiter_from_env()
_jwks: PyJWKClient | None = None


def caller_id(authorization: str | None) -> str:
    """Verify the caller's JWT-SVID and return its SPIFFE ID."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing workload token")
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(SPIRE_JWKS_URL)
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256", "ES256"], audience=GATEWAY_AUDIENCE)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=403, detail=f"invalid workload token: {exc}")
    subject = claims.get("sub")
    if not subject:
        raise HTTPException(status_code=403, detail="workload token has no subject")
    return subject


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict]
    response_format: dict | None = None


def _wants_json(req: ChatRequest) -> bool:
    return (req.response_format or {}).get("type") == "json_object"


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "provider": os.environ.get("LLM_PROVIDER", "ollama")}


@app.post("/v1/chat/completions")
def chat(req: ChatRequest, authorization: str | None = Header(default=None)) -> dict:
    caller = caller_id(authorization)

    # Rate and cost limits, keyed on the proven caller identity.
    decision = LIMITER.check(caller)
    if not decision.allowed:
        audit("llm.limited", caller=caller, reason=decision.reason)
        raise HTTPException(
            status_code=429,
            detail=decision.reason,
            headers={"Retry-After": str(decision.retry_after)},
        )

    provider = os.environ.get("LLM_PROVIDER", "ollama")
    # Audit metadata only — never the prompt or its contents.
    # The model that will actually run, resolved *before* the audit. The caller
    # usually names none (the agent asks for an answer, not a vendor), so auditing
    # `req.model` recorded an empty string — and "which model decided this?" is the
    # reason the field exists.
    model = req.model or (OLLAMA_MODEL if provider == "ollama" else os.environ.get("LLM_MODEL", ""))
    audit("llm.call", provider=provider, model=model, messages=len(req.messages), caller=caller)

    if provider == "ollama":
        prompt = "\n".join(str(m.get("content", "")) for m in req.messages)
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            # Ask a *thinking* model not to deliberate. With `format: json` a thinking
            # model (Qwen3 and friends) puts its JSON in `thinking` and returns `response`
            # empty, so the caller receives nothing at all. Found by swapping one in — see
            # the fallback below.
            "think": False,
        }
        if _wants_json(req):
            payload["format"] = "json"
        with span("llm.provider_call", provider="ollama", model=payload["model"]):
            resp = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=180)
        resp.raise_for_status()
        body = resp.json()
        # `response` is the answer. `thinking` is reasoning, and when a model ignores
        # the request above the answer still lands there, so take it rather than
        # handing the caller an empty string.
        content = body.get("response") or body.get("thinking", "")
        LIMITER.charge(caller, estimate_tokens(prompt) + estimate_tokens(content))
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}

    # Hosted, OpenAI-compatible provider. The key lives ONLY here.
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    resp = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}"},
        json=req.model_dump(exclude_none=True),
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    # Providers report usage; fall back to an estimate if they do not.
    usage = (body.get("usage") or {}).get("total_tokens")
    if usage is None:
        usage = sum(estimate_tokens(str(m.get("content", ""))) for m in req.messages)
    LIMITER.charge(caller, int(usage))
    return body
