"""The gateway translates an OpenAI-shaped request to the configured provider."""
from __future__ import annotations

from fastapi.testclient import TestClient

import app.gateway.app as gw
from app.gateway.app import app


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


def test_healthz():
    assert TestClient(app).get("/healthz").json()["ok"] is True


def test_ollama_translation(monkeypatch):
    calls: dict = {}

    def fake_post(url, json=None, **kwargs):  # noqa: A002 - mirrors httpx
        calls["url"], calls["json"] = url, json
        return _Response({"response": '{"tool": "crm.customer.read"}'})

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
