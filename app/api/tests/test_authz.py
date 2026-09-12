"""Role-based authorization: the gate that turns roles into access."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from agentnhi import Delegation
from app.api.authz import require_roles

ALICE = Delegation(user="alice", workload="spiffe://agent", audience="mcp-tools", roles=("support_rep",))
ADMIN = Delegation(user="admin", workload="spiffe://agent", audience="mcp-tools", roles=("platform_admin",))
NONE = Delegation(user="nobody", workload="spiffe://agent", audience="mcp-tools", roles=())


def test_matching_role_is_allowed():
    dep = require_roles("manager", "platform_admin")
    assert dep(delegation=ADMIN) is ADMIN


def test_missing_role_is_forbidden():
    dep = require_roles("manager", "platform_admin")
    with pytest.raises(HTTPException) as exc:
        dep(delegation=ALICE)
    assert exc.value.status_code == 403


def test_no_roles_is_forbidden():
    dep = require_roles("support_rep")
    with pytest.raises(HTTPException) as exc:
        dep(delegation=NONE)
    assert exc.value.status_code == 403
