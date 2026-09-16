"""Ask the policy what a set of roles may call.

The role → tool matrix lives in `policy/authz.rego`. The agent reads it from
there rather than keeping its own copy, so the tools it *offers* can never
disagree with the tools policy will *allow*. This is a UX filter, not the
control: the enforcement stays at the tool server.

Every query that resolves *tools* names a tenant, because the matrix can differ
per tenant (S8) — the same role can have different power in `acme` and `globex`.
The tenant comes from the caller's verified identity, never from a request body.
"""
from __future__ import annotations

from typing import Any

import httpx


def _opa_post(
    opa_url: str, path: str, input_doc: dict, *, client: Any | None = None, timeout: float = 3.0
) -> Any:
    """Query a policy rule with an input document. Returns None on any error."""
    url = f"{opa_url.rstrip('/')}/v1/data/{path}"
    try:
        if client is not None:
            resp = client.post(url, json=input_doc, timeout=timeout)
        else:
            with httpx.Client() as http:
                resp = http.post(url, json=input_doc, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("result")
    except Exception:  # noqa: BLE001 - fail closed; the caller decides
        return None


def tools_for_roles(
    opa_url: str,
    roles: object,
    tenant: str | None,
    *,
    client: Any | None = None,
    timeout: float = 3.0,
) -> set[str]:
    """The tools the given roles may call **in this tenant**.

    The tenant is required, not an optimisation: policy resolves a tenant's
    override for a role, so an unscoped caller resolves no tools at all. Passing
    it is what keeps the offered set equal to the allowed set — without it the
    agent could offer a tool the tool server then denies, which is exactly the
    substitution the agent exists to prevent.

    Fails closed (empty set) on any error.
    """
    result = _opa_post(
        opa_url,
        "agentnhi/authz/tools_for_roles",
        {"input": {"roles": list(roles or ()), "tenant": tenant}},
        client=client,
        timeout=timeout,
    )
    return set(result or [])


def _opa_get(opa_url: str, path: str, *, client: Any | None = None, timeout: float = 3.0) -> Any:
    """Read a document from OPA. Returns None on any error (the caller decides)."""
    url = f"{opa_url.rstrip('/')}/v1/data/{path}"
    try:
        if client is not None:
            resp = client.get(url, timeout=timeout)
        else:
            with httpx.Client() as http:
                resp = http.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("result")
    except Exception:  # noqa: BLE001
        return None


def role_matrix(opa_url: str, tenant: str | None, **kwargs) -> dict:
    """The role → tools table **for one tenant**, straight from the policy.

    Resolved by policy (a tenant's entry replaces the default for that role, and
    an unmentioned role falls back), so the page shows what this tenant has rather
    than the global default.
    """
    return _opa_post(opa_url, "agentnhi/authz/role_matrix", {"input": {"tenant": tenant}}, **kwargs) or {}


def catalogue(opa_url: str, **kwargs) -> list:
    """The tool catalogue, injected into the bundle at build time."""
    return _opa_get(opa_url, "tools", **kwargs) or []


def refund_limits(opa_url: str, **kwargs) -> dict:
    """The refund tiers, so a page can describe them without hardcoding."""
    return {
        "auto": _opa_get(opa_url, "agentnhi/authz/auto_refund_limit", **kwargs),
        "approval": _opa_get(opa_url, "agentnhi/authz/approval_refund_limit", **kwargs),
    }
