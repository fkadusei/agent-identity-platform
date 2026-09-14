# Tests for policy/authz.rego — run: opa test policy/ -v
package agentnhi.authz

import rego.v1

AGENT := "spiffe://acme.com/ns/agent-platform/sa/agent"
ROGUE := "spiffe://acme.com/ns/agent-platform/sa/rogue"

base := {
  "agent": AGENT,
  "user": "alice",
  "roles": ["support_rep"],
  "tenant": "acme",
  "tool": "crm.customer.read",
}

refund(amount) := object.union(base, {"tool": "refunds.issue", "amount": amount})

# --- allow -------------------------------------------------------------------
test_allow_low_risk_tool if {
  decision == "allow" with input as base
}

test_allow_small_refund if {
  decision == "allow" with input as refund(25)
}

test_boundary_50_allows if {
  decision == "allow" with input as refund(50)
}

# --- require approval --------------------------------------------------------
test_mid_refund_requires_approval if {
  decision == "require_approval" with input as refund(200)
}

test_boundary_500_requires_approval if {
  decision == "require_approval" with input as refund(500)
}

test_pii_with_privacy_role_requires_approval if {
  decision == "require_approval" with input as object.union(base, {
    "roles": ["support_rep", "privacy"],
    "tool": "privacy.pii.read",
  })
}

# --- deny --------------------------------------------------------------------
test_large_refund_is_denied if {
  decision == "deny" with input as refund(1000)
}

test_pii_without_privacy_role_is_denied if {
  decision == "deny" with input as object.union(base, {"tool": "privacy.pii.read"})
}

test_bulk_action_is_denied if {
  decision == "deny" with input as object.union(base, {"tool": "bulk.refund"})
}

test_untrusted_agent_is_denied if {
  decision == "deny" with input as object.union(base, {"agent": ROGUE})
}

test_unknown_tool_is_denied if {
  decision == "deny" with input as object.union(base, {"tool": "admin.delete_everything"})
}

test_no_roles_is_denied if {
  decision == "deny" with input as object.union(base, {"roles": []})
}

# --- reason is always present and readable -----------------------------------
test_reason_is_never_empty if {
  reason != "" with input as base
}

test_refund_reason_mentions_approval if {
  contains(reason, "approval") with input as refund(200)
}

# --- tenancy: an unscoped identity gets nothing (fail closed) -----------------
test_deny_without_a_tenant if {
  decision == "deny" with input as object.remove(base, ["tenant"])
}

test_missing_tenant_reason_is_clear if {
  contains(reason, "tenant") with input as object.remove(base, ["tenant"])
}

test_allow_still_holds_with_a_tenant if {
  decision == "allow" with input as base
}

# --- a refund needs a positive, numeric amount ------------------------------
test_refund_without_an_amount_is_denied if {
  decision == "deny" with input as object.remove(refund(200), ["amount"])
}

test_refund_with_a_zero_amount_is_denied if {
  decision == "deny" with input as refund(0)
}

test_refund_with_a_negative_amount_is_denied if {
  decision == "deny" with input as refund(-5)
}

test_refund_with_a_non_numeric_amount_is_denied if {
  decision == "deny" with input as object.union(refund(200), {"amount": "-"})
}

test_refund_with_a_string_amount_is_denied if {
  decision == "deny" with input as object.union(refund(200), {"amount": "200"})
}

test_refund_amount_reason_is_clear if {
  contains(reason, "positive") with input as refund(0)
}
