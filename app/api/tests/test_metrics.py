"""The Prometheus scrape endpoint exposes the platform's counters."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import app


def test_metrics_exposes_counters():
    client = TestClient(app)
    client.post("/audit/events", json={"event": "tool.denied", "tool": "refunds.issue"})
    text = client.get("/metrics").text
    assert "agent_platform_audit_events_total" in text
    assert 'event="tool.denied"' in text
    assert "agent_platform_http_requests_total" in text
    assert "agent_platform_approvals_pending" in text


def test_http_requests_are_labelled_by_route_template():
    client = TestClient(app)
    client.get("/healthz")
    text = client.get("/metrics").text
    # The route template, not the raw path — otherwise label cardinality explodes.
    assert 'route="/healthz"' in text


def test_backlog_gauge_is_the_platform_queue_not_this_replica():
    """The queue depth is read from the store at scrape time, across tenants.

    Two replicas each keep their own gauge, and only the one that handled a change
    sees it move — so a gauge written on request would leave the other replica
    reporting a stale queue, and an autoscaler reading `max()` across them would
    scale on that stale value (S6). It also must not be tenant-scoped: the api
    serves one queue.
    """
    from app.api.main import get_store
    from app.approvals.store import ApprovalStore
    from app.common import metrics

    store = ApprovalStore()
    app.dependency_overrides[get_store] = lambda: store
    try:
        for tenant, user in (("acme", "alice"), ("globex", "grace")):
            store.create(
                tool="refunds.issue", args={}, user=user, agent="spiffe://agent",
                reason="", tenant=tenant,
            )
        # A value left behind by a previous decision on this replica must not
        # survive the scrape.
        metrics.APPROVALS_PENDING.set(99)
        text = TestClient(app).get("/metrics").text
        assert "agent_platform_approvals_pending 2.0" in text
    finally:
        app.dependency_overrides.clear()
