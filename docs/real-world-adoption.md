# Real-World Adoption Guide

> **Status: final.** The platform runs end to end (Phases 1–3 complete). This is
> the guide leaders and architects read first; the runbook for operating it is
> [`operator-guide.md`](operator-guide.md).

## Who this is for

Anyone deciding whether — and how — to give AI agents real access to real
systems without handing them long-lived API keys.

## The problem, in one paragraph

Most agents today carry a static API key. That key works from anywhere if
leaked, never expires on its own, and cannot tell you *which* agent did what.
Because an agent contains a model that can be talked into things, a leaked key
plus a clever sentence becomes a breach. The fix is not a better key; it is to
stop using keys and give the agent an identity instead.

## What this platform does

An agent acts **as itself** (a short-lived SPIFFE identity), **for a user**
(OAuth token exchange), against tools whose every call is **authorized by policy**
(OPA, deny-by-default) with **human approval** for high-risk actions and an
**audit trail** keyed on identity. It holds no static credentials — not even for
the model (an mTLS LLM gateway holds that).

## What changes: concepts demo → this platform → production

| Concern | This platform | Production target |
|---|---|---|
| Workload identity | SPIFFE/SPIRE, SVIDs fetched per workload | HA SPIRE, persistent storage |
| Delegation | RFC 8693 exchange, audience-bound, minutes-long | same |
| Authorization | OPA allow/deny/require-approval, deny-by-default | staged rollout, decision logs (built) |
| Tools | backend seam: simulator **or** real HTTP/sandbox | real vendor sandboxes → production systems |
| Human oversight | approval interrupts + a queue, role-gated | SLAs, escalation |
| Secrets | none static; `.env` → Secrets, admin service account least-privilege | External Secrets / Vault |
| Observability | OTel traces with identity + Prometheus/Grafana dashboard | alerting pipeline |
| Supply chain | keyless cosign signing + admission policy | registry + policy controller |
| Delivery | Helm chart; CI/CD with a human approval gate | GitOps |
| Transport | mTLS on agent↔gateway | mTLS everywhere, cert-manager |

## Where to start (the map)

| You want to… | Read |
| --- | --- |
| understand the terms | [`glossary.md`](glossary.md) |
| know what it defends against | [`threat-model.md`](threat-model.md) |
| run it locally | [`../README.md`](../README.md) (kind, `scripts/setup.sh`) |
| deploy it | [`../deploy/helm/agent-platform/README.md`](../deploy/helm/agent-platform/README.md) |
| operate it | [`operator-guide.md`](operator-guide.md) (the runbook) |
| change policy | [`policy-lifecycle.md`](policy-lifecycle.md) |
| onboard people | [`enrollment-and-roles.md`](enrollment-and-roles.md) |
| integrate a system | [`integrations.md`](integrations.md) |
| see the data model | [`data-stores.md`](data-stores.md) · [`data-handling.md`](data-handling.md) |
| ship it safely | [`ci-cd.md`](ci-cd.md) · [`supply-chain.md`](supply-chain.md) |

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
6. **Observability.** Wire traces, metrics and alerts *before* widening access.
7. **LLM gateway.** Remove the last static secret; route model calls through an
   identity-authenticated gateway.
8. **Scale out.** Repeat for the next agent; productize the SDK.

Each step is independently useful, and each shrinks the blast radius of the next.

## Production checklist

Before serving real traffic, close these — they are deliberate scope choices in
the reference, not oversights:

- [ ] **Multi-tenant isolation** — not implemented (threat T9). Add a tenant
      claim and enforce it in policy *and* the tools before serving >1 tenant.
- [ ] **TLS/mTLS everywhere** — only agent↔gateway is mTLS today; terminate and
      originate TLS on every hop (cert-manager or a service mesh).
- [ ] **HA** — the app tier is replicated (2 replicas + PDBs, see
      [`ha.md`](ha.md)); SPIRE, Keycloak and Postgres still need a shared
      datastore / external DB / managed HA.
- [ ] **Managed data** — point `database.url` at a managed Postgres (done); give
      it backups and a migration story.
- [ ] **Identity federation** — replace seeded users with your IdP (OIDC/SAML) and
      lifecycle (SCIM).
- [ ] **Rate/cost limits** — per-agent quotas at the LLM gateway.
- [ ] **Model data controls** — provider retention/no-training terms, or keep the
      local model.
- [ ] **Alerting** — wire the rules in [`operator-guide.md`](operator-guide.md)
      into your pager.

## Operating model

- **Platform team** owns SPIRE, the authorization server, and the policy engine.
- **Product teams** own their tools and their policy *requests*.
- **Security** owns the guardrails, the threat model, and the review of policy
  changes.
- **Approvers** (managers, finance, privacy) own high-risk decisions, and their
  approvals are audited.

## Cost model

- **Run cost:** identity infrastructure (SPIRE/Keycloak/OPA/Postgres) is modest
  but is now critical path; budget for HA.
- **Engineering cost:** the first agent is more work than a shared API key. The
  second is much less (the SDK and policy patterns are reusable).
- **Risk reduction:** a leaked credential becomes a minutes-long, single-purpose
  token instead of a master key.

## Risk register (summary)

| Risk | Mitigation |
|---|---|
| Identity infrastructure outage stops agents | HA, monitoring, documented fail modes |
| Policy mistakes block legitimate work | policy tests, staged rollout, decision logs |
| Policy engine down denies everything | fail-closed by design; alert on OPA health |
| Approval bottleneck | SLAs, auto-approve low tiers, clear queues |
| Model sends data externally | local default, gateway, redaction, retention controls |
| Over-broad initial scope | adopt incrementally, start with one action |

## Anti-patterns

- Giving the agent a long-lived key "just for now".
- Putting authorization in application code instead of policy.
- Trusting the model to police itself.
- Forwarding tokens between services.
- Enforcing roles in the UI instead of the server.
- Treating observability as a later problem.
- Skipping approvals on "small" high-risk actions.

## Measuring success

- % of agents with short-lived, audience-bound credentials (target: 100%).
- Number of static keys removed.
- Median approval time for gated actions.
- Policy-denial rate (a spike can mean injection attempts or a bad policy).
- Mean time to attribute an action to an agent and a user (target: seconds).
