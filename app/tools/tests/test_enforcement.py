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
        user="alice", workload=AGENT, audience="mcp-tools", roles=("support_rep",), tenant="acme"
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


def test_string_amount_is_coerced_before_policy():
    # A model may emit "40"; policy must see 40.0, not a string (Rego sorts
    # strings after numbers, so "40" > 500 would be true).
    seen: dict = {}

    class CapturingPolicy:
        def decide(self, **kwargs) -> PolicyResult:
            seen.update(kwargs)
            return PolicyResult(Decision.ALLOW, "ok")

    e = ToolEnforcer(
        settings=Settings(keycloak_issuer="http://kc", audience="mcp-tools", trusted_workload=AGENT),
        verifier=FakeVerifier(
            Delegation(user="alice", workload=AGENT, audience="mcp-tools", roles=("support_rep",), tenant="acme")
        ),
        policy=CapturingPolicy(),
        approvals=FakeApprovals(False),
    )
    result = e.call("token", "refunds.issue", {"order_id": "o-1001", "amount": "40"})
    assert result.outcome is Outcome.OK
    assert seen["context"]["amount"] == 40.0


# --- tenant isolation (threat T9) -------------------------------------------
# The tenant comes from the identity, so a session cannot reach another tenant's
# data — and a record it may not see looks exactly like one that does not exist.

def test_a_session_cannot_reach_another_tenants_data():
    e = enforcer()  # alice, tenant acme
    mine = e.call("token", "crm.customer.read", {"customer_id": "c-100"})
    assert mine.outcome is Outcome.OK
    assert "error" not in mine.result

    other = e.call("token", "crm.customer.read", {"customer_id": "c-900"})
    assert other.outcome is Outcome.OK
    assert other.result == {"error": "unknown customer"}


def test_an_unscoped_identity_gets_no_data():
    e = enforcer(
        delegation=Delegation(
            user="alice", workload=AGENT, audience="mcp-tools", roles=("support_rep",)
        )
    )
    result = e.call("token", "crm.customer.read", {"customer_id": "c-100"})
    assert result.result == {"error": "unknown customer"}


def test_every_tool_audit_record_carries_the_tenant():
    """The privacy view scopes by tenant, so a record missing one is invisible.

    This is exactly how a PII `tool.allowed` row went missing from the trail: the
    other three audit calls carried the tenant and that one did not. One case per
    outcome, so no call site can quietly drop it again.
    """
    from agentnhi import set_sink

    records: list[dict] = []
    set_sink(records.append)
    try:
        enforcer().call("token", "crm.customer.read", {"customer_id": "c-100"})  # allowed
        enforcer(decision=Decision.DENY).call(  # denied
            "token", "refunds.issue", {"order_id": "o-1001", "amount": 1000}
        )
        enforcer(decision=Decision.REQUIRE_APPROVAL).call(  # held
            "token", "refunds.issue", {"order_id": "o-1001", "amount": 200}
        )
        enforcer().call("token", "crm.customer.read", {})  # tool.error (missing arg)
    finally:
        set_sink(None)

    tool_events = [r for r in records if str(r.get("event", "")).startswith("tool.")]
    assert {r["event"] for r in tool_events} == {
        "tool.allowed",
        "tool.denied",
        "tool.approval_required",
        "tool.error",
    }, sorted(r["event"] for r in tool_events)
    for record in tool_events:
        assert record.get("tenant") == "acme", record
