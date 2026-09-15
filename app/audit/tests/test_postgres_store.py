"""The Postgres audit store: the same semantics, durable and shared.

Runs against a real database when TEST_DATABASE_URL (or PG*) is set (CI provides
one), and is skipped otherwise so the suite stays runnable without Postgres.
"""
from __future__ import annotations

import os

import pytest

from app.audit.store import PostgresAuditStore
from app.common.db import connect

URL = os.environ.get("TEST_DATABASE_URL")
CONFIGURED = bool(URL or os.environ.get("PGHOST"))

pytestmark = pytest.mark.skipif(not CONFIGURED, reason="no TEST_DATABASE_URL / PG* configured")


def _record(**over):
    record = {
        "ts": 1_700_000_000.0,
        "event": "tool.allowed",
        "sub": "priya",
        "tenant": "acme",
        "tool": "privacy.pii.read",
        "decision": "allow",
        "reason": "requires privacy approval: PII access",
    }
    record.update(over)
    return record


@pytest.fixture
def store():
    store = PostgresAuditStore(URL)
    with connect(URL) as conn:
        conn.execute("DELETE FROM audit_events")
    return store


def test_it_round_trips_the_whole_record(store):
    # Not just the indexed columns: the trail has to be readable.
    store.append(_record())
    (got,) = store.query()
    assert got == _record()


def test_two_stores_share_one_trail(store):
    # This is the reason the store exists. Two API replicas used to hold
    # different subsets of the same events; now either one sees all of them.
    other_replica = PostgresAuditStore(URL)
    store.append(_record(event="tool.allowed"))
    other_replica.append(_record(event="tool.denied"))
    assert {r["event"] for r in store.query()} == {"tool.allowed", "tool.denied"}
    assert {r["event"] for r in other_replica.query()} == {"tool.allowed", "tool.denied"}


def test_newest_first(store):
    store.append(_record(event="first"))
    store.append(_record(event="second"))
    assert [r["event"] for r in store.query()] == ["second", "first"]


def test_it_filters_by_tenant(store):
    store.append(_record(tenant="acme"))
    store.append(_record(tenant="globex"))
    assert len(store.query(tenant="acme")) == 1
    assert len(store.query(tenant="globex")) == 1
    assert len(store.query()) == 2


def test_it_filters_by_tool_and_user(store):
    store.append(_record(tool="privacy.pii.read", sub="priya"))
    store.append(_record(tool="refunds.issue", sub="alice"))
    assert store.query(tool="refunds.issue")[0]["sub"] == "alice"
    assert store.query(sub="priya")[0]["tool"] == "privacy.pii.read"


def test_limit_takes_the_newest(store):
    for i in range(5):
        store.append(_record(ts=float(i)))
    assert [r["ts"] for r in store.query(limit=2)] == [4.0, 3.0]
