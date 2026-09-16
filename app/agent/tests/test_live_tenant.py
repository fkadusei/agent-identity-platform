"""The agent asks for the caller's tools *in their tenant*.

The bug this guards: the agent offers the model only the tools a role may call, so
the model cannot pick one the tool server will then deny. If it asked the policy
without a tenant, a tenant whose matrix differs (S8) would be offered a tool its
own policy refuses — the substitution the agent exists to prevent.
"""
from __future__ import annotations

from agentnhi import Settings

from app.agent.live import LiveDeps
from app.tools.catalog import TOOLS


def test_allowed_tools_are_read_for_the_callers_tenant(monkeypatch):
    seen: dict = {}

    def fake_tools_for_roles(opa_url, roles, tenant, **_kwargs):
        seen["opa_url"] = opa_url
        seen["roles"] = tuple(roles)
        seen["tenant"] = tenant
        return {"crm.customer.read"}

    monkeypatch.setattr("app.common.policy.tools_for_roles", fake_tools_for_roles)

    deps = LiveDeps(
        user_token="token",
        tenant="globex",
        roles=("support_rep",),
        settings=Settings(opa_url="http://opa:8181"),
    )
    allowed = deps.allowed_tools()

    assert seen == {
        "opa_url": "http://opa:8181",
        "roles": ("support_rep",),
        "tenant": "globex",
    }
    # Offered = the catalogue filtered to what the policy granted, not the whole
    # catalogue.
    assert allowed == {"crm.customer.read": TOOLS["crm.customer.read"]}


def test_an_unscoped_caller_is_offered_nothing(monkeypatch):
    """Fails closed: policy resolves no tools without a tenant, so neither do we."""
    monkeypatch.setattr("app.common.policy.tools_for_roles", lambda *_a, **_k: set())

    deps = LiveDeps(
        user_token="token",
        tenant=None,
        roles=("support_rep",),
        settings=Settings(opa_url="http://opa:8181"),
    )
    assert deps.allowed_tools() == {}
