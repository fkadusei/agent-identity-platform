# ADR-0014: Downstream on-behalf-of — a second token exchange

- **Status:** Accepted
- **Date:** 2026-10-05
- **Related:** ADR-0002 (Keycloak token exchange), ADR-0009 (provider-agnostic gateway), S28, Q28

## Context

The tool server calls the simulated systems (a vendor stand-in) **tenant-scoped**:
an `X-Tenant` header and no token (Q28). So the vendor could not tell *which person*
an action was for — the platform's "on behalf of the user" guarantee stopped at the
tool server. A real vendor routinely needs the user (its own audit, limits, or
per-user data), and the platform's whole premise is that delegation is real rather
than asserted.

## Decision

**Wire a second RFC 8693 token exchange, so the vendor receives a token that names
the user.**

- The tool server exchanges the user's token at Keycloak for one **audienced to the
  vendor**, authenticating with a **client secret** (the tool servers' `mcp-tools`
  client, given token exchange and an audience mapper) — the SDK's client-secret
  shape. The exchanging client must be *within the subject token's audience*, and
  the user's token is audienced to `mcp-tools`, so that is the client to use.
- It sends that token as `Authorization: Bearer`; the vendor verifies it (signature,
  issuer, `aud=sandbox`) and takes the tenant **and the user** from it.
- It **degrades safely**: with `TOOLS_CLIENT_ID`/`TOOLS_CLIENT_SECRET`/
  `SANDBOX_AUDIENCE` unset, the tool server skips the exchange and the call falls back
  to `X-Tenant`, exactly as before — the platform still runs without an IdP in the loop.

## Consequences

- The vendor has cryptographic proof of *which person* the action was for:
  `sub` = the human, `azp` = the tool server, `aud` = the vendor. Audience binding is
  preserved at every hop (T2): a token for the tool server is useless at the vendor.
- The tool servers' `mcp-tools` client gains token exchange and an audience mapper
  (its secret already existed); the vendor (the sandbox) becomes a token verifier, so
  it needs `KC_ISSUER` and its audience.
- The authorization decision still happens at the **tool server**; the OBO token is
  *proof*, not *permission*. The vendor must not treat a valid token as an allowance.
- One vendor and one audience are fixed in the realm; multi-vendor would be more
  clients/mappers (Q11's registry question again).

## Alternatives considered

- **Keep it tenant-scoped only.** Rejected: the vendor cannot answer "for which
  person", and the platform would be claiming delegation it does not carry.
- **Forward the user's token unchanged.** Rejected: it is audienced to the tool
  server, so forwarding it defeats audience binding — the exact replay T2 is about.
- **Opaque reference token + introspection at the vendor.** Deferred, not rejected:
  it removes token contents from the vendor but adds a live dependency; the JWT
  exchange is the shape the SDK already supports.
