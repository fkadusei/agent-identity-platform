# ADR-0002: Keycloak Standard Token Exchange V2 for delegation

- **Status:** Accepted
- **Date:** 2026-09-12
- **Related:** ADR-0001

## Context

The agent must act **on behalf of a user** without holding that user's
credentials, and every token must be narrowly scoped. This is OAuth 2.0 Token
Exchange (RFC 8693). Two hard integration facts were established while building
the concepts demo:

1. Keycloak requires a `jti` claim on `private_key_jwt` client assertions, and
   SPIRE does not mint one.
2. SPIRE caches JWT-SVIDs, so a repeated exchange reuses the same `jti`, which
   Keycloak correctly rejects ("token reuse detected").

## Decision

Use **Keycloak Standard Token Exchange V2** (26.2+; no fine-grained admin
permissions — authorization is expressed through audience mappers). The agent
authenticates as a client whose **client_id is its SPIFFE ID**, presenting its
JWT-SVID as a client assertion. Two small SPIRE builds bridge the gaps:

- a **`jti` CredentialComposer plugin** on the SPIRE server, and
- a **SPIRE agent with the JWT-SVID cache disabled**.

Delegation is recorded as `sub` (the human) + `azp` (the acting workload), and
tokens are audience-bound.

## Consequences

- Delegation is explicit, auditable, and standards-based; no shared secret for
  the agent.
- We carry two custom SPIRE builds. Both disappear once an authorization server
  natively supports SPIFFE client authentication
  (`draft-ietf-oauth-spiffe-client-auth`).

## Alternatives considered

- **Static client secret for the agent** — rejected: reintroduces the credential
  we are removing.
- **Keycloak X.509 client auth** — rejected: it matches on the certificate
  subject DN, but SPIRE puts the SPIFFE ID in the SAN, so workloads cannot be
  distinguished.
