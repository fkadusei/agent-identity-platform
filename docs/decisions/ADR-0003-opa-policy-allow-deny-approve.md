# ADR-0003: OPA policy with allow / deny / require-approval

- **Status:** Accepted
- **Date:** 2026-09-12

## Context

The agent must be stopped from doing harmful things — whether because the model
misjudges or because it is manipulated. Authorization must not live inside
application code (unreviewable, scattered) and must not depend on the model's
output.

## Decision

Centralize authorization in **OPA** (Open Policy Agent), written in **Rego**,
**deny-by-default**, with three outcomes:

- `allow` — proceed,
- `deny` — refuse,
- `require_approval` — pause for an authenticated human decision.

Policy is code: versioned, reviewed in PRs, unit-tested in CI, and changeable
without redeploying any workload.

## Consequences

- The LLM's reach is bounded by policy it cannot influence: prompt injection can
  change what the agent *asks for*, not what policy *permits*.
- Policy becomes a living artifact someone owns; changes are reviewable.
- High-risk actions require a human, whose identity and decision are audited.

## Alternatives considered

- **Authorization in application code** — rejected: unreviewable, inconsistent,
  and requires redeploys to change.
- **Model-side guardrails only** — rejected: the model is the untrusted input.
