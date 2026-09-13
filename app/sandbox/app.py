"""The sandbox service: the simulators exposed over the REST contract.

It stands in for a real CRM / orders / payments / ticketing API, so the tools'
HTTP backend (`TOOLS_BACKEND=http`) can be exercised end to end without vendor
credentials. Point `SANDBOX_BASE_URL` at a real sandbox to replace it — the
contract is all the tools know about.

Every request **must** carry `X-Tenant`, and every lookup is scoped to it: a
record from another tenant is a 404, exactly as if it did not exist.
"""
from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

from app.simulators import crm, orders, payments, tickets

app = FastAPI(title="sandbox")


def _tenant(x_tenant: str | None) -> str:
    if not x_tenant:
        raise HTTPException(status_code=400, detail="X-Tenant header is required")
    return x_tenant


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/customers/{customer_id}")
def get_customer(customer_id: str, x_tenant: str | None = Header(default=None)) -> dict:
    customer = crm.get_customer(customer_id, _tenant(x_tenant))
    if customer is None:
        raise HTTPException(status_code=404, detail="unknown customer")
    return customer


@app.get("/customers/{customer_id}/pii")
def get_pii(customer_id: str, x_tenant: str | None = Header(default=None)) -> dict:
    pii = crm.get_pii(customer_id, _tenant(x_tenant))
    if pii is None:
        raise HTTPException(status_code=404, detail="unknown customer")
    return pii


@app.get("/customers/{customer_id}/orders")
def list_orders(customer_id: str, x_tenant: str | None = Header(default=None)) -> dict:
    return {"orders": orders.list_orders(customer_id, _tenant(x_tenant))}


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, x_tenant: str | None = Header(default=None)) -> dict:
    ticket = tickets.get_ticket(ticket_id, _tenant(x_tenant))
    if ticket is None:
        raise HTTPException(status_code=404, detail="unknown ticket")
    return ticket


@app.post("/tickets/{ticket_id}/drafts")
def draft_reply(ticket_id: str, body: dict, x_tenant: str | None = Header(default=None)) -> dict:
    return tickets.draft_reply(ticket_id, body.get("body", ""), _tenant(x_tenant))


@app.get("/orders/{order_id}/refund-quote")
def quote_refund(order_id: str, x_tenant: str | None = Header(default=None)) -> dict:
    quote = payments.quote_refund(order_id, _tenant(x_tenant))
    if quote is None:
        raise HTTPException(status_code=404, detail="unknown order")
    return quote


@app.post("/orders/{order_id}/refunds")
def issue_refund(order_id: str, body: dict, x_tenant: str | None = Header(default=None)) -> dict:
    return payments.issue_refund(order_id, float(body.get("amount", 0)), _tenant(x_tenant))
