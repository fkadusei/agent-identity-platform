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
    tenant      text NOT NULL DEFAULT '',
    status      text NOT NULL,
    approver    text,
    note        text,
    created_at  double precision NOT NULL,
    decided_at  double precision
);
-- Migration for a database created before approvals were tenant-scoped.
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS tenant text NOT NULL DEFAULT '';
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
    # The tenant the request belongs to. Approvals are scoped to it, so one
    # tenant's approvers never see or decide another's.
    tenant: str = ""
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

    def create(
        self, *, tool: str, args: dict, user: str, agent: str, reason: str, tenant: str
    ) -> Approval:
        approval = Approval(
            id=f"ap-{uuid.uuid4().hex[:12]}",
            tool=tool,
            args=_normalize(args),
            user=user,
            agent=agent,
            reason=reason,
            tenant=tenant,
        )
        with self._lock:
            self._items[approval.id] = approval
        return approval

    def get(self, approval_id: str, tenant: str) -> Approval | None:
        approval = self._items.get(approval_id)
        # Invisible across tenants, the same as it is in Postgres.
        return approval if approval is not None and approval.tenant == tenant else None

    def pending(self, tenant: str) -> list[Approval]:
        return [a for a in self._items.values() if a.status == "pending" and a.tenant == tenant]

    def all(self, tenant: str) -> list[Approval]:
        return [a for a in self._items.values() if a.tenant == tenant]

    def decide(
        self,
        approval_id: str,
        *,
        approver: str,
        approved: bool,
        note: str | None = None,
        tenant: str,
    ) -> Approval | None:
        with self._lock:
            approval = self._items.get(approval_id)
            # Only the requester's own tenant may decide it.
            if approval is None or approval.status != "pending" or approval.tenant != tenant:
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
        self, approval_id: str, *, tool: str, args: dict, user: str, agent: str, tenant: str
    ) -> bool:
        approval = self._items.get(approval_id)
        if approval is None or approval.status != "approved" or approval.tenant != tenant:
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
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with connect(self._url) as conn:
            conn.execute(_SCHEMA)

    def _conn(self):
        """A connection with the schema ensured.

        The DDL is `CREATE TABLE IF NOT EXISTS` (a cheap no-op when the table is
        there), so the store survives a database that was reset under it — e.g. a
        Postgres restart on ephemeral storage.
        """
        conn = connect(self._url)
        conn.execute(_SCHEMA)
        return conn

    @staticmethod
    def _row_to_approval(row) -> Approval:
        return Approval(
            id=row[0],
            tool=row[1],
            args=row[2],
            user=row[3],
            agent=row[4],
            reason=row[5],
            tenant=row[6],
            status=row[7],
            approver=row[8],
            note=row[9],
            created_at=row[10],
            decided_at=row[11],
        )

    def create(
        self, *, tool: str, args: dict, user: str, agent: str, reason: str, tenant: str
    ) -> Approval:
        approval = Approval(
            id=f"ap-{uuid.uuid4().hex[:12]}",
            tool=tool,
            args=_normalize(args),
            user=user,
            agent=agent,
            reason=reason,
            tenant=tenant,
        )
        with self._conn() as conn:
            conn.execute(
                'INSERT INTO approvals (id, tool, args, "user", agent, reason, tenant, status, '
                "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    approval.id,
                    approval.tool,
                    json.dumps(approval.args),
                    approval.user,
                    approval.agent,
                    approval.reason,
                    approval.tenant,
                    approval.status,
                    approval.created_at,
                ),
            )
        return approval

    def get(self, approval_id: str, tenant: str) -> Approval | None:
        with self._conn() as conn:
            row = conn.execute(
                'SELECT id, tool, args, "user", agent, reason, tenant, status, approver, note, '
                "created_at, decided_at FROM approvals WHERE id = %s AND tenant = %s",
                (approval_id, tenant),
            ).fetchone()
        return self._row_to_approval(row) if row else None

    def pending(self, tenant: str) -> list[Approval]:
        with self._conn() as conn:
            rows = conn.execute(
                'SELECT id, tool, args, "user", agent, reason, tenant, status, approver, note, '
                "created_at, decided_at FROM approvals "
                "WHERE status = 'pending' AND tenant = %s ORDER BY created_at",
                (tenant,),
            ).fetchall()
        return [self._row_to_approval(r) for r in rows]

    def all(self, tenant: str) -> list[Approval]:
        with self._conn() as conn:
            rows = conn.execute(
                'SELECT id, tool, args, "user", agent, reason, tenant, status, approver, note, '
                "created_at, decided_at FROM approvals WHERE tenant = %s "
                "ORDER BY created_at DESC",
                (tenant,),
            ).fetchall()
        return [self._row_to_approval(r) for r in rows]

    def decide(
        self,
        approval_id: str,
        *,
        approver: str,
        approved: bool,
        note: str | None = None,
        tenant: str,
    ) -> Approval | None:
        status = "approved" if approved else "denied"
        with self._conn() as conn:
            row = conn.execute(
                'UPDATE approvals SET status = %s, approver = %s, note = %s, decided_at = %s '
                "WHERE id = %s AND status = 'pending' AND tenant = %s AND \"user\" <> %s "
                'RETURNING id, tool, args, "user", agent, reason, tenant, status, approver, note, '
                "created_at, decided_at",
                (status, approver, note, time.time(), approval_id, tenant, approver),
            ).fetchone()
        return self._row_to_approval(row) if row else None

    def verify(
        self, approval_id: str, *, tool: str, args: dict, user: str, agent: str, tenant: str
    ) -> bool:
        approval = self.get(approval_id, tenant)
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
