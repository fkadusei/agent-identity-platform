"""The sandbox exposes the simulator data over the REST contract, scoped by tenant."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.sandbox.app import app

client = TestClient(app)
ACME = {"X-Tenant": "acme"}
GLOBEX = {"X-Tenant": "globex"}


def test_healthz():
    assert client.get("/healthz").json() == {"ok": True}


def test_customer_roundtrip():
    resp = client.get("/customers/c-100", headers=ACME)
    assert resp.status_code == 200
    assert resp.json()["id"] == "c-100"


def test_unknown_customer_is_404():
    assert client.get("/customers/nope", headers=ACME).status_code == 404


def test_missing_tenant_header_is_400():
    assert client.get("/customers/c-100").status_code == 400


def test_another_tenants_customer_is_404():
    # globex's customer is invisible to an acme session, and vice versa.
    assert client.get("/customers/c-900", headers=ACME).status_code == 404
    assert client.get("/customers/c-900", headers=GLOBEX).status_code == 200


def test_orders_are_wrapped_in_an_envelope():
    resp = client.get("/customers/c-100/orders", headers=ACME)
    assert resp.status_code == 200
    assert isinstance(resp.json()["orders"], list)


def test_pii_endpoint():
    assert client.get("/customers/c-100/pii", headers=ACME).status_code == 200
    assert client.get("/customers/c-900/pii", headers=ACME).status_code == 404


def test_refund_quote_and_issue():
    quote = client.get("/orders/o-1001/refund-quote", headers=ACME)
    assert quote.status_code == 200

    issued = client.post("/orders/o-1001/refunds", json={"amount": 25}, headers=ACME)
    assert issued.status_code == 200
    assert issued.json().get("status") == "issued"


def test_another_tenants_order_is_404():
    assert client.get("/orders/o-9001/refund-quote", headers=ACME).status_code == 404


def test_ticket_draft():
    resp = client.post("/tickets/t-5001/drafts", json={"body": "hello"}, headers=ACME)
    assert resp.status_code == 200
    assert client.get("/tickets/t-9001", headers=ACME).status_code == 404
