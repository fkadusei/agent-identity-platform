"""Agent service: start a run, and resume it after a human decision.

The graph state lives in Postgres when `DATABASE_URL` is set, so a paused run
survives a restart and any replica can resume it. The *token* to act with is not
durable (it must not be), so a resume that lands on a process which never saw the
run carries the caller's token again — see `/resume`.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from app.agent.graph import build_agent, resume_task, run_task
from app.agent.live import LiveDeps
from app.common.audit_forward import enable_forwarding
from app.common.db import connect, database_configured, database_url
from app.common.telemetry import instrument_fastapi, setup_telemetry

app = FastAPI(title="agent service")
enable_forwarding()
setup_telemetry("agent")
instrument_fastapi(app)
_runs: dict[str, Any] = {}
_checkpointer: Any = None
_checkpointer_ready = False


def get_checkpointer() -> Any:
    """A durable checkpointer when DATABASE_URL is set, else None (in-memory)."""
    global _checkpointer, _checkpointer_ready
    if not _checkpointer_ready:
        _checkpointer_ready = True
        if database_configured():
            from langgraph.checkpoint.postgres import PostgresSaver

            saver = PostgresSaver(connect(database_url()))
            saver.setup()
            _checkpointer = saver
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

    thread_id = body.get("thread_id") or f"t-{uuid.uuid4().hex[:8]}"
    agent = build_agent(LiveDeps(user_token=token), checkpointer=get_checkpointer())
    _runs[thread_id] = agent
    outcome = run_task(agent, task, thread_id, token)
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
        agent = build_agent(LiveDeps(user_token=token), checkpointer=get_checkpointer())
        _runs[thread_id] = agent

    outcome = resume_task(agent, thread_id, bool(body.get("approved")))
    return {"thread_id": thread_id, **outcome}
