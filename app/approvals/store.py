"""Approval store for human-in-the-loop high-risk actions.

An approval is bound to the *exact* request: the tool, its arguments, the human
it is for, and the workload that requested it. The tool server verifies against
this, so a caller cannot approve one action and replay it for another.

Two backends, chosen by `build_store()`:

* :class:`ApprovalStore` — in-memory (tests, single-process demo).
* :class:`PostgresApprovalStore` — durable, so an approval survives a restart
  and any replica can serve it. Selected when `DATABASE_URL` is set.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field

from app.common.db import connect, database_configured, database_url

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id          text PRIMARY KEY,
    tool        text NOT NULL,
    args        jsonb NOT NULL,
    "user"      text NOT NULL,
    agent       text NOT NULL,
    reason      text NOT NULL,
    status      text NOT NULL,
    approver    text,
    note        text,
    created_at  double precision NOT NULL,
    decided_at  double precision
)
"""


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
    """In-memory backend (not durable)."""

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

    def all(self) -> list[Approval]:
        return list(self._items.values())

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


class PostgresApprovalStore:
    """Durable backend. Same semantics as :class:`ApprovalStore`.

    The self-approval and already-decided rules are enforced in the UPDATE's
    WHERE clause, so two concurrent approvers cannot both win.
    """

    def __init__(self, url: str | None = None) -> None:
        # url=None means "use the PG* environment" (see app/common/db.py).
        self._url = url
        with connect(self._url) as conn:
            conn.execute(_SCHEMA)

    @staticmethod
    def _row_to_approval(row) -> Approval:
        return Approval(
            id=row[0],
            tool=row[1],
            args=row[2],
            user=row[3],
            agent=row[4],
            reason=row[5],
            status=row[6],
            approver=row[7],
            note=row[8],
            created_at=row[9],
            decided_at=row[10],
        )

    def create(self, *, tool: str, args: dict, user: str, agent: str, reason: str) -> Approval:
        approval = Approval(
            id=f"ap-{uuid.uuid4().hex[:12]}",
            tool=tool,
            args=_normalize(args),
            user=user,
            agent=agent,
            reason=reason,
        )
        with connect(self._url) as conn:
            conn.execute(
                'INSERT INTO approvals (id, tool, args, "user", agent, reason, status, created_at) '
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    approval.id,
                    approval.tool,
                    json.dumps(approval.args),
                    approval.user,
                    approval.agent,
                    approval.reason,
                    approval.status,
                    approval.created_at,
                ),
            )
        return approval

    def get(self, approval_id: str) -> Approval | None:
        with connect(self._url) as conn:
            row = conn.execute(
                'SELECT id, tool, args, "user", agent, reason, status, approver, note, '
                "created_at, decided_at FROM approvals WHERE id = %s",
                (approval_id,),
            ).fetchone()
        return self._row_to_approval(row) if row else None

    def pending(self) -> list[Approval]:
        with connect(self._url) as conn:
            rows = conn.execute(
                'SELECT id, tool, args, "user", agent, reason, status, approver, note, '
                "created_at, decided_at FROM approvals WHERE status = 'pending' "
                "ORDER BY created_at"
            ).fetchall()
        return [self._row_to_approval(r) for r in rows]

    def all(self) -> list[Approval]:
        with connect(self._url) as conn:
            rows = conn.execute(
                'SELECT id, tool, args, "user", agent, reason, status, approver, note, '
                "created_at, decided_at FROM approvals ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_approval(r) for r in rows]

    def decide(
        self, approval_id: str, *, approver: str, approved: bool, note: str | None = None
    ) -> Approval | None:
        status = "approved" if approved else "denied"
        with connect(self._url) as conn:
            row = conn.execute(
                'UPDATE approvals SET status = %s, approver = %s, note = %s, decided_at = %s '
                "WHERE id = %s AND status = 'pending' AND \"user\" <> %s "
                'RETURNING id, tool, args, "user", agent, reason, status, approver, note, '
                "created_at, decided_at",
                (status, approver, note, time.time(), approval_id, approver),
            ).fetchone()
        return self._row_to_approval(row) if row else None

    def verify(
        self, approval_id: str, *, tool: str, args: dict, user: str, agent: str
    ) -> bool:
        approval = self.get(approval_id)
        if approval is None or approval.status != "approved":
            return False
        return (
            approval.tool == tool
            and approval.args == _normalize(args)
            and approval.user == user
            and approval.agent == agent
        )


def build_store() -> ApprovalStore | PostgresApprovalStore:
    """Postgres when a database is configured, else in-memory."""
    if database_configured():
        return PostgresApprovalStore(database_url())
    return ApprovalStore()
