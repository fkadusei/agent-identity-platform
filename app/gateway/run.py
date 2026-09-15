"""Run the gateway with SPIFFE mTLS.

It fetches its own X.509-SVID from the Workload API (no server cert on disk),
uses it as the TLS server certificate, and **requires a client certificate**
verified against the SPIRE trust bundle. Only a workload with a SPIFFE identity
issued by our SPIRE server can even open a connection.

The SVID is short-lived (1h in the demo), so it is **renewed in the process**: a
TLS server that keeps an expired certificate fails every handshake, which looks
like an outage rather than a rotated credential.
"""
from __future__ import annotations

import os
import ssl
import threading
import time

import uvicorn

from agentnhi import audit
from agentnhi.identity import write_mtls_files


def _svid_files(socket: str) -> tuple[str, str]:
    """Fetch the X.509-SVID, retrying while SPIRE finishes attesting this pod."""
    last: Exception | None = None
    for _ in range(30):
        try:
            return write_mtls_files(socket)
        except Exception as exc:  # noqa: BLE001 - the Workload API may not be ready yet
            last = exc
            time.sleep(2)
    raise SystemExit(f"could not obtain an X.509-SVID: {last}")


def _restart_before_expiry(every: int) -> None:
    """Exit before the SVID expires, so the pod restarts with a fresh one.

    Reloading the certificate into a live SSLContext did not hold up: after about
    a day, handshakes started failing with 'server disconnected'. A restarted
    process is unambiguous — it fetches a new SVID at startup — and with two
    replicas behind a PodDisruptionBudget the restart is invisible.

    The interval must stay comfortably below the SVID lifetime (1h in the demo).
    """
    while True:
        time.sleep(every)
        audit("gateway.svid_restart", after_seconds=every)
        os._exit(0)


def main() -> None:
    socket = os.environ.get("SPIFFE_SOCKET", "unix:///run/spire/sockets/agent.sock")
    bundle = os.environ.get("SPIFFE_BUNDLE", "/run/spire/bundle/bundle.crt")
    cert_file, key_file = _svid_files(socket)

    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
    ctx.load_verify_locations(bundle)
    ctx.verify_mode = ssl.CERT_REQUIRED  # mTLS: a client SVID is mandatory

    threading.Thread(
        target=_restart_before_expiry,
        args=(int(os.environ.get("GATEWAY_SVID_RESTART_SECONDS", "3300")),),
        daemon=True,
    ).start()

    uvicorn.run(
        "app.gateway.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8443")),
        ssl_context_factory=lambda _config, _default: ctx,
        log_level="info",
    )


if __name__ == "__main__":
    main()
