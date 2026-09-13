"""Prometheus metrics for the platform, exposed at `/metrics` on the API.

Where possible the counters are derived from the **audit stream**: every service
forwards its audit events to the API, so a single ingest point yields policy
decisions, approvals, logins and admin actions without instrumenting each
service twice. That keeps "what the audit log says" and "what the dashboard
shows" from drifting apart.
"""
from __future__ import annotations

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

# Auth (emitted by app/api/auth.py)
LOGINS = Counter("agent_platform_logins_total", "User logins by result", ["result"])

# Everything that goes through the audit stream (policy decisions, approvals,
# user administration, tool calls ...).
AUDIT_EVENTS = Counter(
    "agent_platform_audit_events_total",
    "Audit events ingested, by event type",
    ["event"],
)

# Approval backlog (emitted wherever the store changes).
APPROVALS_PENDING = Gauge(
    "agent_platform_approvals_pending", "Approvals awaiting a decision"
)

# HTTP, labelled by the route template (not the raw path — that would explode
# the label cardinality on /admin/users/{id}).
HTTP_REQUESTS = Counter(
    "agent_platform_http_requests_total", "HTTP requests", ["method", "route", "status"]
)


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
