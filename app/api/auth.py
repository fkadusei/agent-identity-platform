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
import jwt
from fastapi import APIRouter, HTTPException

from agentnhi import Settings, audit
from app.api.identity import admin_from_env

router = APIRouter()

# The roles this platform knows about. Keycloak also emits built-ins
# (default-roles-…, offline_access, uma_authorization) that are not ours.
PLATFORM_ROLES = ("support_rep", "manager", "privacy", "platform_admin")


def signup_enabled() -> bool:
    return os.environ.get("SIGNUP_ENABLED", "1").lower() not in ("0", "false", "no", "")


def _roles_from_token(token: str) -> list[str]:
    # We just minted this token, so we read its claims without re-verifying.
    claims = jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
    roles = (claims.get("realm_access") or {}).get("roles") or []
    return sorted(r for r in roles if r in PLATFORM_ROLES)


@router.get("/auth/config")
def auth_config() -> dict:
    """Lets the UI show or hide the Enroll page."""
    return {"signup_enabled": signup_enabled()}


@router.post("/auth/login")
def login(body: dict) -> dict:
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
        audit("auth.login_failed", user=username)
        raise HTTPException(status_code=401, detail="invalid username or password")

    token = resp.json()["access_token"]
    roles = _roles_from_token(token)
    audit("auth.login", user=username, roles=roles)
    return {"user": username, "roles": roles, "access_token": token}


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
    # account starts with no roles; an admin grants access afterward.
    try:
        user_id = admin_from_env().create_user(
            username=username,
            email=email,
            password=password,
            first_name=(body.get("firstName") or "").strip(),
            last_name=(body.get("lastName") or "").strip(),
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
