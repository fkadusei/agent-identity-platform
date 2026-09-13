"""The per-caller limiter: a burst guard and a daily cost guard."""
from __future__ import annotations

from app.gateway.limits import Limiter, estimate_tokens


def test_unlimited_by_default():
    limiter = Limiter()
    for _ in range(100):
        assert limiter.check("agent").allowed


def test_rate_limit_is_per_caller():
    limiter = Limiter(requests_per_minute=2)
    assert limiter.check("agent-a").allowed
    assert limiter.check("agent-a").allowed
    denied = limiter.check("agent-a")
    assert not denied.allowed
    assert "rate limit" in denied.reason
    assert denied.retry_after > 0
    # A different caller is unaffected.
    assert limiter.check("agent-b").allowed


def test_token_budget_is_per_caller():
    limiter = Limiter(tokens_per_day=100)
    assert limiter.check("agent-a").allowed
    limiter.charge("agent-a", 120)
    denied = limiter.check("agent-a")
    assert not denied.allowed
    assert "budget" in denied.reason
    # Another caller still has its own budget.
    assert limiter.check("agent-b").allowed


def test_charge_accumulates_and_reports_usage():
    limiter = Limiter(tokens_per_day=1000)
    limiter.charge("agent", 40)
    limiter.charge("agent", 60)
    assert limiter.used_today("agent") == 100


def test_charge_is_ignored_when_no_budget_is_set():
    limiter = Limiter(tokens_per_day=0)
    limiter.charge("agent", 10_000)
    assert limiter.used_today("agent") == 0


def test_estimate_tokens_is_positive():
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 400) == 100
