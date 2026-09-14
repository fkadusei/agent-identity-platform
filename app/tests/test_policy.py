"""The agent reads the role -> tool matrix from the policy, not a copy."""
from __future__ import annotations

import httpx

from app.common.policy import tools_for_roles


def test_tools_for_roles_asks_the_policy():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/data/agentnhi/authz/tools_for_roles"
        assert b"support_rep" in request.content
        return httpx.Response(200, json={"result": ["crm.customer.read", "refunds.issue"]})

    got = tools_for_roles(
        "http://opa:8181",
        ["support_rep"],
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert got == {"crm.customer.read", "refunds.issue"}


def test_tools_for_roles_fails_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    got = tools_for_roles(
        "http://opa:8181", ["support_rep"], client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    # Policy unreachable -> offer nothing, rather than everything.
    assert got == set()


def test_tools_for_roles_handles_no_roles():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    assert (
        tools_for_roles("http://opa:8181", [], client=httpx.Client(transport=httpx.MockTransport(handler)))
        == set()
    )
