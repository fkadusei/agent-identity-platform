"""The HTTP backend speaks the REST contract; the simulator backend is default."""
from __future__ import annotations

import json

import httpx

from app.tools.backends import HttpBackend, SimulatorBackend


def _backend(handler) -> HttpBackend:
    return HttpBackend(
        base_url="http://sandbox:8090",
        token="tok",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_get_customer_hits_the_contract_path_with_auth():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/customers/c-100"
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json={"id": "c-100", "name": "Ada"})

    assert _backend(handler).get_customer("c-100")["name"] == "Ada"


def test_404_maps_to_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    assert _backend(handler).get_customer("nope") is None


def test_list_orders_unwraps_the_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/customers/c-100/orders"
        return httpx.Response(200, json={"orders": [{"id": "o-1"}]})

    assert _backend(handler).list_orders("c-100") == [{"id": "o-1"}]


def test_issue_refund_posts_the_amount():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/orders/o-1/refunds"
        assert json.loads(request.content) == {"amount": 25.0}
        return httpx.Response(200, json={"id": "r-1", "status": "issued"})

    assert _backend(handler).issue_refund("o-1", 25)["status"] == "issued"


def test_simulator_backend_is_the_default_shape():
    assert SimulatorBackend().get_customer("c-100") is not None


def test_tools_call_the_injected_backend():
    from app.tools.catalog import build_tools

    class Fake:
        def get_customer(self, customer_id: str):
            return {"id": customer_id, "name": "FromRealSystem"}

    tools = build_tools(Fake())
    assert tools["crm.customer.read"].handler(customer_id="c-100")["name"] == "FromRealSystem"
