"""The durable limiter: the same policy, in Postgres.

Runs against a real database when TEST_DATABASE_URL (or PG*) is set, and is
skipped otherwise so the suite stays runnable without Postgres.
"""
from __future__ import annotations

import os
import uuid

import pytest

from app.gateway.limits import PostgresLimiter

URL = os.environ.get("TEST_DATABASE_URL")
CONFIGURED = bool(URL or os.environ.get("PGHOST"))

pytestmark = pytest.mark.skipif(
    not CONFIGURED, reason="no database configured (set TEST_DATABASE_URL or PG*)"
)


@pytest.fixture
def caller() -> str:
    return f"spiffe://test/{uuid.uuid4().hex[:8]}"


def _limiter(**kwargs) -> PostgresLimiter:
    return PostgresLimiter(URL, **kwargs)


def test_rate_limit_is_per_caller(caller):
    limiter = _limiter(requests_per_minute=2)
    assert limiter.check(caller).allowed
    assert limiter.check(caller).allowed
    denied = limiter.check(caller)
    assert not denied.allowed
    assert "rate limit" in denied.reason
    assert limiter.check(f"{caller}/other").allowed


def test_token_budget_is_per_caller(caller):
    limiter = _limiter(tokens_per_day=100)
    assert limiter.check(caller).allowed
    limiter.charge(caller, 120)
    denied = limiter.check(caller)
    assert not denied.allowed
    assert "budget" in denied.reason


def test_counters_survive_a_restart(caller):
    # A second instance stands in for a restarted gateway: the counter is shared.
    _limiter(tokens_per_day=1000).charge(caller, 250)
    assert _limiter(tokens_per_day=1000).used_today(caller) == 250


def test_used_today_accumulates(caller):
    limiter = _limiter(tokens_per_day=1000)
    limiter.charge(caller, 40)
    limiter.charge(caller, 60)
    assert limiter.used_today(caller) == 100
