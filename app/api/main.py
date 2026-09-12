"""The platform API: human approvals and agent tasks.

Endpoints:
    POST /approvals                    create a pending approval (agent's token)
    GET  /approvals?status=pending     the approval queue
    POST /approvals/{id}/decision      approve/deny (approver's token)
    POST /approvals/verify             used by tool servers (in trust domain)
    POST /tasks                        start an agent run
    POST /tasks/{thread_id}/resume     resume a paused run with a decision

Every caller is authenticated with an exchanged token; the approval is bound to
the token's user and workload.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException

from agentnhi import Settings, TokenRejected, TokenVerifier, audit
from agentnhi.tokens import Delegation
from app.approvals import ApprovalStore

app = FastAPI(title="agent-identity-platform API")
_store = ApprovalStore()
_verifier: TokenVerifier | None = None


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
def verify_approval(
    body: dict,
    store: ApprovalStore = Depends(get_store),
) -> dict:
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
