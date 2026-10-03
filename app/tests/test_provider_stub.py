"""The stub provider is strict about the two things S17 fixed.

It is the test double the gateway's hosted branch runs against; these pin the
behaviour that makes it useful: it demands a model (as a real provider does) and,
when strict, rejects `response_format`.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.provider_stub.app import app

client = TestClient(app)


def _body(**kwargs) -> dict:
    body = {"messages": [{"role": "user", "content": "get customer c-100"}]}
    body.update(kwargs)
    return body


def test_healthz():
    assert client.get("/healthz").json()["ok"] is True


def test_a_request_without_a_model_is_400():
    resp = client.post("/v1/chat/completions", json=_body())
    assert resp.status_code == 400
    assert "model" in resp.json()["detail"]


def test_it_returns_a_tool_decision():
    resp = client.post("/v1/chat/completions", json=_body(model="stub"))
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert '"tool"' in content


def test_strict_mode_rejects_response_format(monkeypatch):
    monkeypatch.setenv("STUB_STRICT", "1")
    resp = client.post(
        "/v1/chat/completions",
        json=_body(model="stub", response_format={"type": "json_object"}),
    )
    assert resp.status_code == 400
    assert "response_format" in resp.json()["detail"]


def test_the_api_key_is_required_when_configured(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "stub-key")
    assert client.post("/v1/chat/completions", json=_body(model="stub")).status_code == 401
    ok = client.post(
        "/v1/chat/completions",
        json=_body(model="stub"),
        headers={"Authorization": "Bearer stub-key"},
    )
    assert ok.status_code == 200
