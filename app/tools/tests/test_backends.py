"""The HTTP backend speaks the REST contract; the simulator backend is default.

Every call carries the tenant, and the HTTP backend sends it as `X-Tenant`.
"""
from __future__ import annotations

import json

import httpx

from app.tools.backends import HttpBackend, SimulatorBackend

ACME = "acme"
GLOBEX = "globex"


def _backend(handler) -> HttpBackend:
    return HttpBackend(
        base_url="http://sandbox:8090",
        token="tok",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_get_customer_sends_the_tenant_and_auth_headers():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/customers/c-100"
        assert request.headers["x-tenant"] == ACME
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json={"id": "c-100", "name": "Ada"})

    assert _backend(handler).get_customer("c-100", ACME)["name"] == "Ada"


def test_404_maps_to_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    # The sandbox answers 404 for another tenant's record; the backend maps that
    # to "not found", the same as the simulator.
    assert _backend(handler).get_customer("c-900", ACME) is None


def test_list_orders_unwraps_the_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/customers/c-100/orders"
        return httpx.Response(200, json={"orders": [{"id": "o-1"}]})

    assert _backend(handler).list_orders("c-100", ACME) == [{"id": "o-1"}]


def test_issue_refund_posts_the_amount():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/orders/o-1/refunds"
        assert request.headers["x-tenant"] == ACME
        assert json.loads(request.content) == {"amount": 25.0}
        return httpx.Response(200, json={"id": "r-1", "status": "issued"})

    assert _backend(handler).issue_refund("o-1", 25, ACME)["status"] == "issued"


def test_simulator_backend_scopes_by_tenant():
    backend = SimulatorBackend()
    assert backend.get_customer("c-900", ACME) is None
    assert backend.get_customer("c-900", GLOBEX) is not None


def test_tools_call_the_injected_backend():
    from app.tools.catalog import build_tools

    class Fake:
        def get_customer(self, customer_id: str, tenant: str):
            return {"id": customer_id, "tenant": tenant, "name": "FromRealSystem"}

    tools = build_tools(Fake())
    got = tools["crm.customer.read"].handler(customer_id="c-100", tenant=ACME)
    assert got["name"] == "FromRealSystem"
    assert got["tenant"] == ACME
