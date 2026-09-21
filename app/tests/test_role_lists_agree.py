"""The role lists must agree, because they did not once and nobody noticed.

`PLATFORM_ROLES` (what the api tells the UI a user is) was missing `billing` and
`read_only`. Both existed in the policy — so the platform let those users work — and in
the realm, which seeded them. The result was a signed-in user shown as having *no roles*
while their token carried one and the policy honoured it: capability and display
disagreeing, with the display being what a person believes.

Two comparisons, one per direction of that drift:

* the api against the **policy** — a role the policy enforces must be one the api reports;
* the api against the **realm** — a role the demo seeds onto a user must be one the api
  knows, or the seeded user is precisely the bella case.

Both read their source as text, since python cannot import rego and the realm is a
template. That is a deliberate trade: a parse can be brittle, and a silently skipped
check would be worse, so each parse asserts it found something.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REGO = ROOT / "policy" / "authz.rego"
REALM = ROOT / "deploy" / "kind" / "manifests" / "keycloak" / "realm.json.tmpl"


def api_roles() -> set[str]:
    from app.api.auth import PLATFORM_ROLES

    return set(PLATFORM_ROLES)


def policy_roles() -> set[str]:
    """The keys of `default_role_tools` — every role the policy has a matrix for.

    Top-level keys sit at two spaces of indentation; the tool names inside them are
    nested deeper, which is what makes this parse unambiguous.
    """
    text = REGO.read_text()
    block = text[text.index("default_role_tools") :]
    block = block[: block.index("\n}")] if "\n}" in block else block
    found = set(re.findall(r'^\s{2}"([a-z_]+)":', block, re.M))
    assert found, "parsed no roles out of default_role_tools — the parse has gone stale"
    return found


def seeded_roles() -> set[str]:
    """Every role the realm template assigns to a user."""
    raw = re.sub(r"\$\{[^}]+\}", "PLACEHOLDER", REALM.read_text())
    realm = json.loads(raw)
    found = {r for user in realm.get("users", []) for r in user.get("realmRoles") or []}
    assert found, "parsed no roles out of the realm — the parse has gone stale"
    return found


def test_the_api_reports_every_role_the_policy_enforces():
    missing = policy_roles() - api_roles()
    assert not missing, (
        f"the policy enforces {sorted(missing)}, which PLATFORM_ROLES does not report — "
        "a user holding one would be shown as having no roles"
    )
    assert not api_roles() - policy_roles(), (
        "PLATFORM_ROLES lists roles the policy has no matrix for: "
        f"{sorted(api_roles() - policy_roles())}"
    )


def test_every_role_the_realm_seeds_is_one_the_api_knows():
    unknown = seeded_roles() - api_roles()
    assert not unknown, (
        f"the realm seeds {sorted(unknown)}, which PLATFORM_ROLES does not know — those "
        "users would sign in looking unprivileged"
    )
