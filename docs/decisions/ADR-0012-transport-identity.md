# ADR-0012: Transport identity — SPIFFE for the workloads we own, the mesh for the rest

- **Status:** Accepted
- **Date:** 2026-09-19
- **Related:** ADR-0001 (identity over secrets), ADR-0009 (identity-authenticated
  gateway), ADR-0003 (policy)

## Context

The original design put SPIFFE on one hop — agent → gateway, where a static model
credential would otherwise live — and let the service mesh (Linkerd) carry every
other in-cluster hop, because a mesh "means the services need no TLS code"
(`docs/tls.md`). That left the platform with **two identity systems**: Linkerd's,
which authenticates pods to each other, and SPIFFE's, which is the platform's own
answer to *who is this workload*.

Two problems followed from that split:

- A hop "being encrypted" said nothing about **who** the peer was at the
  application layer, so the tool server — a policy enforcement point — learned the
  caller's workload identity only from a JWT, never from the transport.
- `/audit/events` took no credential at all. The mesh was the only thing in front
  of it, and the mesh authenticates but does not authorize by default, so any
  meshed pod could forge an audit event.

Meanwhile the mesh is not optional for everything else: **Keycloak, OPA, Postgres,
the observability stack and the sandbox** are third-party or simulated systems.
Giving them SPIFFE identities means hand-rolling certificate distribution and
rotation for products that do not speak SPIFFE, which is more moving parts than
the mesh already is — and the sandbox *should not* have an identity at all: it
stands in for a vendor's system, and a real vendor has none.

## Decision

**SPIFFE for every hop between workloads we own; the mesh for everything else.**

- **Our hops are SPIFFE, both directions.** `api`, `tools` and `agent` hold SVIDs
  alongside `gateway`; `app/common/server.py` serves their TLS listeners with
  `CERT_REQUIRED` against the SPIRE bundle, and `app/common/hop.py` presents the
  client's SVID. The restart-before-expiry rule (S15) applies to every one of them.
- **The caller is named.** The transport proves a valid SVID; it cannot prove
  *which* — our ASGI server does not expose the peer certificate — so the name
  travels in a **JWT-SVID** audienced to the callee and is verified against SPIRE's
  JWKS (`app/common/workload.py`). This is the check the gateway has made since
  Phase 2, now shared. It is enforced in the tools' **enforcement core** — one
  choke point covering both the HTTP and MCP transports — and on the api's machine
  routes, each with its own allow-list: the agent creates approvals, the tool
  server verifies them, and both may ingest audit.
- **Two listeners per service.** `api`, `tools` and `agent` also serve their
  existing port **without** mTLS, because a browser and a verification script
  cannot hold an SVID: they are a different trust domain. In production that
  listener is fronted by an ingress that terminates TLS (the chart's `ingress.tls`).
- **The mesh stays, and keeps its own hops.** Our pods remain mesh-injected, and
  the SPIFFE port **skips the proxy in both directions**
  (`config.linkerd.io/skip-inbound-ports` / `skip-outbound-ports: "8443"`). Without
  that skip the proxy would terminate the connection and prove *its* identity,
  hiding the peer's SVID from our server; with it, the mesh still encrypts every
  hop to Keycloak, OPA, Postgres, the sandbox and `/metrics`.
- **This ADR also records the mesh decision itself,** which no earlier ADR did:
  Linkerd is retained deliberately, for the components that cannot present a
  workload identity.

## Consequences

- **The two identity systems remain.** This ADR reduces where Linkerd's identity
  is load-bearing; it does not remove it. "One identity system" is not achieved,
  and the boundary is drawn where it can be defended rather than everywhere.
- **Identity at the application layer, not the transport.** Because the peer
  certificate is not exposed by our server, the *name* rides a bearer token with a
  five-minute life. It is audience-bound to one callee (so it cannot be replayed
  across hops) and never logged, but it is replayable within that window.
- **A route that forgets the check degrades.** The naming is enforced per route,
  so a new machine route must be given the dependency explicitly;
  `scripts/spiffe_hops_client.py` asserts the two that carry real weight today and
  fails if either stops requiring a name.
- **Plaintext exists, in one place.** The user/tooling listener is unencrypted
  in-cluster until the ingress terminates TLS for it (S7's second half, still
  open). It carries user tokens, so it is the hop to finish.
- **Operational surface grows**: two listeners, a skip rule on a port, and SPIRE
  registration entries for `api` and `tools` (which `setup.sh` creates and the
  chart README must name as a prerequisite).

## Alternatives considered

- **SPIFFE on every hop, mesh removed** — requires certificates for Keycloak, OPA
  and Postgres and a synthetic identity for the sandbox. More to get wrong than
  the mesh, for no gain on the hops that matter.
- **Uninject our pods and keep the mesh for third parties** — measured: a pod
  without a proxy loses encryption on *all* its outbound hops, not just the ones
  we were retiring, so Keycloak, OPA, Postgres, the sandbox and `/metrics` would
  all have gone plaintext. Rejected.
- **Keep the mesh everywhere, add SPIFFE nowhere** — status quo: an encryption
  story with no per-hop identity, and `/audit/events` open.
- **X.509 SAN assertions instead of a JWT-SVID** — the strongest form, but our
  ASGI server does not expose the peer certificate, and switching servers to one
  that does would leave the gateway's own, proven pattern inconsistent with it.
