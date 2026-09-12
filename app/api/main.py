"""The platform API: human approvals, agent tasks, and the audit timeline.

Endpoints:
    POST /demo/login               demo-only: mint a token for a seeded user
    POST /tasks                    start an agent run (proxied to the agent svc)
    POST /tasks/resume             resume a paused run
    POST /approvals                create a pending approval (agent's token)
    GET  /approvals?status=pending the approval queue
    POST /approvals/{id}/decision  approve/deny (approver's token)
    POST /approvals/verify         used by tool servers (in trust domain)
    POST /audit/events             ingest an audit record (from the services)
    GET  /audit                    the audit timeline (newest first)
    GET  /                         the web UI (when a build is present)

Callers are authenticated with an exchanged token. The `/demo/login` endpoint is
a convenience for the local demo and is called out as such.
"""
from __future__ import annotations

import os
from collections import deque
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agentnhi import Settings, TokenRejected, TokenVerifier, audit
from agentnhi.tokens import Delegation
from app.approvals import ApprovalStore

app = FastAPI(title="agent-identity-platform API")
_store = ApprovalStore()
_audit: deque[dict] = deque(maxlen=500)
_verifier: TokenVerifier | None = None

# Human demo logins are documented values (see docs/guides). The CLIENT secrets
# are not: they are generated into a gitignored .env and mounted from the
# platform-secrets Secret, so no client secret is ever committed.
DEMO_USERS = {
    "alice": ("alice123", "demo-cli", os.environ.get("DEMO_CLI_SECRET", "")),
    "manager": ("manager123", "manager-cli", os.environ.get("MANAGER_CLI_SECRET", "")),
}


def get_store() -> ApprovalStore:
    return _store


def get_verifier() -> TokenVerifier:
    global _verifier
    if _verifier is None:
        _verifier = TokenVerifier(Settings.from_env())
    return _verifier


def current_delegation(
    authorization: str | None = Header(default=None),
    verifier: TokenVerifier = Depends(get_verifier),
) -> Delegation:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return verifier.verify(token)
    except TokenRejected as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


# ---------------------------------------------------------------------------
# Demo login (local demo convenience)
# ---------------------------------------------------------------------------
@app.post("/demo/login")
def demo_login(body: dict) -> dict:
    username = body.get("user", "")
    if username not in DEMO_USERS:
        raise HTTPException(status_code=400, detail="unknown demo user")
    password, client_id, secret = DEMO_USERS[username]
    issuer = Settings.from_env().keycloak_issuer
    resp = httpx.post(
        f"{issuer}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": secret,
            "username": username,
            "password": password,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="login failed")
    return {"user": username, "access_token": resp.json()["access_token"]}


# ---------------------------------------------------------------------------
# Agent tasks (proxied to the agent service)
# ---------------------------------------------------------------------------
def _agent_url() -> str:
    return os.environ.get("AGENT_URL", "http://agent:8081").rstrip("/")


@app.post("/tasks")
def start_task(body: dict, authorization: str | None = Header(default=None)) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    resp = httpx.post(
        f"{_agent_url()}/run",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
    return resp.json()


@app.post("/tasks/resume")
def resume_task(body: dict) -> dict:
    resp = httpx.post(f"{_agent_url()}/resume", json=body, timeout=120)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
    return resp.json()


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------
@app.post("/approvals")
def create_approval(
    body: dict,
    delegation: Delegation = Depends(current_delegation),
    store: ApprovalStore = Depends(get_store),
) -> dict:
    tool = body.get("tool")
    if not tool:
        raise HTTPException(status_code=400, detail="tool is required")
    approval = store.create(
        tool=tool,
        args=body.get("args", {}),
        user=delegation.user,
        agent=delegation.workload,
        reason=body.get("reason", ""),
    )
    audit(
        "approval.created",
        approval_id=approval.id,
        spiffe_id=delegation.workload,
        sub=delegation.user,
        tool=tool,
    )
    return approval.as_dict()


@app.get("/approvals")
def list_approvals(
    status: str | None = None,
    store: ApprovalStore = Depends(get_store),
) -> list[dict]:
    items = store.pending() if status == "pending" else list(store._items.values())  # noqa: SLF001
    return [a.as_dict() for a in items]


@app.post("/approvals/verify")
def verify_approval(body: dict, store: ApprovalStore = Depends(get_store)) -> dict:
    """Called by the tool server. The approvals service is the authority here."""
    valid = store.verify(
        body.get("approval_id", ""),
        tool=body.get("tool", ""),
        args=body.get("args", {}),
        user=body.get("user", ""),
        agent=body.get("agent", ""),
    )
    return {"valid": valid}


@app.post("/approvals/{approval_id}/decision")
def decide_approval(
    approval_id: str,
    body: dict,
    delegation: Delegation = Depends(current_delegation),
    store: ApprovalStore = Depends(get_store),
) -> dict:
    approval = store.decide(
        approval_id,
        approver=delegation.user,
        approved=bool(body.get("approved")),
        note=body.get("note"),
    )
    if approval is None:
        raise HTTPException(
            status_code=409,
            detail="approval not found, already decided, or self-approval is not allowed",
        )
    audit(
        "approval.decided",
        approval_id=approval.id,
        approver=delegation.user,
        decision=approval.status,
        tool=approval.tool,
    )
    return approval.as_dict()


# ---------------------------------------------------------------------------
# Audit timeline
# ---------------------------------------------------------------------------
@app.post("/audit/events")
def ingest_audit(record: dict) -> dict:
    _audit.appendleft(record)
    return {"ok": True}


@app.get("/audit")
def get_audit(limit: int = 100) -> list[dict]:
    return list(_audit)[: max(1, min(limit, 500))]


# ---------------------------------------------------------------------------
# Web UI (served from the same origin when a build is present)
# ---------------------------------------------------------------------------
_WEB_DIR = Path(os.environ.get("WEB_DIR", "/workspace/app/web/dist"))
if _WEB_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_WEB_DIR / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_WEB_DIR / "index.html")
