"""LLM gateway: the only component that talks to a model provider.

The agent calls this over **SPIFFE mTLS** (its X.509-SVID as the client cert,
verified against the SPIRE trust bundle). The gateway holds the provider key, so
the agent needs no LLM credential at all — the "last static credential" is gone
from the agent.

It exposes an OpenAI-compatible `/v1/chat/completions` and translates to the
configured provider (local Ollama by default; any OpenAI-compatible endpoint
when a key is present).
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from agentnhi import audit
from app.common.telemetry import instrument_fastapi, setup_telemetry, span

app = FastAPI(title="LLM gateway")
setup_telemetry("gateway")
instrument_fastapi(app)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")


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
def chat(req: ChatRequest) -> dict:
    provider = os.environ.get("LLM_PROVIDER", "ollama")
    # Audit metadata only — never the prompt or its contents.
    audit("llm.call", provider=provider, model=req.model or "", messages=len(req.messages))

    if provider == "ollama":
        prompt = "\n".join(str(m.get("content", "")) for m in req.messages)
        payload: dict = {
            "model": req.model or OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
        }
        if _wants_json(req):
            payload["format"] = "json"
        with span("llm.provider_call", provider="ollama", model=payload["model"]):
            resp = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=180)
        resp.raise_for_status()
        content = resp.json()["response"]
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
    return resp.json()
