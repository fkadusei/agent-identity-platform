"""Login and self-service enrollment.

Login is a real username/password grant against the `portal` client (server-side,
so the browser never holds a client secret). Enrollment creates the account with
**no roles** — a new user can do nothing until an admin grants a role. That is
the whole point: signing up is not the same as being authorized.

In production the browser would use the authorization-code + PKCE flow directly
against Keycloak; the server-side grant here keeps the local demo self-contained
(see docs/enrollment-and-roles.md).
"""
from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException

from agentnhi import Settings, TokenRejected, TokenVerifier, audit
from app.api.authz import get_verifier
from app.api.identity import admin_from_env
from app.common import metrics

router = APIRouter()

# The roles this platform knows about. Keycloak also emits built-ins
# (default-roles-…, offline_access, uma_authorization) that are not ours.
PLATFORM_ROLES = ("support_rep", "manager", "privacy", "platform_admin")

# The agent's SPIFFE ID, surfaced so the UI can show the real delegation chain.
AGENT_SPIFFE_ID = os.environ.get(
    "AGENT_SPIFFE_ID", "spiffe://acme.com/ns/agent-platform/sa/agent"
)


def signup_enabled() -> bool:
    return os.environ.get("SIGNUP_ENABLED", "1").lower() not in ("0", "false", "no", "")


def platform_roles(roles) -> list[str]:
    """Keep only the roles this platform acts on, sorted."""
    return sorted(r for r in roles if r in PLATFORM_ROLES)


@router.get("/auth/config")
def auth_config() -> dict:
    """Lets the UI show or hide the Enroll page, and name the acting agent."""
    return {
        "signup_enabled": signup_enabled(),
        "agent_id": AGENT_SPIFFE_ID,
    }


@router.post("/auth/login")
def login(body: dict, verifier: TokenVerifier = Depends(get_verifier)) -> dict:
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password are required")

    settings = Settings.from_env()
    resp = httpx.post(
        settings.token_endpoint,
        data={
            "grant_type": "password",
            "client_id": os.environ.get("PORTAL_CLIENT_ID", "portal"),
            "client_secret": os.environ.get("PORTAL_SECRET", ""),
            "username": username,
            "password": password,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        metrics.LOGINS.labels("failed").inc()
        audit("auth.login_failed", user=username)
        raise HTTPException(status_code=401, detail="invalid username or password")

    token = resp.json()["access_token"]
    # Verify what we just minted (signature + issuer + audience) rather than
    # trusting an unverified decode, then read the roles off the delegation.
    try:
        delegation = verifier.verify(token)
    except TokenRejected as exc:
        raise HTTPException(status_code=502, detail=f"login produced an unusable token: {exc}")

    roles = platform_roles(delegation.roles)
    # The tools this caller's roles permit, in their tenant — read from the
    # policy, so the UI has no second copy of the role -> tool matrix and cannot
    # show a tool the tenant's matrix does not grant (S8).
    from app.common.policy import tools_for_roles

    allowed = sorted(tools_for_roles(Settings.from_env().opa_url, delegation.roles, delegation.tenant))
    metrics.LOGINS.labels("ok").inc()
    audit("auth.login", user=username, roles=roles)
    return {
        "user": username,
        "roles": roles,
        # Surfaced so callers (the UI, scripts) never need to decode the token.
        "tenant": delegation.tenant,
        "tools": allowed,
        # When the token expires (from the verified claims), so the UI can drop a
        # stale session instead of showing errors after a refresh.
        "expires_at": delegation.claims.get("exp"),
        "access_token": token,
    }


@router.post("/enroll")
def enroll(body: dict) -> dict:
    if not signup_enabled():
        raise HTTPException(
            status_code=403, detail="self-service signup is disabled; ask an admin"
        )

    username = (body.get("username") or "").strip()
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    if not username or not email or not password:
        raise HTTPException(
            status_code=400, detail="username, email and password are required"
        )

    # NOTE: roles are deliberately NOT read from the request. A self-enrolled
    # account starts with no roles; an admin grants access afterward. The tenant
    # comes from configuration (a signup form cannot choose its own tenant).
    try:
        user_id = admin_from_env().create_user(
            username=username,
            email=email,
            password=password,
            first_name=(body.get("firstName") or "").strip(),
            last_name=(body.get("lastName") or "").strip(),
            tenant=os.environ.get("DEFAULT_TENANT", "acme"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            raise HTTPException(
                status_code=400, detail="password does not meet the realm policy (min 8)"
            )
        raise HTTPException(status_code=502, detail="enrollment failed")

    audit("user.enrolled", user=username, user_id=user_id, roles=[])
    return {"user": username, "id": user_id, "roles": []}
