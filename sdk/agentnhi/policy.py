"""Authorization decisions via OPA.

Three outcomes, not two:

* ``allow``            — proceed.
* ``deny``             — refuse.
* ``require_approval`` — pause for an authenticated human decision.

**This client fails closed.** If OPA is unreachable, returns a malformed body,
or returns an unknown decision, the result is ``deny``. A policy system that
fails open is worse than no policy system at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

from .audit import audit
from .config import Settings


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason: str
    raw: dict | None = None
    policy_version: str | None = None

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


class PolicyClient:
    def __init__(self, settings: Settings, client: Any | None = None):
        self._settings = settings
        self._client = client

    def _post(self, payload: dict) -> Any:
        url = f"{self._settings.opa_url.rstrip('/')}/v1/data/{self._settings.policy_path}"
        timeout = self._settings.policy_timeout
        if self._client is not None:
            return self._client.post(url, json=payload, timeout=timeout)
        with httpx.Client() as client:
            return client.post(url, json=payload, timeout=timeout)

    def decide(
        self,
        *,
        agent: str,
        user: str,
        tool: str,
        context: dict | None = None,
    ) -> PolicyResult:
        """Return a :class:`PolicyResult`; never raises — denies on any error."""
        input_doc = {"agent": agent, "user": user, "tool": tool}
        if context:
            input_doc.update(context)
        try:
            resp = self._post({"input": input_doc})
            resp.raise_for_status()
            result = (resp.json() or {}).get("result") or {}
        except Exception as exc:  # noqa: BLE001 - fail closed on everything
            audit("policy.unavailable", reason=str(exc)[:200])
            return PolicyResult(Decision.DENY, "policy unavailable — denying (fail closed)")

        raw = result.get("decision")
        try:
            decision = Decision(raw)
        except ValueError:
            audit("policy.invalid", raw=str(raw)[:100])
            return PolicyResult(Decision.DENY, "policy returned no valid decision — denying")

        reason = result.get("reason") or f"policy decision: {decision.value}"
        return PolicyResult(decision, reason, result, result.get("policy_version"))
