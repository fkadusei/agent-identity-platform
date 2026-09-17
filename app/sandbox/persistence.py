"""Where the sandbox keeps the simulated systems' data between restarts.

The sandbox stands in for a vendor's own CRM / orders / payments / ticketing
system, so it owns this storage — the platform's database is not the vendor's, and
a real vendor would have its own. For the demo, a JSON snapshot on a volume is
enough to stop a pod restart resetting every refund and draft (S9), which used to
make the demo confusing to give twice.

Three deliberate properties:

* **Off unless configured.** `SANDBOX_STATE_PATH` selects the file; unset means the
  old in-memory behaviour, so tests and a local run are unaffected.
* **Never fatal.** Persistence must not be able to take the sandbox down: a
  snapshot that cannot be read is treated as empty, and a write that fails is
  reported and ignored. A failure is visible as `sandbox.state_error` in the logs
  rather than silent — a volume that is not mounted should say so.
* **Atomic.** Writes go to a temporary file and are renamed over the target, so a
  crash mid-write cannot leave a half-written snapshot to be read at startup.
"""
from __future__ import annotations

import json
import os
import tempfile

from agentnhi import audit


class SandboxState:
    """A JSON snapshot of the simulated systems' runtime state."""

    def __init__(self, path: str | None) -> None:
        self._path = path or None

    @property
    def enabled(self) -> bool:
        return self._path is not None

    def load(self) -> dict:
        """The last snapshot, or empty lists. Never raises."""
        if not self._path or not os.path.exists(self._path):
            return {"refunds": [], "drafts": []}
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:  # noqa: BLE001 - a bad snapshot must not stop us
            audit("sandbox.state_error", op="load", path=self._path, reason=str(exc)[:200])
            return {"refunds": [], "drafts": []}
        return {
            "refunds": list(data.get("refunds") or []),
            "drafts": list(data.get("drafts") or []),
        }

    def save(self, *, refunds: list[dict], drafts: list[dict]) -> None:
        """Write the snapshot atomically. Never raises."""
        if not self._path:
            return
        payload = {"refunds": list(refunds), "drafts": list(drafts)}
        try:
            directory = os.path.dirname(self._path) or "."
            os.makedirs(directory, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=directory, prefix=".sandbox-state-")
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream)
            os.replace(temporary, self._path)
        except Exception as exc:  # noqa: BLE001 - never take the sandbox down
            audit("sandbox.state_error", op="save", path=self._path, reason=str(exc)[:200])
