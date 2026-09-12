"""Run the gateway with SPIFFE mTLS.

It fetches its own X.509-SVID from the Workload API (no server cert on disk),
uses it as the TLS server certificate, and **requires a client certificate**
verified against the SPIRE trust bundle. In other words, only a workload with a
SPIFFE identity issued by our SPIRE server can even open a connection.
"""
from __future__ import annotations

import os
import ssl
import time

import uvicorn

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


def main() -> None:
    socket = os.environ.get("SPIFFE_SOCKET", "unix:///run/spire/sockets/agent.sock")
    bundle = os.environ.get("SPIFFE_BUNDLE", "/run/spire/bundle/bundle.crt")
    cert_file, key_file = _svid_files(socket)

    uvicorn.run(
        "app.gateway.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8443")),
        ssl_certfile=cert_file,
        ssl_keyfile=key_file,
        ssl_ca_certs=bundle,
        ssl_cert_reqs=ssl.CERT_REQUIRED,  # mTLS: a client SVID is mandatory
        log_level="info",
    )


if __name__ == "__main__":
    main()
