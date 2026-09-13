"""The sandbox exposes the simulator data over the REST contract the tools speak."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.sandbox.app import app

client = TestClient(app)


def test_healthz():
    assert client.get("/healthz").json() == {"ok": True}


def test_customer_roundtrip():
    resp = client.get("/customers/c-100")
    assert resp.status_code == 200
    assert resp.json()["id"] == "c-100"


def test_unknown_customer_is_404():
    assert client.get("/customers/nope").status_code == 404


def test_orders_are_wrapped_in_an_envelope():
    resp = client.get("/customers/c-100/orders")
    assert resp.status_code == 200
    assert isinstance(resp.json()["orders"], list)


def test_pii_endpoint():
    resp = client.get("/customers/c-100/pii")
    assert resp.status_code == 200


def test_refund_quote_and_issue():
    quote = client.get("/orders/o-1001/refund-quote")
    assert quote.status_code == 200

    issued = client.post("/orders/o-1001/refunds", json={"amount": 25})
    assert issued.status_code == 200
    assert issued.json().get("status") == "issued"


def test_ticket_draft():
    resp = client.post("/tickets/t-5001/drafts", json={"body": "hello"})
    assert resp.status_code == 200
