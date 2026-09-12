"""The enforcement core: verify -> policy -> approval -> execute."""
from __future__ import annotations

import pytest

from agentnhi import Decision, Delegation, PolicyResult, Settings, TokenRejected
from app.simulators import reset
from app.tools.enforcement import Outcome, ToolEnforcer

AGENT = "spiffe://acme.com/ns/agent-nhi/sa/agent"


class FakeVerifier:
    def __init__(self, delegation: Delegation | None = None, error: Exception | None = None):
        self._delegation = delegation
        self._error = error

    def verify(self, token, **_kwargs):
        if self._error:
            raise self._error
        assert self._delegation is not None
        return self._delegation


class FakePolicy:
    def __init__(self, decision: Decision, reason: str = "policy"):
        self._decision = decision
        self._reason = reason

    def decide(self, **_kwargs) -> PolicyResult:
        return PolicyResult(self._decision, self._reason)


class FakeApprovals:
    def __init__(self, valid: bool):
        self._valid = valid
        self.calls: list[dict] = []

    def verify(self, approval_id, **kwargs) -> bool:
        self.calls.append({"approval_id": approval_id, **kwargs})
        return self._valid


def enforcer(*, delegation=None, verify_error=None, decision=Decision.ALLOW, approvals=False):
    delegation = delegation or Delegation(
        user="alice", workload=AGENT, audience="mcp-tools", roles=("support_rep",)
    )
    return ToolEnforcer(
        settings=Settings(keycloak_issuer="http://kc", audience="mcp-tools", trusted_workload=AGENT),
        verifier=FakeVerifier(delegation, verify_error),
        policy=FakePolicy(decision),
        approvals=FakeApprovals(approvals),
    )


@pytest.fixture(autouse=True)
def _clean():
    reset()
    yield
    reset()


def test_allow_executes_the_tool():
    result = enforcer().call("token", "crm.customer.read", {"customer_id": "c-100"})
    assert result.outcome is Outcome.OK
    assert result.result["tier"] == "gold"


def test_deny_does_not_execute():
    result = enforcer(decision=Decision.DENY).call(
        "token", "refunds.issue", {"order_id": "o-1001", "amount": 1000}
    )
    assert result.outcome is Outcome.DENIED
    assert result.decision == "deny"


def test_high_risk_without_approval_is_held():
    result = enforcer(decision=Decision.REQUIRE_APPROVAL).call(
        "token", "refunds.issue", {"order_id": "o-1001", "amount": 200}
    )
    assert result.outcome is Outcome.APPROVAL_REQUIRED


def test_high_risk_with_valid_approval_executes():
    e = enforcer(decision=Decision.REQUIRE_APPROVAL, approvals=True)
    result = e.call("token", "refunds.issue", {"order_id": "o-1001", "amount": 200, "approval_id": "a-1"})
    assert result.outcome is Outcome.OK
    assert result.result["status"] == "issued"


def test_high_risk_with_invalid_approval_is_held():
    e = enforcer(decision=Decision.REQUIRE_APPROVAL, approvals=False)
    result = e.call("token", "refunds.issue", {"order_id": "o-1001", "amount": 200, "approval_id": "bad"})
    assert result.outcome is Outcome.APPROVAL_REQUIRED


def test_no_token_is_denied():
    result = enforcer().call(None, "crm.customer.read", {"customer_id": "c-100"})
    assert result.outcome is Outcome.DENIED


def test_rejected_identity_is_denied():
    result = enforcer(verify_error=TokenRejected("audience mismatch")).call(
        "token", "crm.customer.read", {"customer_id": "c-100"}
    )
    assert result.outcome is Outcome.DENIED
    assert "identity rejected" in result.reason


def test_unknown_tool_is_denied():
    result = enforcer().call("token", "admin.delete_everything", {})
    assert result.outcome is Outcome.DENIED


def test_tool_error_is_reported_not_raised():
    result = enforcer().call("token", "refunds.issue", {"order_id": "o-nope", "amount": 10})
    assert result.outcome is Outcome.ERROR


def test_approval_id_is_not_passed_to_the_handler():
    # If approval_id leaked into the handler it would raise a TypeError.
    e = enforcer(decision=Decision.REQUIRE_APPROVAL, approvals=True)
    result = e.call("token", "refunds.issue", {"order_id": "o-1001", "amount": 200, "approval_id": "a-1"})
    assert result.outcome is Outcome.OK
