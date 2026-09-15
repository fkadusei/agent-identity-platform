"""The platform API: login/enrollment, user administration, approvals, audit.

Endpoints:
    GET  /roles                    the role -> tool matrix (from policy)
    GET  /auth/config              is self-service signup enabled?
    POST /auth/login               username/password -> token (+roles)
    POST /enroll                   self-service account creation (no roles)
    GET  /admin/users              list users and their roles     (platform_admin)
    POST /admin/users              create a user                  (platform_admin)
    POST /admin/users/{id}/roles   grant a role                   (platform_admin)
    DELETE /admin/users/{id}/roles/{role}   revoke a role         (platform_admin)
    POST /admin/users/{id}/enabled enable/disable an account      (platform_admin)
    POST /admin/users/{id}/password reset a password              (platform_admin)
    DELETE /admin/users/{id}       delete a user                  (platform_admin)
    POST /tasks                    start an agent run (proxied to the agent svc)
    POST /tasks/resume             resume a paused run
    POST /approvals                create a pending approval (agent's token)
    GET  /approvals?status=pending the approval queue
    POST /approvals/{id}/decision  approve/deny                 (manager role)
    POST /approvals/verify         used by tool servers (in trust domain)
    POST /audit/events             ingest an audit record (from the services)
    GET  /audit                    the audit timeline (filter by event/tool/user)
    GET  /privacy/access           the PII access + approval trail   (manager)
    GET  /                         the web UI (when a build is present)

Callers are authenticated with a token (aud=mcp-tools). Authorization is by role
and checked **on the server** (app/api/authz.py); the UI hiding a button is
convenience, never the control.
"""
from __future__ import annotations

import os
from collections import deque
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agentnhi import audit
from agentnhi.tokens import Delegation
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.authz import current_delegation, require_roles
from app.api.roles import router as roles_router
from app.approvals import ApprovalStore
from app.approvals.store import build_store
from app.common import metrics
from app.common.telemetry import instrument_fastapi, setup_telemetry

app = FastAPI(title="agent-identity-platform API")
setup_telemetry("api")
instrument_fastapi(app)
# Dev convenience: the Vite dev server (localhost:5173) is a different origin
# from the API, so without this a browser fetch fails with "Failed to fetch".
# In production the UI is served same-origin, so this never applies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(roles_router)
# Durable when DATABASE_URL is set (a restart no longer forgets approvals).
_store = build_store()
_audit: deque[dict] = deque(maxlen=500)


@app.middleware("http")
async def _count_requests(request, call_next):
    """Count every request by its route template (low label cardinality)."""
    response = await call_next(request)
    route = request.scope.get("route")
    metrics.HTTP_REQUESTS.labels(
        request.method, getattr(route, "path", "unknown"), response.status_code
    ).inc()
    return response


def get_store() -> ApprovalStore:
    return _store


@app.get("/metrics")
def metrics_endpoint():
    """Prometheus scrape target."""
    return metrics.metrics_response()


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


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
def resume_task(body: dict, authorization: str | None = Header(default=None)) -> dict:
    # Forward the caller's token: if the agent restarted, the graph state is
    # durable but the token is not, so the resume needs it again.
    token = (authorization or "").removeprefix("Bearer ").strip()
    resp = httpx.post(
        f"{_agent_url()}/resume",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
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
        tenant=delegation.tenant or "",
    )
    metrics.APPROVALS_PENDING.set(len(store.pending(delegation.tenant or "")))
    audit(
        "approval.created",
        approval_id=approval.id,
        spiffe_id=delegation.workload,
        sub=delegation.user,
        tenant=delegation.tenant or "",
        tool=tool,
    )
    return approval.as_dict()


@app.get("/approvals")
def list_approvals(
    status: str | None = None,
    delegation: Delegation = Depends(current_delegation),
    store: ApprovalStore = Depends(get_store),
) -> list[dict]:
    """The queue, scoped to the caller's tenant."""
    tenant = delegation.tenant or ""
    items = store.pending(tenant) if status == "pending" else store.all(tenant)
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
        tenant=body.get("tenant", ""),
    )
    return {"valid": valid}


@app.post("/approvals/{approval_id}/decision")
def decide_approval(
    approval_id: str,
    body: dict,
    delegation: Delegation = Depends(require_roles("manager")),
    store: ApprovalStore = Depends(get_store),
) -> dict:
    approval = store.decide(
        approval_id,
        approver=delegation.user,
        approved=bool(body.get("approved")),
        note=body.get("note"),
        tenant=delegation.tenant or "",
    )
    if approval is None:
        raise HTTPException(
            status_code=409,
            detail="approval not found, already decided, or self-approval is not allowed",
        )
    metrics.APPROVALS_PENDING.set(len(store.pending(delegation.tenant or "")))
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
    metrics.AUDIT_EVENTS.labels(str(record.get("event", "unknown"))).inc()
    return {"ok": True}


@app.get("/audit")
def get_audit(
    limit: int = 100,
    event: str | None = None,
    tool: str | None = None,
    sub: str | None = None,
) -> list[dict]:
    """The audit timeline (newest first), narrowable by event, tool, or user."""
    events = list(_audit)
    if event:
        events = [e for e in events if e.get("event") == event]
    if tool:
        events = [e for e in events if e.get("tool") == tool]
    if sub:
        events = [e for e in events if e.get("sub") == sub]
    return events[: max(1, min(limit, 500))]


# ---------------------------------------------------------------------------
# Privacy: who looked at personal data, why, and who approved it
# ---------------------------------------------------------------------------
PII_TOOL = "privacy.pii.read"
# Every event the tool server can emit about a tool call. A PII read leaves
# exactly one of these, so the trail is complete rather than a sample.
_TOOL_EVENTS = {"tool.allowed", "tool.denied", "tool.approval_required", "tool.error"}


@app.get("/privacy/access")
def privacy_access(
    delegation: Delegation = Depends(require_roles("manager")),
    store: ApprovalStore = Depends(get_store),
) -> dict:
    """The PII access trail and the approvals behind it, scoped to your tenant.

    An oversight view rather than another queue: personal-data reads are rare and
    always deliberate, so each one is shown next to the decision that permitted
    it. Reading PII needs the `privacy` role *and* manager approval, so a request
    and its approval are two records about the same act.

    Two limits worth stating plainly, because this is an oversight view:

    * the trail holds what *this* process received — audit is an in-memory deque,
      so with more than one API replica the view is partial and a restart clears
      it (see docs/privacy.md);
    * a request from a role with no PII access never reaches the tool server (the
      agent only offers permitted tools), so it leaves no `tool.denied` record
      here. What is below is every attempt the *tool server* saw.
    """
    tenant = delegation.tenant or ""
    access = [
        {
            "event": e.get("event", ""),
            "user": e.get("sub", ""),
            "tool": e.get("tool", ""),
            "decision": e.get("decision")
            or ("approval_required" if e.get("event") == "tool.approval_required" else ""),
            "reason": e.get("reason", ""),
            "policy_version": e.get("policy_version", ""),
            "at": e.get("ts", 0),
        }
        for e in _audit
        if e.get("tool") == PII_TOOL
        and e.get("event") in _TOOL_EVENTS
        and (e.get("tenant") or "") == tenant
    ]
    approvals = [a.as_dict() for a in store.all(tenant) if a.tool == PII_TOOL]
    return {"tool": PII_TOOL, "tenant": tenant, "access": access, "approvals": approvals}


# ---------------------------------------------------------------------------
# Web UI (served from the same origin when a build is present)
# ---------------------------------------------------------------------------
_WEB_DIR = Path(os.environ.get("WEB_DIR", "/workspace/app/web/dist"))
if _WEB_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_WEB_DIR / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_WEB_DIR / "index.html")
