# Real-World Adoption Guide

> **Status: DRAFT (Phase 0).** This is the guide leaders and architects read
> first. It is finalized in Phase 3 once the platform runs end to end.

## Who this is for

Anyone deciding whether — and how — to give AI agents real access to real
systems without handing them long-lived API keys.

## The problem, in one paragraph

Most agents today carry a static API key. That key works from anywhere if
leaked, never expires on its own, and cannot tell you *which* agent did what.
Because an agent contains a model that can be talked into things, a leaked key
plus a clever sentence becomes a breach. The fix is not a better key; it is to
stop using keys and give the agent an identity instead.

## What changes: demo → production

| Concern | Concepts demo | This platform | Production target |
|---|---|---|---|
| Workload identity | SPIFFE/SPIRE | same, hardened | HA SPIRE, persistent storage |
| Delegation | Keycloak token exchange V2 | same | same |
| Authorization | OPA allow/deny | + require-approval | policy lifecycle, staged rollout |
| Tools | mock HTTP API | real MCP servers | real sandbox → real systems |
| Human oversight | none | approval interrupts | approval queues, SLAs |
| Secrets | local Ollama | + LLM gateway | secret manager, zero static secrets |
| Observability | stdout JSON | OpenTelemetry + Grafana | audit pipeline, alerting |
| Transport | HTTP in-cluster | TLS/mTLS | cert-manager, mTLS everywhere |

## Incremental adoption roadmap

Nobody adopts all of this at once. A realistic sequence:

1. **Inventory.** Find every API key and service account your agents use. You
   cannot govern what you have not enumerated.
2. **Identity for one workload.** Give a single agent a SPIFFE identity; remove
   its static key. Prove it end to end.
3. **Delegation.** Add token exchange so the agent acts *for* a user with
   audience-bound, short-lived tokens.
4. **Policy.** Move authorization into OPA, deny-by-default. Start with one
   high-risk action.
5. **Approvals.** Add human-in-the-loop for the riskiest actions.
6. **Observability.** Wire the audit trail and alerts before widening access.
7. **LLM gateway.** Remove the last static secret; route model calls through an
   identity-authenticated gateway.
8. **Scale out.** Repeat for the next agent; productize the SDK.

## Operating model

- **Platform team** owns SPIRE, the authorization server, and the policy engine.
- **Product teams** own their tools and their policy *requests*.
- **Security** owns the guardrails, the threat model, and the review of policy
  changes.
- **Approvers** (managers, finance, privacy) own high-risk decisions, and their
  approvals are audited.

## Cost model

- **Run cost:** identity infrastructure (SPIRE/Keycloak/OPA) is modest but is now
  critical path; budget for HA.
- **Engineering cost:** the first agent is more work than a shared API key. The
  second is much less (the SDK and policy patterns are reusable).
- **Risk reduction:** a leaked credential becomes a minutes-long, single-purpose
  token instead of a master key.

## Risk register (summary)

| Risk | Mitigation |
|---|---|
| Identity infrastructure outage stops agents | HA, monitoring, documented fail modes |
| Policy mistakes block legitimate work | policy tests, staged rollout, decision logs |
| Approval bottleneck | SLAs, auto-approve low tiers, clear queues |
| Model sends data externally | local default, gateway, redaction, retention controls |
| Over-broad initial scope | adopt incrementally, start with one action |

## Anti-patterns

- Giving the agent a long-lived key "just for now".
- Putting authorization in application code instead of policy.
- Trusting the model to police itself.
- Forwarding tokens between services.
- Treating observability as a Phase 2 problem.
- Skipping approvals on "small" high-risk actions.

## Measuring success

- % of agents with short-lived, audience-bound credentials (target: 100%).
- Number of static keys removed.
- Median approval time for gated actions.
- Policy-denial rate (a spike can mean injection attempts or a bad policy).
- Mean time to attribute an action to an agent and a user (target: seconds).
