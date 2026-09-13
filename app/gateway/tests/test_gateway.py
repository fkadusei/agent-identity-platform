"""The gateway translates an OpenAI-shaped request and enforces per-agent limits."""
from __future__ import annotations

from fastapi.testclient import TestClient

import app.gateway.app as gw
from app.gateway.app import app
from app.gateway.limits import Limiter

CALLER = "spiffe://acme.com/ns/agent-platform/sa/agent"


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


def _as_caller(monkeypatch) -> None:
    """Stand in for JWT-SVID verification (tested end to end on kind)."""
    monkeypatch.setattr(gw, "caller_id", lambda _authorization: CALLER)


def test_healthz():
    assert TestClient(app).get("/healthz").json()["ok"] is True


def test_missing_workload_token_is_401():
    # No monkeypatching: the real verifier rejects a missing token.
    resp = TestClient(app).post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert resp.status_code == 401


def test_ollama_translation(monkeypatch):
    calls: dict = {}

    def fake_post(url, json=None, **kwargs):  # noqa: A002 - mirrors httpx
        calls["url"], calls["json"] = url, json
        return _Response({"response": '{"tool": "crm.customer.read"}'})

    _as_caller(monkeypatch)
    monkeypatch.setattr(gw.httpx, "post", fake_post)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    resp = TestClient(app).post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "get c-100"}],
            "response_format": {"type": "json_object"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == '{"tool": "crm.customer.read"}'
    assert calls["url"].endswith("/api/generate")
    assert calls["json"]["format"] == "json"  # json_object is translated for Ollama


def test_hosted_provider_forwards_the_key(monkeypatch):
    calls: dict = {}

    def fake_post(url, json=None, headers=None, **kwargs):  # noqa: A002
        calls["url"], calls["headers"] = url, headers
        return _Response({"choices": [{"message": {"role": "assistant", "content": "{}"}}]})

    _as_caller(monkeypatch)
    monkeypatch.setattr(gw.httpx, "post", fake_post)
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "secret-key")

    resp = TestClient(app).post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert resp.status_code == 200
    assert calls["url"] == "https://api.example/v1/chat/completions"
    assert calls["headers"]["Authorization"] == "Bearer secret-key"


def test_rate_limit_returns_429(monkeypatch):
    _as_caller(monkeypatch)
    monkeypatch.setattr(gw, "LIMITER", Limiter(requests_per_minute=1))
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(gw.httpx, "post", lambda *a, **k: _Response({"response": "{}"}))

    client = TestClient(app)
    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert client.post("/v1/chat/completions", json=body).status_code == 200

    denied = client.post("/v1/chat/completions", json=body)
    assert denied.status_code == 429
    assert "rate limit" in denied.json()["detail"]
    assert denied.headers["retry-after"]


def test_token_budget_returns_429(monkeypatch):
    _as_caller(monkeypatch)
    monkeypatch.setattr(gw, "LIMITER", Limiter(tokens_per_day=10))
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(gw.httpx, "post", lambda *a, **k: _Response({"response": "x" * 400}))

    client = TestClient(app)
    body = {"messages": [{"role": "user", "content": "a long-ish prompt to spend the budget"}]}
    # The first call is allowed and charges more than the 10-token budget.
    assert client.post("/v1/chat/completions", json=body).status_code == 200

    denied = client.post("/v1/chat/completions", json=body)
    assert denied.status_code == 429
    assert "budget" in denied.json()["detail"]
