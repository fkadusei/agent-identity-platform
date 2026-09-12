"""Approval store for human-in-the-loop high-risk actions.

An approval is bound to the *exact* request: the tool, its arguments, the human
it is for, and the workload that requested it. The tool server verifies against
this, so a caller cannot approve one action and replay it for another.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field


def _normalize(args: dict) -> dict:
    """Canonical form for comparing arguments."""
    return {k: args[k] for k in sorted(args)}


@dataclass
class Approval:
    id: str
    tool: str
    args: dict
    user: str
    agent: str
    reason: str
    status: str = "pending"  # pending | approved | denied
    approver: str | None = None
    note: str | None = None
    created_at: float = field(default_factory=time.time)
    decided_at: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class ApprovalStore:
    def __init__(self) -> None:
        self._items: dict[str, Approval] = {}
        self._lock = threading.Lock()

    def create(self, *, tool: str, args: dict, user: str, agent: str, reason: str) -> Approval:
        approval = Approval(
            id=f"ap-{uuid.uuid4().hex[:12]}",
            tool=tool,
            args=_normalize(args),
            user=user,
            agent=agent,
            reason=reason,
        )
        with self._lock:
            self._items[approval.id] = approval
        return approval

    def get(self, approval_id: str) -> Approval | None:
        return self._items.get(approval_id)

    def pending(self) -> list[Approval]:
        return [a for a in self._items.values() if a.status == "pending"]

    def decide(
        self, approval_id: str, *, approver: str, approved: bool, note: str | None = None
    ) -> Approval | None:
        with self._lock:
            approval = self._items.get(approval_id)
            if approval is None or approval.status != "pending":
                return None
            if approver == approval.user:
                # Separation of duties: no self-approval.
                return None
            approval.status = "approved" if approved else "denied"
            approval.approver = approver
            approval.note = note
            approval.decided_at = time.time()
            return approval

    def verify(
        self, approval_id: str, *, tool: str, args: dict, user: str, agent: str
    ) -> bool:
        approval = self._items.get(approval_id)
        if approval is None or approval.status != "approved":
            return False
        return (
            approval.tool == tool
            and approval.args == _normalize(args)
            and approval.user == user
            and approval.agent == agent
        )
