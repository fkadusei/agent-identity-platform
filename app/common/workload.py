"""Proving *which* workload is calling (S7).

The transport proves the caller holds a valid SVID. Naming it is a second step,
because our ASGI server does not expose the peer certificate: the name travels in
a **JWT-SVID** — minted by SPIRE for the caller's own identity, audienced to the
service being called, and verified here against SPIRE's JWKS. The gateway has
identified its callers exactly this way since Phase 2 (`app/gateway/app.py`); this
is the same check in one place, so every hop we own can require it.

Configured by `WORKLOAD_AUDIENCE` — this service's own SPIFFE ID. A service that
holds an identity also requires its callers to name theirs; with it unset (a local
run, the test suite) the check is skipped rather than silently passing, and the
transport still requires a chain-verified SVID wherever it is served.
"""
from __future__ import annotations

import os

import jwt
from jwt import PyJWKClient

SPIRE_JWKS_URL = os.environ.get(
    "SPIRE_JWKS_URL",
    "http://spire-oidc-discovery.agent-platform.svc.cluster.local:11080/keys",
)

# The demo's workload identities. `acme.com` is a documentation value, like the
# one the policy file trusts; a real deployment reads these from its registration.
AGENT = "spiffe://acme.com/ns/agent-platform/sa/agent"
API = "spiffe://acme.com/ns/agent-platform/sa/api"
TOOLS = "spiffe://acme.com/ns/agent-platform/sa/tools"
GATEWAY = "spiffe://acme.com/ns/agent-platform/sa/gateway"

# What a service that says nothing else accepts: the agent, which is the one
# workload most of our machine hops come from.
DEFAULT_CALLER = AGENT

_jwks: PyJWKClient | None = None


class WorkloadRejected(Exception):
    """The caller did not prove an acceptable workload identity."""


def audience() -> str:
    """This service's own SPIFFE ID — what a caller's token must be audienced to."""
    return os.environ.get("WORKLOAD_AUDIENCE", "").strip()


def allowed_callers() -> set[str]:
    """The workloads that may call this service. Defaults to the agent alone."""
    raw = os.environ.get("ALLOWED_WORKLOADS", "").strip()
    if not raw:
        return {DEFAULT_CALLER}
    return {item.strip() for item in raw.split(",") if item.strip()}


def enabled() -> bool:
    """Whether this service requires callers to name themselves."""
    return bool(audience())


def _keys() -> PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(SPIRE_JWKS_URL)
    return _jwks


def verify(token: str | None, *, expected_audience: str | None = None) -> str:
    """Return the calling workload's SPIFFE ID, or raise `WorkloadRejected`.

    Fail closed on everything: a missing token, a bad signature, the wrong
    audience, or a token SPIRE never minted.
    """
    if not token:
        raise WorkloadRejected("missing workload token")
    token = token.removeprefix("Bearer ").strip()
    wanted = expected_audience or audience()
    if not wanted:
        raise WorkloadRejected("this service has no configured audience")
    try:
        key = _keys().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256", "ES256"], audience=wanted)
    except jwt.PyJWTError as exc:
        raise WorkloadRejected(str(exc)) from exc
    subject = claims.get("sub")
    if not subject:
        # A JWT-SVID always names its workload; without a subject there is nothing
        # to allow, so this is a rejection rather than a pass.
        raise WorkloadRejected("workload token has no subject")
    return subject


def check(token: str | None) -> str:
    """Verify the caller and enforce the allow-list. Returns its SPIFFE ID."""
    subject = verify(token)
    allowed = allowed_callers()
    if subject not in allowed:
        raise WorkloadRejected(f"{subject} may not call this service")
    return subject
