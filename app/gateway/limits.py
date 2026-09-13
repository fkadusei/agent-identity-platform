"""Per-caller rate and cost limits for the model gateway.

The gateway is the only egress to a model, so it is the right place to cap what
an agent can spend. Limits are keyed on the caller's **SPIFFE ID**, proven by the
JWT-SVID it presents — never on anything the caller can set freely, or the limit
would be trivially bypassed.

Two limits:

* **rate** — requests per minute (a burst guard);
* **budget** — estimated tokens per day (a cost guard).

Both default to 0, meaning unlimited.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass

from app.common.db import connect, database_configured, database_url

_DAY = 86_400

# Durable counters. The rate window is one row per (caller, minute); the budget
# is one row per (caller, day). Both are upserted atomically, so replicas share
# them and a restart does not reset them.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_rate (
    caller   text   NOT NULL,
    minute   bigint NOT NULL,
    requests integer NOT NULL DEFAULT 0,
    PRIMARY KEY (caller, minute)
);
CREATE TABLE IF NOT EXISTS llm_daily (
    caller text   NOT NULL,
    day    bigint NOT NULL,
    tokens bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (caller, day)
);
"""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""
    retry_after: int = 0


class Limiter:
    """In-memory, per-caller. Single-replica; see docs/llm-gateway.md."""

    def __init__(self, *, requests_per_minute: int = 0, tokens_per_day: int = 0) -> None:
        self._rpm = requests_per_minute
        self._tpd = tokens_per_day
        self._requests: dict[str, deque[float]] = {}
        self._tokens: dict[str, tuple[int, int]] = {}  # caller -> (day_index, used)
        self._lock = threading.Lock()

    def check(self, caller: str) -> Decision:
        """Allow (and count) a request, or refuse with a reason."""
        now = time.time()
        with self._lock:
            if self._rpm:
                window = self._requests.setdefault(caller, deque())
                while window and window[0] < now - 60:
                    window.popleft()
                if len(window) >= self._rpm:
                    return Decision(
                        False,
                        f"rate limit reached ({self._rpm} requests/minute)",
                        retry_after=max(1, int(60 - (now - window[0])) + 1),
                    )
                window.append(now)

            if self._tpd:
                day = int(now // _DAY)
                used = self._tokens.get(caller, (day, 0))
                if used[0] != day:
                    used = (day, 0)
                if used[1] >= self._tpd:
                    return Decision(
                        False,
                        f"daily token budget reached ({self._tpd} tokens)",
                        retry_after=3600,
                    )
            return Decision(True)

    def charge(self, caller: str, tokens: int) -> None:
        """Record tokens spent (estimated) against the caller's daily budget."""
        if not self._tpd or tokens <= 0:
            return
        with self._lock:
            day = int(time.time() // _DAY)
            used = self._tokens.get(caller, (day, 0))
            self._tokens[caller] = (day, used[1] + tokens if used[0] == day else tokens)

    def used_today(self, caller: str) -> int:
        with self._lock:
            day = int(time.time() // _DAY)
            used = self._tokens.get(caller, (day, 0))
            return used[1] if used[0] == day else 0


def estimate_tokens(text: str) -> int:
    """A cheap, provider-agnostic estimate (~4 characters per token)."""
    return max(1, len(text) // 4)


class PostgresLimiter:
    """Durable limiter: the same policy, in Postgres.

    Selected when a database is configured. Because the counters are shared, the
    limits hold across gateway replicas and survive a restart — which is what
    makes them usable in production rather than just in the demo.
    """

    def __init__(
        self, url: str | None = None, *, requests_per_minute: int = 0, tokens_per_day: int = 0
    ) -> None:
        self._url = url
        self._rpm = requests_per_minute
        self._tpd = tokens_per_day
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with connect(self._url) as conn:
            conn.execute(_SCHEMA)

    def _conn(self):
        """A connection with the schema ensured (survives a reset database)."""
        conn = connect(self._url)
        conn.execute(_SCHEMA)
        return conn

    def check(self, caller: str) -> Decision:
        now = time.time()
        if self._rpm:
            minute = int(now // 60)
            # One atomic upsert: increment and read back, so concurrent callers
            # cannot both see a stale count.
            with self._conn() as conn:
                row = conn.execute(
                    "INSERT INTO llm_rate (caller, minute, requests) VALUES (%s, %s, 1) "
                    "ON CONFLICT (caller, minute) DO UPDATE "
                    "SET requests = llm_rate.requests + 1 RETURNING requests",
                    (caller, minute),
                ).fetchone()
            if row[0] > self._rpm:
                return Decision(
                    False,
                    f"rate limit reached ({self._rpm} requests/minute)",
                    retry_after=max(1, int(60 - (now % 60)) + 1),
                )

        if self._tpd:
            day = int(now // _DAY)
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT tokens FROM llm_daily WHERE caller = %s AND day = %s",
                    (caller, day),
                ).fetchone()
            if row and row[0] >= self._tpd:
                return Decision(
                    False, f"daily token budget reached ({self._tpd} tokens)", retry_after=3600
                )
        return Decision(True)

    def charge(self, caller: str, tokens: int) -> None:
        if not self._tpd or tokens <= 0:
            return
        day = int(time.time() // _DAY)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO llm_daily (caller, day, tokens) VALUES (%s, %s, %s) "
                "ON CONFLICT (caller, day) DO UPDATE SET tokens = llm_daily.tokens + %s",
                (caller, day, tokens, tokens),
            )
            # Opportunistic cleanup: the rate window is a minute, the budget a day.
            conn.execute("DELETE FROM llm_rate WHERE minute < %s", (int(time.time() // 60),))
            conn.execute("DELETE FROM llm_daily WHERE day < %s", (day - 1,))

    def used_today(self, caller: str) -> int:
        day = int(time.time() // _DAY)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT tokens FROM llm_daily WHERE caller = %s AND day = %s", (caller, day)
            ).fetchone()
        return row[0] if row else 0


def limiter_from_env():
    """Postgres when a database is configured (durable), else in-memory."""
    kwargs = dict(
        requests_per_minute=int(os.environ.get("LLM_RATE_LIMIT_PER_MINUTE", "0") or 0),
        tokens_per_day=int(os.environ.get("LLM_TOKEN_BUDGET_PER_DAY", "0") or 0),
    )
    if database_configured():
        return PostgresLimiter(database_url(), **kwargs)
    return Limiter(**kwargs)
