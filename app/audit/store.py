"""The audit trail: one record per event, queryable, and durable.

Audit is the *evidence* layer — "which workload did what, on whose behalf, and why
was it allowed" — so it has to survive a restart and give the same answer whichever
replica you ask. An in-memory deque in the API process did neither: with two
replicas each pod held a different subset of events, and a rollout wiped it. For
an oversight view (who read personal data, and who approved it) that is a
correctness problem, not a cosmetic one.

Two backends, chosen by :func:`build_audit_store`:

* :class:`AuditStore` — in-memory and bounded (tests, a single-process demo);
* :class:`PostgresAuditStore` — durable and shared, selected when `DATABASE_URL`
  is set.

Records arrive already redacted: `agentnhi.audit` strips secrets and personal data
before a record leaves the service that emitted it, so nothing here has to decide
what is safe to store.
"""
from __future__ import annotations

import json
import threading
from collections import deque

from app.common.db import connect, database_configured, database_url

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id       bigserial PRIMARY KEY,
    ts       double precision NOT NULL,
    event    text NOT NULL,
    "sub"    text NOT NULL DEFAULT '',
    tenant   text NOT NULL DEFAULT '',
    tool     text,
    decision text,
    record   jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_events_id_idx ON audit_events (id DESC);
CREATE INDEX IF NOT EXISTS audit_events_tool_idx ON audit_events (tool);
CREATE INDEX IF NOT EXISTS audit_events_tenant_idx ON audit_events (tenant);
"""

# The in-memory ceiling. Postgres has no equivalent — durability is the point.
MAX_IN_MEMORY = 500


def _columns(record: dict) -> tuple[float, str, str, str, Any, Any]:
    """The indexed fields, pulled out of the record.

    Only these are queryable; the record itself is kept whole, because the point
    of the trail is to be able to read what happened.
    """
    return (
        float(record.get("ts") or 0.0),
        str(record.get("event") or ""),
        str(record.get("sub") or ""),
        str(record.get("tenant") or ""),
        record.get("tool"),
        record.get("decision"),
    )


def _matches(
    record: dict,
    *,
    event: str | None = None,
    tool: str | None = None,
    sub: str | None = None,
    tenant: str | None = None,
) -> bool:
    if event and record.get("event") != event:
        return False
    if tool and record.get("tool") != tool:
        return False
    if sub and record.get("sub") != sub:
        return False
    # `tenant=None` means "do not filter" — distinct from a tenant of "".
    if tenant is not None and (record.get("tenant") or "") != tenant:
        return False
    return True


class AuditStore:
    """In-memory backend (not durable, not shared between processes)."""

    def __init__(self, maxlen: int = MAX_IN_MEMORY) -> None:
        self._records: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def append(self, record: dict) -> None:
        with self._lock:
            self._records.appendleft(record)

    def query(
        self,
        *,
        limit: int = 100,
        event: str | None = None,
        tool: str | None = None,
        sub: str | None = None,
        tenant: str | None = None,
    ) -> list[dict]:
        with self._lock:
            records = list(self._records)
        found = [
            r for r in records if _matches(r, event=event, tool=tool, sub=sub, tenant=tenant)
        ]
        return found[:limit]


class PostgresAuditStore:
    """Durable, shared backend. Same semantics as :class:`AuditStore`."""

    def __init__(self, url: str | None = None) -> None:
        # url=None means "use the PG* environment" (see app/common/db.py).
        self._url = url
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with connect(self._url) as conn:
            conn.execute(_SCHEMA)

    def _conn(self):
        """A connection with the schema ensured.

        `CREATE TABLE IF NOT EXISTS` is a cheap no-op when the table is there, so
        the store survives a database reset under it.
        """
        conn = connect(self._url)
        conn.execute(_SCHEMA)
        return conn

    def append(self, record: dict) -> None:
        ts, event, sub, tenant, tool, decision = _columns(record)
        with self._conn() as conn:
            conn.execute(
                'INSERT INTO audit_events (ts, event, "sub", tenant, tool, decision, record) '
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (ts, event, sub, tenant, tool, decision, json.dumps(record, default=str)),
            )

    def query(
        self,
        *,
        limit: int = 100,
        event: str | None = None,
        tool: str | None = None,
        sub: str | None = None,
        tenant: str | None = None,
    ) -> list[dict]:
        # One static statement rather than SQL assembled from interpolated
        # fragments: `(%s IS NULL OR col = %s)` is the filter, and every value is
        # a bound parameter. `tenant=None` means "no filter"; "" is a real tenant
        # (an unscoped identity), which is why the check is IS NULL and not
        # truthiness.
        with self._conn() as conn:
            # The ::text casts are load-bearing: Postgres cannot infer the type
            # of a bare NULL parameter, so `%s IS NULL` alone is a type error.
            rows = conn.execute(
                "SELECT record FROM audit_events "
                "WHERE (%(event)s::text IS NULL OR event = %(event)s::text) "
                '  AND (%(tool)s::text IS NULL OR tool = %(tool)s::text) '
                '  AND (%(sub)s::text IS NULL OR "sub" = %(sub)s::text) '
                "  AND (%(tenant)s::text IS NULL OR tenant = %(tenant)s::text) "
                "ORDER BY id DESC LIMIT %(limit)s",
                {"event": event, "tool": tool, "sub": sub, "tenant": tenant, "limit": limit},
            ).fetchall()
        return [row[0] for row in rows]


def build_audit_store() -> AuditStore | PostgresAuditStore:
    """Postgres when a database is configured, else in-memory.

    The in-memory default is deliberate: `./start.sh` runs the whole platform
    without a database, and a demo should not require one to show an audit trail.
    """
    if database_configured():
        return PostgresAuditStore(database_url())
    return AuditStore()
