package agentnhi.authz

import rego.v1

# =============================================================================
# Authorization policy for the support & refunds platform.
#
# Three outcomes, precedence deny > require_approval > allow.
#
# Input contract:
#   input.agent   the acting workload's SPIFFE ID (from the token's azp)
#   input.user    the human the action is for
#   input.roles   the human's roles, e.g. ["support_rep"]
#   input.tenant  the human's tenant
#   input.tool    the tool being called
#   input.amount  the refund amount (refund tools only)
#
# Output:
#   decision      "allow" | "deny" | "require_approval"
#   reason        one human-readable string (an `else` chain, so never a set)
#
# Tested by policy/tests/authz_test.rego (runs in CI).
# =============================================================================

trusted_agent := "spiffe://acme.com/ns/agent-platform/sa/agent"

# ---------------------------------------------------------------------------
# WHO MAY CALL WHAT — the review surface.
#
# A role can only call the tools listed here, and every tool in the catalogue
# must appear somewhere (a test asserts it against data.tools). Adding a tool
# without granting it to a role leaves it uncallable, by design.
# ---------------------------------------------------------------------------
role_tools := {
  "support_rep": {
    "crm.customer.read",
    "crm.orders.list",
    "tickets.read",
    "tickets.reply.draft",
    "refunds.quote",
    "refunds.issue",
  },
  "billing": {"crm.orders.list", "refunds.quote", "refunds.issue"},
  "read_only": {"crm.customer.read", "crm.orders.list", "tickets.read"},
  # `privacy` includes the read tools so the role is usable on its own — you need
  # a customer id before you can read their PII.
  "privacy": {
    "privacy.pii.read",
    "crm.customer.read",
    "crm.orders.list",
    "tickets.read",
  },
  "manager": {"crm.customer.read", "crm.orders.list", "tickets.read", "refunds.quote"},
  "platform_admin": set(),
}

refund_tool := "refunds.issue"
pii_tools := {"privacy.pii.read"}
auto_refund_limit := 50        # <= this: allowed outright
approval_refund_limit := 500   # <= this (and > auto): needs approval; above: denied

# The bundle revision, stamped at build time (scripts/build-bundle.sh) and
# recorded with every decision. Falls back to "dev" for the raw file.
default policy_version := "dev"

policy_version := data.agentnhi.policy_version if data.agentnhi.policy_version

# The tool catalogue, injected at build time. Empty when the raw file is run
# directly (e.g. `opa test policy/`), in which case the unknown-tool rule is
# skipped rather than denying everything.
catalogue := data.tools if data.tools

default catalogue := []

# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------
is_trusted if input.agent == trusted_agent

has_role(role) if role in input.roles

# The union of the caller's roles' tools.
may_call(tool) if {
  some role in input.roles
  tool in role_tools[role]
}

# The tools a set of roles may call — the agent asks for this so the model is
# offered only what it could actually use (the policy stays the enforcement).
tools_for_roles := tools if {
  tools := {tool | some role in input.roles; some tool in role_tools[role]}
}

# A refund must name a positive, numeric amount. Without this a missing or null
# amount falls through to allow.
is_positive_number(v) if {
  is_number(v)
  v > 0
}

# ---------------------------------------------------------------------------
# Deny conditions (each guarded; `deny` is a set, so several may hold)
# ---------------------------------------------------------------------------
deny if not is_trusted

deny if {
  is_trusted
  not input.tenant
}

deny if {
  is_trusted
  input.tenant
  count(catalogue) > 0
  not input.tool in catalogue
}

deny if {
  is_trusted
  input.tenant
  not may_call(input.tool)
}

deny if {
  is_trusted
  input.tenant
  startswith(input.tool, "bulk.")
}

deny if {
  is_trusted
  input.tenant
  may_call(input.tool)
  input.tool == refund_tool
  not is_positive_number(input.amount)
}

deny if {
  is_trusted
  input.tenant
  may_call(input.tool)
  input.tool == refund_tool
  is_positive_number(input.amount)
  input.amount > approval_refund_limit
}

# ---------------------------------------------------------------------------
# Approval conditions
# ---------------------------------------------------------------------------
needs_approval if {
  is_trusted
  input.tenant
  may_call(input.tool)
  input.tool == refund_tool
  is_positive_number(input.amount)
  input.amount > auto_refund_limit
  input.amount <= approval_refund_limit
}

needs_approval if {
  is_trusted
  input.tenant
  may_call(input.tool)
  input.tool in pii_tools
  has_role("privacy")
}

# ---------------------------------------------------------------------------
# Allow conditions
# ---------------------------------------------------------------------------
allow if {
  is_trusted
  input.tenant
  may_call(input.tool)
  input.tool != refund_tool
  not input.tool in pii_tools
}

allow if {
  is_trusted
  input.tenant
  may_call(input.tool)
  input.tool == refund_tool
  is_positive_number(input.amount)
  input.amount <= auto_refund_limit
}

# ---------------------------------------------------------------------------
# Resolution
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
# The reason — an `else` chain, so exactly one string is returned. (Separate
# rules for the same name would produce a *set* whenever two bodies matched,
# which the SDK, the audit and the UI all expect to be a string.)
# ---------------------------------------------------------------------------
reason := "denied: untrusted workload identity" if not is_trusted

else := "denied: caller has no tenant (unscoped identity)" if not input.tenant

else := sprintf("denied: %v is not a known tool", [input.tool]) if {
  count(catalogue) > 0
  not input.tool in catalogue
}

else := "denied: bulk actions are not permitted" if startswith(input.tool, "bulk.")

else := sprintf("denied: your role may not call %v", [input.tool]) if not may_call(input.tool)

else := "denied: a refund needs a positive, numeric amount" if {
  input.tool == refund_tool
  not is_positive_number(input.amount)
}

else := sprintf(
  "denied: refund of %v exceeds the approval ceiling of %v",
  [input.amount, approval_refund_limit],
) if {
  input.tool == refund_tool
  is_positive_number(input.amount)
  input.amount > approval_refund_limit
}

else := "denied: PII access requires the privacy role" if {
  input.tool in pii_tools
  not has_role("privacy")
}

else := sprintf(
  "requires manager approval: refund of %v is above the auto-approval limit of %v",
  [input.amount, auto_refund_limit],
) if {
  needs_approval
  input.tool == refund_tool
}

else := "requires privacy approval: PII access" if {
  needs_approval
  input.tool in pii_tools
}

else := sprintf("allowed: %v is within your role", [input.tool]) if allow

else := "denied by default: no rule permitted this action"
