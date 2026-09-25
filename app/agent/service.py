"""Agent service: start a run, and resume it after a human decision.

The graph state lives in Postgres when `DATABASE_URL` is set, so a paused run
survives a restart and any replica can resume it. The *token* to act with is not
durable (it must not be), so a resume that lands on a process which never saw the
run carries the caller's token again — see `/resume`.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from agentnhi import Settings, TokenRejected, TokenVerifier, audit
from agentnhi.tokens import Delegation

from app.agent.graph import build_agent, resume_task, run_task
from app.agent.guardrails import GuardrailError, check_task
from app.agent.live import LiveDeps
from app.common.audit_forward import enable_forwarding
from app.common.db import database_configured, database_url
from app.common.telemetry import instrument_fastapi, setup_telemetry

app = FastAPI(title="agent service")
enable_forwarding()
setup_telemetry("agent")
instrument_fastapi(app)
_runs: dict[str, Any] = {}
_verifier: TokenVerifier | None = None
_checkpointer: Any = None
_checkpointer_ready = False
_pool: Any = None


def _delegation(token: str) -> Delegation:
    """Verify the caller's token before doing anything with it.

    The agent accepts tokens audienced to *itself* (its SPIFFE ID). The client
    that logged the user in (`azp`) is not constrained, and the roles it returns
    decide which tools the model is offered.
    """
    global _verifier
    if _verifier is None:
        base = Settings.from_env()
        _verifier = TokenVerifier(
            Settings(
                keycloak_issuer=base.keycloak_issuer,
                audience=os.environ.get("AGENT_SPIFFE_ID", ""),
                trusted_workload=None,
            )
        )
    return _verifier.verify(token)


def get_checkpointer() -> Any:
    """A durable, **pooled** checkpointer when a database is configured, else None.

    A pool rather than a single connection, because the checkpointer checks a
    connection out per operation and a pool replaces the dead ones. With one bare
    connection, a Postgres restart killed that socket and every run then failed in
    0.1s with `psycopg.OperationalError: server closed the connection
    unexpectedly` — forever, until the agent process was restarted, and looking
    like a dozen other errors from the outside (S12).

    `check=ConnectionPool.check_connection` makes the recovery transparent to the
    first request after the restart: a dead connection is detected at checkout and
    swapped for a live one, instead of being handed out to fail once.
    """
    global _checkpointer, _checkpointer_ready, _pool
    if not _checkpointer_ready:
        _checkpointer_ready = True
        if database_configured():
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg_pool import ConnectionPool

            # An empty conninfo lets libpq build the DSN from the PG* variables,
            # which is how the manifests pass the password (a Secret reference),
            # so no credential is ever assembled into a URL.
            _pool = ConnectionPool(
                conninfo=database_url() or "",
                # The application_name shows which backends are the checkpointer's
                # in pg_stat_activity — the same handle the S12 test uses to
                # simulate a restart by closing exactly those.
                kwargs={"autocommit": True, "application_name": "agent-checkpointer"},
                min_size=1,
                max_size=5,
                check=ConnectionPool.check_connection,
                open=True,
            )
            _checkpointer = PostgresSaver(_pool)

    if _checkpointer is not None:
        # Idempotent, and the same defence the approvals and audit stores apply
        # per operation: a database can come back without the schema under a
        # running agent (a restored or replaced volume, or a wiped demo). Without
        # this the pool would reconnect cleanly and the run would then fail with
        # "relation checkpoints does not exist".
        _checkpointer.setup()

    return _checkpointer


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/run")
def run(body: dict, authorization: str | None = Header(default=None)) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    task = body.get("task")
    if not task:
        raise HTTPException(status_code=400, detail="task is required")
    try:
        check_task(task)
    except GuardrailError as exc:
        audit("agent.task_refused", reason=str(exc)[:200])
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        delegation = _delegation(token)
    except TokenRejected as exc:
        raise HTTPException(status_code=403, detail=f"identity rejected: {exc}")

    thread_id = body.get("thread_id") or f"t-{uuid.uuid4().hex[:8]}"
    agent = build_agent(
        LiveDeps(user_token=token, tenant=delegation.tenant, roles=delegation.roles), checkpointer=get_checkpointer()
    )
    _runs[thread_id] = agent
    outcome = run_task(agent, task, thread_id, token)
    if outcome.get("status") == "refused":
        # The agent declined to act. Nothing reached the tool server, so there is
        # no tool.denied to find later — without this the only trace is a stdout
        # line, and "who asked for something they may not have" is invisible.
        # The task text is deliberately NOT recorded: it is free-form, and may
        # itself contain the personal data this record is meant to protect.
        audit(
            "agent.refused",
            sub=delegation.user,
            tenant=delegation.tenant or "",
            tool=outcome.get("refused_tool") or "",
            reason=outcome.get("reason", "")[:200],
        )
    elif outcome.get("status") == "clarification_required":
        # A question, recorded like any other pause. The answer is not an
        # approval, so this says what was asked for and nothing more.
        audit(
            "agent.clarification_requested",
            sub=delegation.user,
            tenant=delegation.tenant or "",
            tool=outcome.get("tool") or "",
            missing=",".join(outcome.get("missing") or []),
        )
    return {"thread_id": thread_id, **outcome}


@app.post("/resume")
def resume(body: dict, authorization: str | None = Header(default=None)) -> dict:
    thread_id = body.get("thread_id")
    token = (authorization or "").removeprefix("Bearer ").strip()

    agent = _runs.get(thread_id)
    if agent is None:
        # This process never saw the run (e.g. it restarted). If the graph state
        # is durable we can rebuild the agent from the caller's token and resume.
        if not (token and get_checkpointer()):
            raise HTTPException(status_code=404, detail="unknown thread_id")
        try:
            delegation = _delegation(token)
        except TokenRejected as exc:
            raise HTTPException(status_code=403, detail=f"identity rejected: {exc}")
        agent = build_agent(
            LiveDeps(user_token=token, tenant=delegation.tenant, roles=delegation.roles),
            checkpointer=get_checkpointer(),
        )
        _runs[thread_id] = agent

    # One resume endpoint for both pauses: an approval sends {"approved": bool},
    # a clarification sends {"values": {...}}. They are kept apart on purpose —
    # supplying a fact is not granting a permission.
    if "values" in body:
        decision: dict = {"values": body.get("values") or {}}
    else:
        decision = {"approved": bool(body.get("approved"))}
    outcome = resume_task(agent, thread_id, decision)
    return {"thread_id": thread_id, **outcome}


def main() -> None:
    """Serve the agent: SPIFFE mTLS for the api, plain for the user path (S7)."""
    from app.common.server import run

    run(
        "app.agent.service:app",
        int(os.environ.get("SPIFFE_PORT", "8443")),
        service="agent",
        edge_port=int(os.environ.get("PORT", "8081")),
    )


if __name__ == "__main__":
    main()
