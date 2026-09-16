"""The agent's run checkpointer must survive Postgres dropping its connections.

The bug this guards (S12): the checkpointer held a single Postgres connection.
When Postgres restarted, that socket died and every run then failed in 0.1s with
`psycopg.OperationalError: server closed the connection unexpectedly` — forever,
until the agent process was restarted. The failure also looked like a dozen other
errors from the outside.

Runs against a real database when TEST_DATABASE_URL (or PG*) is set (CI provides
one), and is skipped otherwise so the suite stays runnable without Postgres.
"""
from __future__ import annotations

import os
import uuid

import pytest

from app.common.db import connect

URL = os.environ.get("TEST_DATABASE_URL")
CONFIGURED = bool(URL or os.environ.get("PGHOST"))

pytestmark = pytest.mark.skipif(not CONFIGURED, reason="no TEST_DATABASE_URL / PG* configured")

APPLICATION_NAME = "agent-checkpointer"


@pytest.fixture
def checkpointer(monkeypatch):
    """A fresh checkpointer per test, built against the test database."""
    import app.agent.service as service

    if URL:
        monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setattr(service, "_checkpointer", None)
    monkeypatch.setattr(service, "_checkpointer_ready", False)
    # `raising=False`: the single-connection design had no pool to reset, and this
    # test is meant to fail on the *behaviour*, not on a missing attribute.
    monkeypatch.setattr(service, "_pool", None, raising=False)

    saver = service.get_checkpointer()
    assert saver is not None
    yield saver
    pool = getattr(service, "_pool", None)
    if pool is not None:
        pool.close()


def _close_the_sockets_the_checkpointer_holds(saver) -> int:
    """A stand-in for a Postgres restart: close the checkpointer's sockets.

    The old design held exactly one connection, so killing that pid *is* the
    restart. A pool holds several; those are found by `application_name`, so
    nothing another test or service is holding gets touched.
    """
    from psycopg import Connection

    if isinstance(saver.conn, Connection):
        pids = [saver.conn.info.backend_pid]
    else:
        with connect(URL) as conn:
            pids = [
                pid
                for (pid,) in conn.execute(
                    "SELECT pid FROM pg_stat_activity"
                    " WHERE datname = current_database() AND application_name = %s",
                    (APPLICATION_NAME,),
                ).fetchall()
            ]
    if not pids:
        return 0
    with connect(URL) as conn:
        closed = conn.execute(
            "SELECT count(pg_terminate_backend(pid)) FROM unnest(%s::int[]) AS t(pid)",
            (pids,),
        ).fetchone()
    return closed[0] or 0


def test_the_checkpointer_is_backed_by_a_pool(checkpointer):
    from psycopg_pool import ConnectionPool

    # The whole point of S12: not one connection, which can never be replaced.
    assert isinstance(checkpointer.conn, ConnectionPool)


def test_it_survives_the_database_closing_its_connections(checkpointer):
    config = {"configurable": {"thread_id": f"t-{uuid.uuid4().hex[:8]}"}}
    assert checkpointer.get_tuple(config) is None  # the pool works to begin with

    assert _close_the_sockets_the_checkpointer_holds(checkpointer) >= 1

    # With a single connection this raised OperationalError — and kept raising on
    # every later request. The pool detects the dead connection at checkout,
    # discards it, and reconnects, so the next operation simply works.
    checkpointer.setup()
    assert checkpointer.get_tuple(config) is None


def test_it_recreates_its_schema_if_the_database_came_back_empty(checkpointer):
    """A restored or replaced database can come back without the checkpoint tables.

    On the demo's old `emptyDir` Postgres a pod restart did exactly that; S3 has
    since given it a volume, so the schema is dropped here explicitly instead.
    """
    import app.agent.service as service

    with connect(URL) as conn:
        conn.execute(
            "DROP TABLE IF EXISTS checkpoint_writes, checkpoint_blobs,"
            " checkpoints, checkpoint_migrations CASCADE"
        )

    # get_checkpointer() re-ensures the schema, the same defence the approvals and
    # audit stores apply per operation. Without it the pool would reconnect fine
    # and the run would then die on "relation checkpoints does not exist".
    saver = service.get_checkpointer()
    config = {"configurable": {"thread_id": f"t-{uuid.uuid4().hex[:8]}"}}
    assert saver.get_tuple(config) is None
