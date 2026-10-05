"""Admission denylist for revoked workload identities (S23).

A revoked SPIFFE ID must be refused at every hop we own **immediately** — not
only when its SVID happens to expire. The set of revoked IDs lives in the api
(the authority). A service that *is* the api registers an in-process source;
every other service fetches the set over a hop we own and caches it briefly, so
staleness is seconds rather than the SVID's minutes-to-hour TTL.

Disabled unless a source is registered or `REVOCATION_URL` is set, so unit tests
and a local run never reach for the network.
"""
from __future__ import annotations

import os
import time
from typing import Callable

from app.common import hop

#: How long a fetched set may be reused. Small enough to be "immediate" for a
#: human, large enough not to call the api on every hop.
TTL = 5.0

_source: Callable[[], set[str]] | None = None
_cache: set[str] = set()
_cached_at = 0.0
#: True once a fetch has succeeded, so a later outage keeps the last known set
#: rather than failing open.
_available = False


def set_source(fn: Callable[[], set[str]]) -> None:
    """Register an in-process source — the api reading its own store."""
    global _source
    _source = fn


def reset() -> None:
    """Forget the source and the cache (tests)."""
    global _source, _cache, _cached_at, _available
    _source, _cache, _cached_at, _available = None, set(), 0.0, False


def _url() -> str:
    return os.environ.get("REVOCATION_URL", "").rstrip("/")


def fail_closed() -> bool:
    """Whether an *unavailable* denylist should refuse rather than allow.

    Opt-in (`REVOCATION_FAIL_CLOSED=1`): if the set can never be fetched, refuse
    every workload rather than let an unknown one through. Off by default — the
    denylist is defence in depth, and refusing all traffic on an api outage is a
    posture an operator should choose, not inherit.
    """
    return os.environ.get("REVOCATION_FAIL_CLOSED", "").strip().lower() in ("1", "true", "yes", "on")


def unavailable() -> bool:
    """Configured, not the authority, and no set has ever been fetched."""
    return _source is None and bool(_url()) and not _available


def _fetch() -> set[str]:
    # Imported lazily: `workload` imports this module to check admission, so a
    # top-level import here would be circular.
    from app.common import workload

    url = f"{_url()}/workloads/revoked"
    client, headers = hop.open_hop(url, workload.API, timeout=3.0)
    try:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return set(resp.json().get("revoked") or [])
    finally:
        client.close()


def revoked_ids() -> set[str]:
    """The revoked SPIFFE IDs — local for the api, fetched and cached otherwise.

    On a fetch failure the last known set is kept. With no source and no
    `REVOCATION_URL` the set is empty: the denylist is defence in depth, not the
    only control, so an unreachable api degrades to "no extra refusal" rather than
    blocking every hop.
    """
    global _cache, _cached_at, _available
    if _source is not None:
        return set(_source())
    if not _url():
        return set()
    now = time.time()
    if now - _cached_at < TTL:
        return _cache
    try:
        _cache = _fetch()
        _available = True
    except Exception:  # noqa: BLE001 - keep the last known set
        pass
    _cached_at = now
    return _cache


def is_revoked(spiffe_id: str) -> bool:
    # Fail closed only when opted in *and* we have no set at all: with a
    # last-known set we keep using it, and with the denylist disabled there is
    # nothing to fail.
    if fail_closed() and unavailable():
        return True
    return spiffe_id in revoked_ids()
