"""Admin user management — gated on the `platform_admin` role.

Everything here is a privileged action, so every route depends on
:func:`require_admin` (server-side role check) and every mutation is audited.
Roles are a closed set: only the realm roles this platform knows about may be
granted, so an admin cannot mint an arbitrary role.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException

from agentnhi import audit
from agentnhi.tokens import Delegation
from app.api.authz import require_roles
from app.api.identity import admin_from_env

router = APIRouter(prefix="/admin")

# The roles an admin may grant. Anything else is rejected.
ASSIGNABLE_ROLES = ("support_rep", "manager", "privacy", "platform_admin")

require_admin = require_roles("platform_admin")


def _public(user: dict, roles: list[str]) -> dict:
    return {
        "id": user.get("id", ""),
        "username": user.get("username", ""),
        "email": user.get("email", ""),
        "enabled": user.get("enabled", True),
        "roles": roles,
    }


@router.get("/users")
def list_users(_: Delegation = Depends(require_admin)) -> list[dict]:
    admin = admin_from_env()
    return [_public(u, admin.user_role_names(u["id"])) for u in admin.list_users()]


@router.post("/users")
def create_user(body: dict, admin_dep: Delegation = Depends(require_admin)) -> dict:
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password are required")
    roles = [r for r in (body.get("roles") or []) if r in ASSIGNABLE_ROLES]

    admin = admin_from_env()
    try:
        user_id = admin.create_user(
            username=username,
            email=(body.get("email") or "").strip(),
            password=password,
            first_name=(body.get("firstName") or "").strip(),
            last_name=(body.get("lastName") or "").strip(),
            # The admin names the tenant; it defaults to the platform's.
            tenant=(body.get("tenant") or "").strip()
            or os.environ.get("DEFAULT_TENANT", "acme"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    for role in roles:
        admin.assign_role(user_id, role)
    audit(
        "user.created",
        user=username,
        user_id=user_id,
        roles=roles,
        actor=admin_dep.user,
    )
    return {"id": user_id, "username": username, "roles": roles}


@router.post("/users/{user_id}/roles")
def grant_role(
    user_id: str, body: dict, admin_dep: Delegation = Depends(require_admin)
) -> dict:
    role = (body.get("role") or "").strip()
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of: {', '.join(ASSIGNABLE_ROLES)}",
        )
    admin = admin_from_env()
    admin.assign_role(user_id, role)
    audit("user.role_granted", user_id=user_id, role=role, actor=admin_dep.user)
    return {"id": user_id, "roles": admin.user_role_names(user_id)}


@router.delete("/users/{user_id}/roles/{role}")
def revoke_role(
    user_id: str, role: str, admin_dep: Delegation = Depends(require_admin)
) -> dict:
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail="unknown role")
    admin = admin_from_env()
    admin.remove_role(user_id, role)
    audit("user.role_revoked", user_id=user_id, role=role, actor=admin_dep.user)
    return {"id": user_id, "roles": admin.user_role_names(user_id)}


@router.post("/users/{user_id}/enabled")
def set_enabled(
    user_id: str, body: dict, admin_dep: Delegation = Depends(require_admin)
) -> dict:
    enabled = bool(body.get("enabled"))
    admin_from_env().set_enabled(user_id, enabled)
    audit(
        "user.enabled" if enabled else "user.disabled",
        user_id=user_id,
        actor=admin_dep.user,
    )
    return {"id": user_id, "enabled": enabled}


@router.post("/users/{user_id}/password")
def reset_password(
    user_id: str, body: dict, admin_dep: Delegation = Depends(require_admin)
) -> dict:
    password = body.get("password") or ""
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")
    admin_from_env().reset_password(user_id, password)
    audit("user.password_reset", user_id=user_id, actor=admin_dep.user)
    return {"id": user_id, "reset": True}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str, admin_dep: Delegation = Depends(require_admin)
) -> dict:
    admin_from_env().delete_user(user_id)
    audit("user.deleted", user_id=user_id, actor=admin_dep.user)
    return {"id": user_id, "deleted": True}
