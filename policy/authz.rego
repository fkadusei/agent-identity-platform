# =============================================================================
# Authorization policy for the support & refunds platform.
#
# Three outcomes, with explicit precedence: deny > require_approval > allow.
# If nothing matches, the answer is deny (the default).
#
# Input contract:
#   input.agent   the acting workload's SPIFFE ID (from the token's azp)
#   input.user    the human the action is for (from the token's sub/username)
#   input.roles   the human's roles, e.g. ["support_rep"] or ["support_rep","manager"]
#   input.tool    the tool being called, e.g. "refunds.issue"
#   input.amount  the refund amount (only for refund tools)
#
# Output:
#   decision      "allow" | "deny" | "require_approval"
#   reason        a human-readable explanation (recorded in the audit trail)
#
# Tested by policy/tests/authz_test.rego (runs in CI).
# =============================================================================
package agentnhi.authz

import rego.v1

# ---------------------------------------------------------------------------
# Configuration — the parts a reviewer would change.
# ---------------------------------------------------------------------------
trusted_agent := "spiffe://acme.com/ns/agent-platform/sa/agent"

# Tools a support rep may use freely.
low_risk_tools := {
  "crm.customer.read",
  "crm.orders.list",
  "tickets.read",
  "tickets.reply.draft",
  "refunds.quote",
}

pii_tools := {"privacy.pii.read"}
refund_tool := "refunds.issue"
auto_refund_limit := 50        # <= this: allowed outright
approval_refund_limit := 500   # <= this (and > auto): needs approval; above: denied

# The bundle revision, injected at build time as data.agentnhi.policy_version
# (see scripts/build-bundle.sh) and recorded with every decision — so you can
# always answer "which policy revision decided this?". Falls back to "dev" when
# the raw file is run directly (e.g. `opa test policy/`).
default policy_version := "dev"

policy_version := data.agentnhi.policy_version if data.agentnhi.policy_version

# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------
is_trusted if input.agent == trusted_agent

has_role(role) if role in input.roles

# A deny condition: the workload is not the trusted agent.
deny if not is_trusted

# A deny condition: bulk actions are never permitted.
deny if startswith(input.tool, "bulk.")

# A deny condition: refunds above the approval ceiling.
deny if {
  input.tool == refund_tool
  input.amount > approval_refund_limit
}

# A deny condition: PII access for someone without the privacy role.
deny if {
  input.tool in pii_tools
  not has_role("privacy")
}

# Approval condition: refunds above the auto-approval limit.
needs_approval if {
  is_trusted
  has_role("support_rep")
  input.tool == refund_tool
  input.amount > auto_refund_limit
  input.amount <= approval_refund_limit
}

# Approval condition: any PII access by a privacy-role holder.
needs_approval if {
  is_trusted
  input.tool in pii_tools
  has_role("privacy")
}

# Allow condition: low-risk tools for a support rep.
allow if {
  is_trusted
  has_role("support_rep")
  input.tool in low_risk_tools
}

# Allow condition: small refunds for a support rep.
allow if {
  is_trusted
  has_role("support_rep")
  input.tool == refund_tool
  input.amount <= auto_refund_limit
}

# ---------------------------------------------------------------------------
# Resolution — exactly one branch fires, because each is guarded.
# ---------------------------------------------------------------------------
default decision := "deny"

decision := "deny" if deny

decision := "require_approval" if {
  needs_approval
  not deny
}

decision := "allow" if {
  allow
  not deny
  not needs_approval
}

# ---------------------------------------------------------------------------
# Reasons (recorded in the audit trail)
# ---------------------------------------------------------------------------
default reason := "denied by default: no rule permitted this action"

reason := "denied: untrusted workload identity" if not is_trusted

reason := "denied: bulk actions are not permitted" if startswith(input.tool, "bulk.")

reason := sprintf(
  "denied: refund of %v exceeds the approval ceiling of %v",
  [input.amount, approval_refund_limit],
) if {
  input.tool == refund_tool
  input.amount > approval_refund_limit
}

reason := "denied: PII access requires the privacy role" if {
  input.tool in pii_tools
  not has_role("privacy")
}

reason := sprintf(
  "requires manager approval: refund of %v is above the auto-approval limit of %v",
  [input.amount, auto_refund_limit],
) if {
  needs_approval
  not deny
  input.tool == refund_tool
}

reason := "requires privacy approval: PII access" if {
  needs_approval
  not deny
  input.tool in pii_tools
}

reason := "allowed: low-risk tool for support_rep" if {
  allow
  not deny
  not needs_approval
  input.tool in low_risk_tools
}

reason := sprintf("allowed: refund of %v is within the auto-approval limit", [input.amount]) if {
  allow
  not deny
  not needs_approval
  input.tool == refund_tool
}
