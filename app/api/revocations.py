"""The revocation authority: which workload identities are cut off (S23).

Two backends behind one interface, like the approvals and audit stores:
in-memory for tests and a single process, Postgres when a database is configured
so the list survives a restart and every replica agrees. The api is the writer;
every other service reads it (via `app/common/revocation.py`).
"""
from __future__ import annotations

import threading
import time

from app.common.db import connect, database_configured, database_url

_SCHEMA = """
CREATE TABLE IF NOT EXISTS revoked_workloads (
    spiffe_id  text PRIMARY KEY,
    reason     text NOT NULL DEFAULT '',
    revoked_by text NOT NULL DEFAULT '',
    revoked_at double precision NOT NULL
);
"""


class RevocationStore:
    """In-memory backend (not durable)."""

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()

    def revoke(self, spiffe_id: str, *, reason: str, by: str) -> dict:
        record = {
            "spiffe_id": spiffe_id,
            "reason": reason,
            "revoked_by": by,
            "revoked_at": time.time(),
        }
        with self._lock:
            self._items[spiffe_id] = record
        return record

    def restore(self, spiffe_id: str) -> bool:
        with self._lock:
            return self._items.pop(spiffe_id, None) is not None

    def ids(self) -> set[str]:
        return set(self._items)

    def all(self) -> list[dict]:
        return sorted(self._items.values(), key=lambda r: r["spiffe_id"])


class PostgresRevocationStore:
    """Durable backend. Same semantics as :class:`RevocationStore`."""

    def __init__(self, url: str | None = None) -> None:
        self._url = url
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with connect(self._url) as conn:
            conn.execute(_SCHEMA)

    def _conn(self):
        conn = connect(self._url)
        conn.execute(_SCHEMA)
        return conn

    def revoke(self, spiffe_id: str, *, reason: str, by: str) -> dict:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO revoked_workloads (spiffe_id, reason, revoked_by, revoked_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (spiffe_id) DO UPDATE SET reason = EXCLUDED.reason, "
                "revoked_by = EXCLUDED.revoked_by, revoked_at = EXCLUDED.revoked_at",
                (spiffe_id, reason, by, now),
            )
        return {"spiffe_id": spiffe_id, "reason": reason, "revoked_by": by, "revoked_at": now}

    def restore(self, spiffe_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "DELETE FROM revoked_workloads WHERE spiffe_id = %s RETURNING spiffe_id",
                (spiffe_id,),
            ).fetchone()
        return row is not None

    def ids(self) -> set[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT spiffe_id FROM revoked_workloads").fetchall()
        return {r[0] for r in rows}

    def all(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT spiffe_id, reason, revoked_by, revoked_at FROM revoked_workloads "
                "ORDER BY spiffe_id"
            ).fetchall()
        return [
            {"spiffe_id": r[0], "reason": r[1], "revoked_by": r[2], "revoked_at": r[3]}
            for r in rows
        ]


def build_revocations() -> RevocationStore | PostgresRevocationStore:
    """Postgres when a database is configured, else in-memory."""
    if database_configured():
        return PostgresRevocationStore(database_url())
    return RevocationStore()
