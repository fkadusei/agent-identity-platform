"""The role → tool matrix, read from the policy.

The page renders exactly what the policy enforces — there is no second copy to
drift. The matrix is the **caller's own tenant's** (S8): the same role name can
carry different tools in a different tenant, so showing the global default would
be a lie about your own powers. Any signed-in caller may read it (it is policy,
not personal data).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from agentnhi import Settings
from agentnhi.tokens import Delegation
from app.api.authz import current_delegation
from app.common.policy import catalogue, refund_limits, role_matrix

router = APIRouter()


@router.get("/roles")
def roles(delegation: Delegation = Depends(current_delegation)) -> dict:
    opa = Settings.from_env().opa_url
    matrix = role_matrix(opa, delegation.tenant)
    return {
        "roles": {role: sorted(tools) for role, tools in sorted(matrix.items())},
        "tools": sorted(catalogue(opa)),
        "limits": refund_limits(opa),
        "you": {"roles": list(delegation.roles), "tenant": delegation.tenant},
    }
