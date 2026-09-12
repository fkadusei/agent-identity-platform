"""Policy client: three outcomes, and fail-closed on every error path."""
from __future__ import annotations

from agentnhi import Decision, PolicyClient, Settings
from tests.fakes import FakeClient, FakeResponse


def settings(**overrides) -> Settings:
    base = dict(opa_url="http://opa:8181", policy_path="agentnhi/authz")
    base.update(overrides)
    return Settings(**base)


def decide(response, **kwargs):
    client = FakeClient(response)
    result = PolicyClient(settings(), client=client).decide(
        agent="spiffe://agent", user="alice", tool="refunds.issue", **kwargs
    )
    return result, client


def test_allow():
    result, _ = decide(FakeResponse(200, {"result": {"decision": "allow", "reason": "ok"}}))
    assert result.decision is Decision.ALLOW
    assert result.allowed is True


def test_deny():
    result, _ = decide(FakeResponse(200, {"result": {"decision": "deny", "reason": "no"}}))
    assert result.decision is Decision.DENY
    assert result.allowed is False


def test_require_approval():
    result, _ = decide(
        FakeResponse(200, {"result": {"decision": "require_approval", "reason": "amount > 50"}})
    )
    assert result.decision is Decision.REQUIRE_APPROVAL
    assert result.allowed is False


def test_unknown_decision_fails_closed():
    result, _ = decide(FakeResponse(200, {"result": {"decision": "maybe"}}))
    assert result.decision is Decision.DENY


def test_missing_result_fails_closed():
    result, _ = decide(FakeResponse(200, {}))
    assert result.decision is Decision.DENY


def test_transport_error_fails_closed():
    client = FakeClient(error=RuntimeError("connection refused"))
    result = PolicyClient(settings(), client=client).decide(agent="a", user="u", tool="t")
    assert result.decision is Decision.DENY
    assert "unavailable" in result.reason


def test_http_error_fails_closed():
    result, _ = decide(FakeResponse(500, text="boom"))
    assert result.decision is Decision.DENY


def test_request_payload_and_url():
    result, client = decide(
        FakeResponse(200, {"result": {"decision": "allow"}}), context={"amount": 75}
    )
    call = client.calls[0]
    assert call["url"].endswith("/v1/data/agentnhi/authz")
    assert call["json"]["input"] == {
        "agent": "spiffe://agent",
        "user": "alice",
        "tool": "refunds.issue",
        "amount": 75,
    }
