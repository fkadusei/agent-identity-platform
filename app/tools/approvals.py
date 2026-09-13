"""Client for the approvals service.

When policy says `require_approval`, the tool server must not execute the action
unless a human has approved *this exact request*. The tool server does not trust
a caller-supplied flag; it asks the approvals service to confirm the approval
exists and matches.

The service is a peer inside the trust domain, so this is an HTTP call, not a
signature check (no key to manage).
"""
from __future__ import annotations

import httpx


class ApprovalsClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None, timeout: float = 5.0):
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout

    def verify(
        self, approval_id: str, *, tool: str, args: dict, user: str, agent: str, tenant: str
    ) -> bool:
        """Return True only if the approvals service confirms a matching approval."""
        payload = {
            "approval_id": approval_id,
            "tool": tool,
            "args": args,
            "user": user,
            "agent": agent,
            "tenant": tenant,
        }
        url = f"{self._base_url}/approvals/verify"
        try:
            if self._client is not None:
                resp = self._client.post(url, json=payload, timeout=self._timeout)
            else:
                with httpx.Client() as client:
                    resp = client.post(url, json=payload, timeout=self._timeout)
            resp.raise_for_status()
            return bool(resp.json().get("valid"))
        except Exception:  # noqa: BLE001 - fail closed
            return False
