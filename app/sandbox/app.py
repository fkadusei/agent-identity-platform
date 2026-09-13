"""The sandbox service: the simulators exposed over the REST contract.

It stands in for a real CRM / orders / payments / ticketing API, so the tools'
HTTP backend (`TOOLS_BACKEND=http`) can be exercised end to end without vendor
credentials. Point `SANDBOX_BASE_URL` at a real sandbox to replace it — the
contract is all the tools know about.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.simulators import crm, orders, payments, tickets

app = FastAPI(title="sandbox")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/customers/{customer_id}")
def get_customer(customer_id: str) -> dict:
    customer = crm.get_customer(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="unknown customer")
    return customer


@app.get("/customers/{customer_id}/pii")
def get_pii(customer_id: str) -> dict:
    pii = crm.get_pii(customer_id)
    if pii is None:
        raise HTTPException(status_code=404, detail="unknown customer")
    return pii


@app.get("/customers/{customer_id}/orders")
def list_orders(customer_id: str) -> dict:
    return {"orders": orders.list_orders(customer_id)}


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str) -> dict:
    ticket = tickets.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="unknown ticket")
    return ticket


@app.post("/tickets/{ticket_id}/drafts")
def draft_reply(ticket_id: str, body: dict) -> dict:
    return tickets.draft_reply(ticket_id, body.get("body", ""))


@app.get("/orders/{order_id}/refund-quote")
def quote_refund(order_id: str) -> dict:
    quote = payments.quote_refund(order_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="unknown order")
    return quote


@app.post("/orders/{order_id}/refunds")
def issue_refund(order_id: str, body: dict) -> dict:
    return payments.issue_refund(order_id, float(body.get("amount", 0)))
