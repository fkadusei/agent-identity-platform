"""Serve a service with SPIFFE mTLS — one implementation for every service.

Three things every SPIFFE listener needs, kept in one place:

* the workload's X.509-SVID, fetched from the Workload API (never read from disk);
* a TLS context that **requires** a client SVID and verifies it against the SPIRE
  trust bundle, so only a workload SPIRE has issued can complete the handshake;
* an exit shortly before that certificate expires, so the process restarts with a
  fresh one. A TLS server that keeps serving an expired certificate fails every
  handshake, which looks like an outage rather than a rotated credential (S15).

The SVID is short-lived (1h in the demo) and the Workload API hands back SPIRE's
*cached* copy, which may already be partway through its life — so the restart is
derived from the certificate, not from a constant (S15).

**Identity, not just encryption.** The chain says the peer holds a valid SVID; it
does not say *which* workload. Hops that need that answer carry the caller's
SPIFFE ID in a JWT-SVID and check it — the same way the gateway already
identifies its callers (`app/gateway/app.py`). Our ASGI server does not expose the
peer certificate to the application, so the JWT-SVID is where the name comes from.

Called from a service's entrypoint with `SPIFFE_SOCKET` set; a local run without
it keeps that service's plain listener. See docs/tls.md.
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


def svid_files(socket: str) -> tuple[str, str]:
    """Fetch the X.509-SVID, retrying while SPIRE finishes attesting this pod."""
    last: Exception | None = None
    for _ in range(30):
        try:
            return write_mtls_files(socket)
        except Exception as exc:  # noqa: BLE001 - the Workload API may not be ready yet
            last = exc
            time.sleep(2)
    raise SystemExit(f"could not obtain an X.509-SVID: {last}")


def svid_expiry(cert_file: str) -> float:
    """The served SVID's `notAfter`, as an epoch timestamp.

    Read from the certificate rather than assumed from its TTL: the Workload API
    returns SPIRE's cached SVID, and SPIRE rotates at roughly half the lifetime,
    so a freshly started process can already be halfway through one.
    """
    from cryptography import x509

    cert = x509.load_pem_x509_certificate(Path(cert_file).read_bytes())
    not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(
        tzinfo=timezone.utc
    )
    return not_after.timestamp()


def restart_delay(remaining: float, margin: int) -> float:
    """Sleep until `margin` seconds before expiry, re-checking at least each minute."""
    return max(min(remaining - margin, 60.0), 0.0)


def restart_before_expiry(cert_file: str, margin: int, service: str) -> None:
    """Exit `margin` seconds before the certificate we are serving expires.

    The deadline comes from the certificate, not a constant. An interval that
    assumes a full lifetime serves an **expired** certificate for the difference,
    and every handshake fails until the process happens to restart (S15).

    Reloading a certificate into a live SSLContext did not hold up, so a restarted
    process — which fetches a new SVID at startup — is the mechanism; with two
    replicas behind a PodDisruptionBudget the restart is invisible.
    """
    expires_at = svid_expiry(cert_file)
    while True:
        remaining = expires_at - time.time()
        if remaining <= margin:
            audit(f"{service}.svid_restart", remaining_seconds=round(remaining))
            os._exit(0)
        time.sleep(restart_delay(remaining, margin))


def server_ssl_context(cert_file: str, key_file: str, bundle: str) -> ssl.SSLContext:
    """Present this workload's SVID as the server certificate; require the peer's.

    Hostname verification is off because a SPIFFE identity is a URI SAN, not a DNS
    name, so the default check could never pass. The chain is still verified
    against the SPIRE trust bundle either way.
    """
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    context.load_verify_locations(bundle)
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def run(
    module: str,
    port: int,
    *,
    service: str,
    edge_port: int | None = None,
    host: str = "0.0.0.0",
) -> None:
    """Run an ASGI app with SPIFFE mTLS on `port`.

    `service` names the audit events (`<service>.svid_loaded`, `<service>.svid_restart`),
    so an operator can see how much life the SVID has at startup — and that a
    restart was a rotation rather than a crash.

    `edge_port` serves the same app **without** mTLS, for callers that cannot hold
    an SVID: a browser, or a verification script standing in for a user. Those are
    a different trust domain from the workloads, and they keep their own listener
    rather than being admitted through this one (S7). In production that listener
    is fronted by an ingress that terminates TLS; `docs/tls.md` names the boundary.
    """
    socket = os.environ.get("SPIFFE_SOCKET", "unix:///run/spire/sockets/agent.sock")
    bundle = os.environ.get("SPIFFE_BUNDLE", "/run/spire/bundle/bundle.crt")
    margin = int(os.environ.get("SPIFFE_RESTART_MARGIN_SECONDS", "120"))

    if edge_port:
        edge = uvicorn.Server(
            uvicorn.Config(module, host=host, port=edge_port, log_level="info")
        )
        threading.Thread(target=edge.run, daemon=True).start()
        audit(f"{service}.edge_listener", port=edge_port)

    cert_file, key_file = svid_files(socket)
    context = server_ssl_context(cert_file, key_file, bundle)
    audit(
        f"{service}.svid_loaded",
        expires_in_seconds=round(svid_expiry(cert_file) - time.time()),
    )
    threading.Thread(
        target=restart_before_expiry,
        args=(cert_file, margin, service),
        daemon=True,
    ).start()

    uvicorn.run(
        module,
        host=host,
        port=port,
        ssl_context_factory=lambda _config, _default: context,
        log_level="info",
    )
