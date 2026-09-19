"""Run the gateway with SPIFFE mTLS.

The agent reaches the model only through this service, and both sides present
their SVIDs: the shared implementation is in `app/common/server.py`, so this file
is just the wiring. The gateway is the only component holding a provider
credential; the agent needs none (ADR-0009).
"""
from __future__ import annotations

import os

from app.common.server import run


def main() -> None:
    run(
        "app.gateway.app:app",
        int(os.environ.get("PORT", "8443")),
        service="gateway",
        # Its only listener is mTLS, so without this the kubelet can only ask
        # whether the socket is open — and a hung gateway answers that (S16).
        health_port=int(os.environ.get("HEALTH_PORT", "8081")),
    )


if __name__ == "__main__":
    main()
