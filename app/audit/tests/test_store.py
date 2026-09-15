"""The in-memory audit store: the semantics the durable one has to match."""
from __future__ import annotations

from app.audit.store import AuditStore


def _record(**over):
    record = {
        "ts": 1_700_000_000.0,
        "event": "tool.allowed",
        "sub": "priya",
        "tenant": "acme",
        "tool": "privacy.pii.read",
        "decision": "allow",
    }
    record.update(over)
    return record


def test_it_keeps_what_was_appended():
    store = AuditStore()
    store.append(_record())
    assert store.query() == [_record()]


def test_newest_first():
    store = AuditStore()
    store.append(_record(event="first"))
    store.append(_record(event="second"))
    assert [r["event"] for r in store.query()] == ["second", "first"]


def test_it_filters_by_event_tool_user_and_tenant():
    store = AuditStore()
    store.append(_record(event="tool.allowed", tool="privacy.pii.read", sub="priya"))
    store.append(_record(event="tool.denied", tool="refunds.issue", sub="alice", tenant="globex"))

    assert len(store.query(event="tool.denied")) == 1
    assert len(store.query(tool="privacy.pii.read")) == 1
    assert len(store.query(sub="alice")) == 1
    assert len(store.query(tenant="acme")) == 1
    assert store.query(tenant="globex")[0]["sub"] == "alice"


def test_tenant_none_means_do_not_filter():
    # The generic audit view wants everything; the privacy view wants one tenant.
    # "" (an unscoped identity) must not be confused with None (no filter).
    store = AuditStore()
    store.append(_record(tenant="acme"))
    store.append(_record(tenant="globex"))
    store.append(_record(tenant=""))
    assert len(store.query()) == 3
    assert len(store.query(tenant="")) == 1


def test_limit_takes_the_newest():
    store = AuditStore()
    for i in range(10):
        store.append(_record(ts=float(i)))
    assert [r["ts"] for r in store.query(limit=3)] == [9.0, 8.0, 7.0]


def test_it_is_bounded():
    store = AuditStore(maxlen=3)
    for i in range(5):
        store.append(_record(ts=float(i)))
    assert [r["ts"] for r in store.query()] == [4.0, 3.0, 2.0]


def test_it_records_events_that_are_not_tool_calls():
    # The trail is every event, not just tool decisions — a login matters too.
    store = AuditStore()
    store.append({"ts": 1.0, "event": "auth.login", "sub": "alice", "tenant": "acme"})
    assert store.query(event="auth.login")[0]["sub"] == "alice"
