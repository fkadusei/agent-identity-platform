"""Run the gateway with SPIFFE mTLS.

It fetches its own X.509-SVID from the Workload API (no server cert on disk),
uses it as the TLS server certificate, and **requires a client certificate**
verified against the SPIRE trust bundle. Only a workload with a SPIFFE identity
issued by our SPIRE server can even open a connection.

The SVID is short-lived (1h in the demo) and the Workload API hands back
SPIRE's *cached* copy, which may already be partway through its life, so the
process exits shortly before the certificate it is serving expires and restarts
with a fresh one. A TLS server that keeps an expired certificate fails every
handshake, which looks like an outage rather than a rotated credential.
"""
from __future__ import annotations

import os
import ssl
import threading
import time
from datetime import timezone
from pathlib import Path

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


def _svid_expiry(cert_file: str) -> float:
    """The served SVID's `notAfter`, as an epoch timestamp.

    Read from the certificate rather than assumed from its TTL. The Workload API
    returns SPIRE's cached SVID, and SPIRE rotates at roughly half the lifetime,
    so a freshly started process can already be halfway through one.
    """
    from cryptography import x509

    cert = x509.load_pem_x509_certificate(Path(cert_file).read_bytes())
    not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(
        tzinfo=timezone.utc
    )
    return not_after.timestamp()


def _restart_delay(remaining: float, margin: int) -> float:
    """Sleep until `margin` seconds before expiry, re-checking at least each minute."""
    return max(min(remaining - margin, 60.0), 0.0)


def _restart_before_expiry(cert_file: str, margin: int) -> None:
    """Exit `margin` seconds before the certificate we are serving expires.

    The deadline comes from the certificate, not a constant. The old 3300s timer
    assumed a fresh 1h SVID at startup, but SPIRE hands back a cached copy — here
    one with 36 minutes left — so the gateway served an **expired** certificate
    for the difference and every agent->gateway handshake failed with
    CERTIFICATE_VERIFY_FAILED until the timer happened to fire (2026-09-16).

    Reloading the certificate into a live SSLContext did not hold up: after about
    a day, handshakes started failing with 'server disconnected'. A restarted
    process is unambiguous — it fetches a new SVID at startup — and with two
    replicas behind a PodDisruptionBudget the restart is invisible.
    """
    expires_at = _svid_expiry(cert_file)
    while True:
        remaining = expires_at - time.time()
        if remaining <= margin:
            audit("gateway.svid_restart", remaining_seconds=round(remaining))
            os._exit(0)
        time.sleep(_restart_delay(remaining, margin))


def main() -> None:
    socket = os.environ.get("SPIFFE_SOCKET", "unix:///run/spire/sockets/agent.sock")
    bundle = os.environ.get("SPIFFE_BUNDLE", "/run/spire/bundle/bundle.crt")
    margin = int(os.environ.get("GATEWAY_SVID_RESTART_MARGIN_SECONDS", "120"))
    cert_file, key_file = _svid_files(socket)

    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
    ctx.load_verify_locations(bundle)
    ctx.verify_mode = ssl.CERT_REQUIRED  # mTLS: a client SVID is mandatory

    # Say how much life the SVID has, so an expired certificate is visible at
    # startup rather than only in the handshake failures it causes.
    audit(
        "gateway.svid_loaded",
        expires_in_seconds=round(_svid_expiry(cert_file) - time.time()),
    )

    threading.Thread(
        target=_restart_before_expiry,
        args=(cert_file, margin),
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
