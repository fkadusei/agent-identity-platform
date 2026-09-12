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
