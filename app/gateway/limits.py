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

_DAY = 86_400


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


def limiter_from_env() -> Limiter:
    return Limiter(
        requests_per_minute=int(os.environ.get("LLM_RATE_LIMIT_PER_MINUTE", "0") or 0),
        tokens_per_day=int(os.environ.get("LLM_TOKEN_BUDGET_PER_DAY", "0") or 0),
    )
