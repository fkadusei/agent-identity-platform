"""The agent reads the role -> tool matrix from the policy, not a copy."""
from __future__ import annotations

import json

import httpx

from app.common.policy import role_matrix, tools_for_roles


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_tools_for_roles_asks_the_policy():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/data/agentnhi/authz/tools_for_roles"
        assert b"support_rep" in request.content
        return httpx.Response(200, json={"result": ["crm.customer.read", "refunds.issue"]})

    got = tools_for_roles("http://opa:8181", ["support_rep"], "acme", client=_client(handler))
    assert got == {"crm.customer.read", "refunds.issue"}


def test_the_tenant_travels_with_the_query():
    """The matrix can differ per tenant (S8), so the tenant is asked about."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content)["input"])
        return httpx.Response(200, json={"result": []})

    tools_for_roles("http://opa:8181", ["support_rep"], "globex", client=_client(handler))
    assert seen == {"roles": ["support_rep"], "tenant": "globex"}


def test_an_unscoped_caller_still_names_its_absence():
    """A missing tenant is sent as null rather than omitted, so policy denies it
    explicitly instead of reading an accidentally-defaulted matrix."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content)["input"])
        return httpx.Response(200, json={"result": []})

    tools_for_roles("http://opa:8181", ["support_rep"], None, client=_client(handler))
    assert seen == {"roles": ["support_rep"], "tenant": None}


def test_tools_for_roles_fails_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    got = tools_for_roles("http://opa:8181", ["support_rep"], "acme", client=_client(handler))
    # Policy unreachable -> offer nothing, rather than everything.
    assert got == set()


def test_tools_for_roles_handles_no_roles():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    assert tools_for_roles("http://opa:8181", [], "acme", client=_client(handler)) == set()


def test_role_matrix_is_asked_for_one_tenant():
    """The Roles page must describe the caller's tenant, not the global default."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/data/agentnhi/authz/role_matrix"
        seen.update(json.loads(request.content)["input"])
        return httpx.Response(200, json={"result": {"read_only": ["crm.customer.read"]}})

    got = role_matrix("http://opa:8181", "globex", client=_client(handler))
    assert seen == {"tenant": "globex"}
    assert got == {"read_only": ["crm.customer.read"]}


def test_role_matrix_is_empty_when_policy_cannot_answer():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    assert role_matrix("http://opa:8181", "acme", client=_client(handler)) == {}
