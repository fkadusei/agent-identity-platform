"""The sandbox service: the simulators exposed over the REST contract.

It stands in for a real CRM / orders / payments / ticketing API, so the tools'
HTTP backend (`TOOLS_BACKEND=http`) can be exercised end to end without vendor
credentials. Point `SANDBOX_BASE_URL` at a real sandbox to replace it — the
contract is all the tools know about.

Every request **must** carry `X-Tenant`, and every lookup is scoped to it: a
record from another tenant is a 404, exactly as if it did not exist.

The systems it stands in for keep their data: refunds and drafts are written to
the snapshot in `SANDBOX_STATE_PATH` (S9), so restarting this pod does not reset
the demo. See `app/sandbox/persistence.py`.
"""
from __future__ import annotations

import contextlib
import json
import os
from collections.abc import AsyncIterator
from contextvars import ContextVar

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.sandbox import auth
from app.sandbox.persistence import SandboxState
from app.simulators import crm, orders, payments, tickets
from app.simulators import restore, snapshot
from app.simulators.errors import NotFound

STATE = SandboxState(os.environ.get("SANDBOX_STATE_PATH"))


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Pick up whatever the simulated systems had before this process started, so
    # a restart continues the demo instead of resetting it (S9).
    restore(**STATE.load())
    yield


app = FastAPI(title="sandbox", lifespan=_lifespan)

#: The caller's identity for the current request — from the OBO token when one is
#: required, else the `X-Tenant` header (S28).
_ctx: ContextVar[dict] = ContextVar("sandbox_ctx", default={})


@app.middleware("http")
async def _identify(request: Request, call_next):
    """Resolve who is calling: a bearer token when required, else `X-Tenant`."""
    ctx: dict = {"tenant": None, "user": None}
    if auth.enabled() and request.url.path != "/healthz":
        try:
            claims = auth.verify(request.headers.get("authorization"))
        except Exception:  # noqa: BLE001 - any failure is a refusal
            return JSONResponse(
                {"detail": "a valid bearer token is required"}, status_code=401
            )
        ctx["tenant"] = claims.get("tenant")
        ctx["user"] = claims.get("preferred_username") or claims.get("sub")
        # The identity the vendor now sees — synthetic, like the rest of the demo.
        print(
            json.dumps(
                {
                    "event": "sandbox.call",
                    "sub": ctx["user"],
                    "tenant": ctx["tenant"],
                    "path": request.url.path,
                }
            ),
            flush=True,
        )
    handle = _ctx.set(ctx)
    try:
        return await call_next(request)
    finally:
        _ctx.reset(handle)


def _persist() -> None:
    """Snapshot the runtime state after a write. Never fatal."""
    STATE.save(**snapshot())


def _tenant(x_tenant: str | None) -> str:
    # The OBO token's tenant wins; the header is the fallback (a local run, tests).
    tenant = _ctx.get().get("tenant") or x_tenant
    if not tenant:
        raise HTTPException(
            status_code=400, detail="X-Tenant header or a bearer token is required"
        )
    return tenant


def _simulate(call):
    """Run a simulator write, mapping its refusals onto HTTP status codes.

    The simulators signal a record that is not there *for this tenant* with
    `NotFound`, and any other refusal with `ValueError`. Left unhandled, the
    former became a 500 — which is neither true (nothing is broken) nor what the
    read endpoints report. A missing record is a 404 here too, exactly as if it
    did not exist; anything else it rejects is bad input.
    """
    try:
        return call()
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    draft = _simulate(lambda: tickets.draft_reply(ticket_id, body.get("body", ""), _tenant(x_tenant)))
    _persist()
    return draft


@app.get("/orders/{order_id}/refund-quote")
def quote_refund(order_id: str, x_tenant: str | None = Header(default=None)) -> dict:
    quote = payments.quote_refund(order_id, _tenant(x_tenant))
    if quote is None:
        raise HTTPException(status_code=404, detail="unknown order")
    return quote


@app.post("/orders/{order_id}/refunds")
def issue_refund(order_id: str, body: dict, x_tenant: str | None = Header(default=None)) -> dict:
    refund = _simulate(
        lambda: payments.issue_refund(
            order_id,
            float(body.get("amount", 0)),
            _tenant(x_tenant),
            # A resumed approval sends the same key, so the vendor answers with the
            # refund it already issued instead of issuing a second one (S24).
            body.get("idempotency_key"),
        )
    )
    _persist()
    return refund
