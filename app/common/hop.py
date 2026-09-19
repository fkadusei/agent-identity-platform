"""Calling a hop we own: our SVID on the transport, our name in a header (S7).

Both halves of a SPIFFE hop live here, so a caller cannot get one without the
other: the client presents this workload's X.509-SVID, and the request carries a
JWT-SVID audienced to the callee. The audience binds the token to one service, so
a token captured on one hop cannot be replayed on the next.

A plain `http://` URL is a local run or a test double and is left alone — the same
"enabled only where it means something" rule the rest of the SPIFFE wiring follows.
"""
from __future__ import annotations

import os
import time

import httpx
from agentnhi.identity import fetch_jwt_svid, mtls_client_context

#: JWT-SVIDs are short-lived (5 minutes by default); re-fetch well inside that.
TOKEN_TTL_SECONDS = 300

_tokens: dict[str, tuple[float, str]] = {}


def workload_token(audience: str) -> str:
    """This workload's JWT-SVID for `audience`, cached briefly."""
    now = time.time()
    cached = _tokens.get(audience)
    if cached and now - cached[0] < TOKEN_TTL_SECONDS:
        return cached[1]
    socket = os.environ.get("SPIFFE_SOCKET", "unix:///run/spire/sockets/agent.sock")
    token = fetch_jwt_svid(socket, audience)
    _tokens[audience] = (now, token)
    return token


def open_hop(url: str, audience: str, *, timeout: float = 30.0) -> tuple[httpx.Client, dict]:
    """A client and the extra headers for calling `url`.

    Over https: mTLS with our SVID as the client certificate, plus the header that
    names us. The caller is responsible for closing the client.
    """
    if not url.startswith("https://"):
        return httpx.Client(timeout=timeout), {}
    context = mtls_client_context(
        os.environ.get("SPIFFE_SOCKET", "unix:///run/spire/sockets/agent.sock"),
        ca_cert_path=os.environ.get("SPIFFE_BUNDLE", "/run/spire/bundle/bundle.crt"),
        verify_hostname=False,
    )
    return httpx.Client(verify=context, timeout=timeout), {
        "X-Workload-Token": f"Bearer {workload_token(audience)}"
    }


def reset() -> None:
    """Forget cached tokens (tests)."""
    _tokens.clear()
