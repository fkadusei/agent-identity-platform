"""Agent service: start a run, and resume it after a human decision.

Run state (the LangGraph checkpoint) lives in this process, so a run that pauses
for approval can be resumed here once a decision is recorded. In production the
checkpointer would be a shared store (Postgres/Redis) so any replica can resume.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from app.agent.graph import build_agent, resume_task, run_task
from app.agent.live import LiveDeps

app = FastAPI(title="agent service")
_runs: dict[str, Any] = {}


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
    agent = build_agent(LiveDeps(user_token=token))
    _runs[thread_id] = agent
    outcome = run_task(agent, task, thread_id, token)
    return {"thread_id": thread_id, **outcome}


@app.post("/resume")
def resume(body: dict) -> dict:
    thread_id = body.get("thread_id")
    agent = _runs.get(thread_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown thread_id")
    outcome = resume_task(agent, thread_id, bool(body.get("approved")))
    return {"thread_id": thread_id, **outcome}
