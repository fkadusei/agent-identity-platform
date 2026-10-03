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
    audited: dict = {}

    def fake_post(url, json=None, **kwargs):  # noqa: A002 - mirrors httpx
        calls["url"], calls["json"] = url, json
        return _Response({"response": '{"tool": "crm.customer.read"}'})

    _as_caller(monkeypatch)
    monkeypatch.setattr(gw, "audit", lambda event, **kw: audited.update(kw))
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
    # The audit names the model that ran, not the empty string a caller may send.
    assert audited["model"] == calls["json"]["model"]


def test_a_thinking_model_does_not_lose_its_answer(monkeypatch):
    """A Qwen3-style model with `format: json` puts the JSON in `thinking`.

    Found by swapping models: `response` came back empty, so the caller received "" and
    the agent reported an unparseable reply — the model had answered correctly. The
    gateway asks for `think: false`, and falls back to `thinking` for a model that skips
    the request anyway.
    """
    calls: dict = {}

    def fake_post(url, json=None, **kwargs):  # noqa: A002 - mirrors httpx
        calls["json"] = json
        return _Response({"response": "", "thinking": '{"tool": "refunds.quote"}'})

    _as_caller(monkeypatch)
    monkeypatch.setattr(gw.httpx, "post", fake_post)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    resp = TestClient(app).post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "quote a refund"}],
            "response_format": {"type": "json_object"},
        },
    )
    assert resp.status_code == 200
    assert calls["json"]["think"] is False
    assert resp.json()["choices"][0]["message"]["content"] == '{"tool": "refunds.quote"}'


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
    monkeypatch.setenv("LLM_MODEL", "gpt-test")

    resp = TestClient(app).post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert resp.status_code == 200
    assert calls["url"] == "https://api.example/v1/chat/completions"
    assert calls["headers"]["Authorization"] == "Bearer secret-key"


def test_hosted_provider_receives_the_resolved_model(monkeypatch):
    """The agent sends no model; the gateway must add the one it resolved (S17).

    Forwarding the caller's request verbatim sent `model: None` straight through,
    and a hosted provider rejects a request with no model. The resolved model is
    already computed for the audit — it now goes into the payload too.
    """
    calls: dict = {}

    def fake_post(url, json=None, headers=None, **kwargs):  # noqa: A002
        calls["json"] = json
        return _Response({"choices": [{"message": {"role": "assistant", "content": "{}"}}]})

    _as_caller(monkeypatch)
    monkeypatch.setattr(gw.httpx, "post", fake_post)
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-test")

    resp = TestClient(app).post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert resp.status_code == 200
    assert calls["json"]["model"] == "gpt-test"


def test_hosted_response_format_can_be_stripped(monkeypatch):
    """A strict provider may reject `response_format`; the field can be dropped (S17)."""
    calls: dict = {}

    def fake_post(url, json=None, headers=None, **kwargs):  # noqa: A002
        calls["json"] = json
        return _Response({"choices": [{"message": {"role": "assistant", "content": "{}"}}]})

    _as_caller(monkeypatch)
    monkeypatch.setattr(gw.httpx, "post", fake_post)
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-test")
    monkeypatch.setenv("LLM_STRIP_RESPONSE_FORMAT", "1")

    resp = TestClient(app).post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "response_format": {"type": "json_object"},
        },
    )
    assert resp.status_code == 200
    assert "response_format" not in calls["json"]


def test_hosted_without_a_model_fails_clearly(monkeypatch):
    _as_caller(monkeypatch)
    monkeypatch.setattr(gw.httpx, "post", lambda *a, **k: _Response({}))
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example/v1")
    monkeypatch.delenv("LLM_MODEL", raising=False)

    resp = TestClient(app).post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert resp.status_code == 500
    assert "LLM_MODEL" in resp.json()["detail"]


def test_hosted_provider_without_a_key_sends_no_authorization(monkeypatch):
    """A keyless provider must not receive an empty `Bearer ` (S17).

    Found through the in-cluster stub: with no LLM_API_KEY the gateway still set
    `Authorization: Bearer `, and httpx refuses the illegal header value — the
    call failed before it left the gateway.
    """
    calls: dict = {}

    def fake_post(url, json=None, headers=None, **kwargs):  # noqa: A002
        calls["headers"] = headers
        return _Response({"choices": [{"message": {"role": "assistant", "content": "{}"}}]})

    _as_caller(monkeypatch)
    monkeypatch.setattr(gw.httpx, "post", fake_post)
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://provider-stub:8080/v1")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    resp = TestClient(app).post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert resp.status_code == 200
    assert "Authorization" not in (calls["headers"] or {})


def test_gateway_refuses_a_revoked_workload(monkeypatch):
    """A revoked agent is refused at the gateway too, before its SVID expires (S23)."""
    from app.common import revocation

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": "k"})()

    monkeypatch.setattr(gw, "_jwks", Keys())
    monkeypatch.setattr(gw.jwt, "decode", lambda *a, **k: {"sub": CALLER})
    revocation.set_source(lambda: {CALLER})
    try:
        resp = TestClient(app).post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 403
        assert "revoked" in resp.json()["detail"]
    finally:
        revocation.reset()


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
