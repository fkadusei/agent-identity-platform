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
