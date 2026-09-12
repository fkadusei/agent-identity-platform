"""Forward audit records to a central collector, in addition to stdout.

Each service emits one JSON line per event (the SDK's default sink). For the UI's
audit timeline we also POST a copy to the API's `/audit/events` endpoint. The
forwarding is best-effort and never blocks or fails a request: if the collector
is down, the event is simply dropped (stdout remains the source of truth).
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading

import httpx

# NOTE: import the function directly. `import agentnhi.audit as _audit` would
# bind the *function* `agentnhi.audit` re-exported by the package __init__,
# not the module, and fail with "'function' object has no attribute 'set_sink'".
from agentnhi.audit import set_sink as _set_sink

_queue: "queue.Queue[dict]" = queue.Queue(maxsize=1000)
_started = False


def _worker(url: str) -> None:
    while True:
        record = _queue.get()
        try:
            httpx.post(f"{url}/audit/events", json=record, timeout=2)
        except Exception:  # noqa: BLE001 - best effort
            pass


def enable_forwarding() -> None:
    """Route audit records to stdout AND to the collector at $AUDIT_URL."""
    global _started
    url = os.environ.get("AUDIT_URL")
    if not url or _started:
        return
    _started = True
    threading.Thread(target=_worker, args=(url.rstrip("/"),), daemon=True).start()

    def sink(record: dict) -> None:
        json.dump(record, sys.stdout, default=str)
        sys.stdout.write("\n")
        sys.stdout.flush()
        try:
            _queue.put_nowait(record)
        except queue.Full:
            pass

    _set_sink(sink)
