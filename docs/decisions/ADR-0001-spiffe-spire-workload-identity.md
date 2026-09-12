# ADR-0001: Adopt SPIFFE/SPIRE for workload identity

- **Status:** Accepted
- **Date:** 2026-09-12
- **Related:** `enterprise-agent-nhi` (concepts demo)

## Context

The agent, the tools, and the services must prove *what they are* to each other.
The conventional answer — a static API key per service — has three failures:
it works from anywhere if leaked, it never expires on its own, and it cannot say
*which* workload acted. For an AI agent (which can be manipulated via prompt
injection), a long-lived shared credential turns a clever sentence into a breach.

## Decision

Give every workload a **SPIFFE identity** issued by **SPIRE**, verified by the
platform (Kubernetes namespace + service account), delivered over a node-local
socket, and short-lived. No workload carries a static credential to prove who
it is.

## Consequences

- Nothing to steal: no key file, no password; identity is bound to the workload
  and expires in minutes.
- We take on a dependency: SPIRE becomes critical path and must be highly
  available.
- Two small SPIRE builds are required (see ADR-0002) to interoperate with
  Keycloak.

## Alternatives considered

- **Static API keys / client secrets** — rejected: the exact failure mode we are
  eliminating.
- **Cloud-provider workload identity (IRSA/Workload Identity)** — good, but
  provider-specific; SPIFFE is portable across clouds and on-prem.
