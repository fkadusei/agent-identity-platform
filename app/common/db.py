"""Postgres access for state that must survive a restart.

Two ways to point at a database, both standard:

* `DATABASE_URL` — a single DSN (what the Helm chart takes from an operator).
* the libpq `PG*` variables (`PGHOST`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`) —
  what the kind manifests use, so the password stays a Secret reference and no
  credential appears in a URL.

When neither is set the services fall back to their in-memory implementations
(tests, single-process demos).
"""
from __future__ import annotations

import os


def database_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "").strip()
    return url or None


def database_configured() -> bool:
    return bool(database_url() or os.environ.get("PGHOST"))


def connect(dsn: str | None = None):
    """Open an autocommit connection.

    With no DSN, libpq builds it from the `PG*` environment. psycopg is imported
    lazily so it stays an optional dependency.
    """
    import psycopg

    if dsn:
        return psycopg.connect(dsn, autocommit=True)
    return psycopg.connect(autocommit=True)
