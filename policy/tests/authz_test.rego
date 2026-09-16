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

# =============================================================================
# The role -> tool matrix
# =============================================================================
all_tools := [
  "crm.customer.read", "crm.orders.list", "tickets.read", "tickets.reply.draft",
  "refunds.quote", "refunds.issue", "privacy.pii.read",
]

# The *default* matrix (tenant_role_tools overrides it per tenant, below).
expected_role_tools := {
  "support_rep": {"crm.customer.read", "crm.orders.list", "tickets.read", "tickets.reply.draft", "refunds.quote", "refunds.issue"},
  "billing": {"crm.orders.list", "refunds.quote", "refunds.issue"},
  "read_only": {"crm.customer.read", "crm.orders.list", "tickets.read"},
  "privacy": {"privacy.pii.read", "crm.customer.read", "crm.orders.list", "tickets.read"},
  "manager": {"crm.customer.read", "crm.orders.list", "tickets.read", "refunds.quote"},
  "platform_admin": set(),
}

for_role(role, tool) := object.union(base, {"roles": [role], "tool": tool, "amount": 25})

test_a_role_may_call_every_tool_it_grants if {
  some role, tools in expected_role_tools
  some tool in tools
  decision != "deny" with input as for_role(role, tool)
}

test_a_role_is_denied_every_tool_it_does_not_grant if {
  some role, tools in expected_role_tools
  some tool in all_tools
  not tool in tools
  decision == "deny" with input as for_role(role, tool)
}

test_every_catalogue_tool_is_granted_to_some_role if {
  some tool in all_tools
  some role in object.keys(expected_role_tools)
  tool in expected_role_tools[role]
}

test_roles_are_the_union_when_a_user_has_several if {
  tools_for_roles == {"crm.orders.list", "refunds.quote", "refunds.issue", "crm.customer.read", "tickets.read"} with input as object.union(base, {"roles": ["read_only", "billing"]})
}

# =============================================================================
# Per-tenant matrices (S8)
#
# The same role name, different power, decided by which customer you belong to.
# =============================================================================
for_tenant(tenant, role, tool) := object.union(base, {
  "tenant": tenant,
  "roles": [role],
  "tool": tool,
  "amount": 25,
})

# --- the demonstration: globex's support_rep loses refunds.issue -------------

test_acme_support_rep_may_issue_a_refund if {
  decision != "deny" with input as for_tenant("acme", "support_rep", "refunds.issue")
}

test_globex_support_rep_may_not_issue_a_refund if {
  decision == "deny" with input as for_tenant("globex", "support_rep", "refunds.issue")
}

test_the_globex_refusal_names_the_tool if {
  reason == "denied: your role may not call refunds.issue" with input as for_tenant("globex", "support_rep", "refunds.issue")
}

# It is a *replacement*, not a subtraction of one tool: the rest still works.
test_globex_support_rep_keeps_the_rest_of_the_role if {
  some tool in ["crm.customer.read", "crm.orders.list", "tickets.read", "tickets.reply.draft", "refunds.quote"]
  decision != "deny" with input as for_tenant("globex", "support_rep", tool)
}

# An override replaces the default entirely — nothing is merged in.
test_an_override_replaces_rather_than_extends if {
  role_tools_for("globex", "support_rep") == {
    "crm.customer.read", "crm.orders.list", "tickets.read", "tickets.reply.draft", "refunds.quote",
  }
}

# --- a role the tenant does not mention falls back to the default ------------

test_an_unmentioned_role_falls_back_to_the_default if {
  role_tools_for("globex", "manager") == default_role_tools["manager"]
}

test_an_unknown_tenant_gets_the_default_matrix if {
  role_tools_for("nowhere", "support_rep") == default_role_tools["support_rep"]
}

test_a_role_defined_nowhere_has_no_tools if {
  not role_tools_for("acme", "no_such_role")
}

# --- what the agent asks for is tenant-scoped too ----------------------------

test_the_offered_tools_are_tenant_scoped if {
  tools_for_roles == {
    "crm.customer.read", "crm.orders.list", "tickets.read", "tickets.reply.draft", "refunds.quote",
  } with input as object.union(base, {"tenant": "globex"})
}

test_an_unscoped_caller_is_offered_nothing if {
  tools_for_roles == set() with input as object.remove(base, ["tenant"])
}

# --- the matrix the Roles page reads -----------------------------------------

test_the_matrix_shows_the_callers_tenant if {
  role_matrix["support_rep"] == role_tools_for("globex", "support_rep") with input as {"tenant": "globex"}
}

test_the_matrix_is_undefined_without_a_tenant if {
  not role_matrix with input as {}
}

# --- the data stays honest ----------------------------------------------------

# A tenant override may only mention roles that exist, or the default matrix and
# the override would disagree about what a role even is.
test_tenant_overrides_only_name_known_roles if {
  some _, per_role in tenant_role_tools
  some role, _ in per_role
  role in object.keys(default_role_tools)
}

# Every tenant override names real tools, so a typo cannot quietly remove access.
test_tenant_overrides_only_name_catalogue_tools if {
  some _, per_role in tenant_role_tools
  some _, tools in per_role
  some tool in tools
  tool in all_tools
}

# --- unknown tools and the reason chain -------------------------------------

test_an_unknown_tool_is_denied if {
  decision == "deny" with input as object.union(base, {"tool": "admin.delete_everything"})
    with data.tools as all_tools
}

test_a_tool_outside_the_catalogue_is_denied if {
  reason == "denied: admin.wipe is not a known tool" with input as object.union(base, {"tool": "admin.wipe"})
    with data.tools as all_tools
}

# The reason is an `else` chain, so overlapping conditions still yield ONE string
# (separate rules would return a set, which the SDK, audit and UI cannot read).
test_reason_is_always_a_single_string if {
  some doc in [
    base,
    refund(1000),
    refund(0),
    object.remove(base, ["tenant"]),
    object.union(base, {"agent": ROGUE}),
    object.union(base, {"roles": ["read_only"], "tool": "refunds.issue", "amount": 0}),
    object.union(base, {"roles": ["read_only"], "tool": "bulk.refund"}),
    object.union(base, {"tool": "admin.wipe"}),
  ]
  is_string(reason) with input as doc
}

test_a_denied_role_gets_a_clear_reason if {
  reason == "denied: your role may not call refunds.issue" with input as for_role("read_only", "refunds.issue")
}
