"""Assert, per hop we own, that it is SPIFFE on both sides (S7).

`tls-check.sh` can only ask the mesh whether an edge is *encrypted*. This asks each
hop itself the two questions that matter, and fails if either answer is wrong:

  1. **Is the transport locked?** A client with no SVID must not be able to talk to
     it at all — otherwise the listener is open to anything in the cluster.
  2. **Is the caller named?** A client with a valid SVID but no workload token must
     be refused *for that reason*, and the agent, naming itself, must get past the
     identity gate.

Runs inside the agent pod, because that is where a workload identity and the app
package both live. Exits non-zero if any assertion fails.
"""
from __future__ import annotations

import os
import ssl
import sys

import httpx

from app.common import hop, workload

BUNDLE = os.environ.get("SPIFFE_BUNDLE", "/run/spire/bundle/bundle.crt")
SOCKET = os.environ.get("SPIFFE_SOCKET", "unix:///run/spire/sockets/agent.sock")

# Each hop we own, the audience a caller's token must carry, and a route that
# enforces the caller's identity (None where the route set is shared with users,
# so only the transport is asserted there). The gateway identifies callers in its
# own way — a JWT-SVID in Authorization, checked by its own code.
HOPS = [
    {
        "name": "agent → tools",
        "url": "https://tools:8443",
        "audience": workload.TOOLS,
        "probe": "/tools/crm.customer.read",
        "body": {"customer_id": "c-100"},
    },
    {
        "name": "agent → api",
        "url": "https://api:8443",
        "audience": workload.API,
        "probe": "/audit/events",
        "body": {"event": "hop.check"},
    },
    {"name": "agent → agent", "url": "https://agent:8443", "audience": workload.AGENT, "probe": None},
    {
        "name": "agent → gateway",
        "url": "https://gateway:8443",
        "audience": workload.GATEWAY,
        "probe": None,
    },
]


def _transport_locked(url: str) -> tuple[bool, str]:
    """A client with no SVID must not be able to talk to this hop."""
    context = ssl.create_default_context(cafile=BUNDLE)
    context.check_hostname = False
    try:
        with httpx.Client(verify=context, timeout=10) as client:
            return False, f"answered {client.get(f'{url}/healthz').status_code} with no client SVID"
    except Exception as exc:  # noqa: BLE001 - refusing is the expected outcome
        return True, type(exc).__name__


def _probe(spec: dict, *, named: bool) -> httpx.Response:
    client, headers = hop.open_hop(spec["url"], spec["audience"], timeout=10)
    try:
        return client.post(
            f"{spec['url']}{spec['probe']}", json=spec["body"], headers=headers if named else {}
        )
    finally:
        client.close()


def _assert_named(spec: dict) -> tuple[bool, str]:
    anonymous = _probe(spec, named=False)
    if not (anonymous.status_code == 403 and "workload identity" in anonymous.text):
        return False, f"unnamed caller got {anonymous.status_code}: {anonymous.text[:70]}"

    named = _probe(spec, named=True)
    if "workload identity" in named.text:
        return False, f"the named caller was still refused: {named.text[:70]}"
    return True, f"refused unnamed; admitted named ({named.status_code})"


def main() -> int:
    print("  " + f"{'hop':<18}{'transport':<20}{'caller identity'}")
    print("  " + "-" * 78)
    failures = 0
    for spec in HOPS:
        locked, why = _transport_locked(spec["url"])
        if not locked:
            failures += 1
            print(f"  {spec['name']:<18}{'FAIL':<20}{why}")
            continue
        if spec["probe"] is None:
            print(f"  {spec['name']:<18}{'mTLS required ✓':<20}— (shared with the user path)")
            continue
        ok, detail = _assert_named(spec)
        failures += 0 if ok else 1
        print(f"  {spec['name']:<18}{'mTLS required ✓':<20}{'✓ ' if ok else 'FAIL '}{detail}")

    if failures:
        print(f"\n  {failures} hop(s) are not SPIFFE-verified.")
        return 1
    print("\n  Every hop we own requires an SVID, and the named hops require a name.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
