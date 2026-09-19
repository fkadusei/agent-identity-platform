"""Forward audit records to a central collector, in addition to stdout.

Each service emits one JSON line per event (the SDK's default sink). For the UI's
audit timeline we also POST a copy to the API's `/audit/events` endpoint. The
forwarding is best-effort and never blocks or fails a request: if the collector
is down, the event is simply dropped (stdout remains the source of truth).

Since S7 that endpoint requires the sender to name itself, so this uses the same
hop helper as any other call we make: the workload's SVID on the transport, a
JWT-SVID audienced to the api in the header. Before that, `/audit/events` took no
credential at all.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading

from agentnhi.audit import set_sink as _set_sink

from app.common import hop, workload

_queue: "queue.Queue[dict]" = queue.Queue(maxsize=1000)
_started = False


def _post(url: str, record: dict) -> None:
    client, headers = hop.open_hop(url, workload.API, timeout=2)
    try:
        client.post(f"{url}/audit/events", json=record, headers=headers)
    finally:
        client.close()


def _worker(url: str) -> None:
    while True:
        record = _queue.get()
        try:
            _post(url, record)
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
