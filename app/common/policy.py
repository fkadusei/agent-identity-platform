"""Ask the policy what a set of roles may call.

The role → tool matrix lives in `policy/authz.rego`. The agent reads it from
there rather than keeping its own copy, so the tools it *offers* can never
disagree with the tools policy will *allow*. This is a UX filter, not the
control: the enforcement stays at the tool server.
"""
from __future__ import annotations

from typing import Any

import httpx


def tools_for_roles(
    opa_url: str, roles: object, *, client: Any | None = None, timeout: float = 3.0
) -> set[str]:
    """The tools the given roles may call. Fails closed (empty) on any error."""
    payload = {"input": {"roles": list(roles or ())}}
    url = f"{opa_url.rstrip('/')}/v1/data/agentnhi/authz/tools_for_roles"
    try:
        if client is not None:
            resp = client.post(url, json=payload, timeout=timeout)
        else:
            with httpx.Client() as http:
                resp = http.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return set(resp.json().get("result") or [])
    except Exception:  # noqa: BLE001 - fail closed: no tools rather than all tools
        return set()
