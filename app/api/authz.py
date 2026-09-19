"""Authentication and role-based authorization for the API.

Every caller presents a token (aud=mcp-tools). :func:`current_delegation`
verifies it and extracts who the human is; :func:`require_roles` is the gate
that turns roles into authorization. Role checks live here, on the server —
the UI hides what a user cannot do, but that is convenience, never the control.
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from agentnhi import Settings, TokenRejected, TokenVerifier
from agentnhi.tokens import Delegation
from app.common import workload

_verifier: TokenVerifier | None = None


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


def require_roles(*roles: str):
    """Dependency factory: the caller must hold at least one of ``roles``."""

    def dependency(delegation: Delegation = Depends(current_delegation)) -> Delegation:
        if not set(roles) & set(delegation.roles):
            raise HTTPException(
                status_code=403,
                detail=f"requires one of these roles: {', '.join(roles)}",
            )
        return delegation

    return dependency


def require_workload(*allowed: str):
    """Dependency factory: a **machine** caller must be one of these workloads.

    For the routes a workload calls rather than a browser (creating an approval,
    verifying one, ingesting audit). The name is the caller's JWT-SVID, verified
    against SPIRE's JWKS — the same check the gateway makes, shared via
    `app/common/workload.py`.

    Skipped when this service has no `WORKLOAD_AUDIENCE` (a local run, the test
    suite), where the transport still requires a chain-verified SVID. In the
    manifests it is always set, so the hop is always named.
    """

    def dependency(x_workload_token: str | None = Header(default=None)) -> str:
        if not workload.enabled():
            return ""
        try:
            caller = workload.verify(x_workload_token)
        except workload.WorkloadRejected as exc:
            raise HTTPException(status_code=403, detail=f"workload identity rejected: {exc}")
        if caller not in allowed:
            raise HTTPException(status_code=403, detail=f"{caller} may not call this route")
        return caller

    return dependency
