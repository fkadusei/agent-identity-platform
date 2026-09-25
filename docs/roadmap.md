# Roadmap

Living checklist. Updated at the end of every work session (see
[`../HANDOFF.md`](../HANDOFF.md)). A phase is done only when its gate passes.

Legend: `[x]` done · `[~]` in progress · `[ ]` not started

**Current totals:** 160 app tests (20 Postgres ones skip) · 34 SDK tests · 31
policy tests · 10 required CI checks · PRs #1–#73. Phases 1–3 complete; every
threat in the threat model addressed. The repo is public.

---

## Phase 0 — Foundations, security, documentation

- [x] Repo scaffolded at `agent-identity-platform/`
- [x] Security baseline: `.gitignore`, `.gitleaks.toml`, pre-commit hook,
      `scripts/install-hooks.sh`, `scripts/scan-secrets.sh`, `.env.example`,
      `SECURITY.md`
- [x] CI security workflow (`security.yml`) + repo checks (`ci.yml`)
- [x] Verified the hook blocks a test secret and gitleaks finds no leaks
- [x] ADRs 0001–0011 recorded
- [x] `docs/threat-model.md`, `docs/data-handling.md`, `docs/glossary.md`,
      `CONTRIBUTING.md`
- [x] `docs/real-world-adoption.md` (finalized in Phase 3)
- [x] `docs/visualization/index.html` — interactive 3D architecture (light/dark)
- [x] `README.md`, `HANDOFF.md`, `LICENSE`
- [x] Cross-links with `enterprise-agent-nhi`
- [x] Git repo created and pushed
- [x] **Gate:** security DoD met, plan + adoption doc reviewed by owner

## Phase 1 — Reusable core + realistic local app

- [x] Extract `sdk/agentnhi/` from the concepts demo (typed, unit-tested):
      SVID fetch, mTLS, token exchange, verification (`aud`+`azp`), OPA client
      (fail-closed), redaction-safe audit — 32 tests
- [x] OPA policy matrix (allow / deny / require-approval) + tests — 14 tests
- [x] Synthetic simulators: CRM, orders, payments, ticketing — 10 tests
- [x] Tool servers (FastAPI + MCP) behind one enforcement core — 11 tests
- [x] Approvals service (`app/api`): pending/decision/verify — 13 tests
- [x] LangGraph agent: planner + tool loop + **approval interrupts** — 4 tests
- [x] FastAPI: sessions, tasks, audit query
- [x] React UI: task console, approval queue, audit timeline
- [x] Extended attack suite (forwarding, out-of-policy, approval bypass, PII, rogue workload)
- [x] Local deployment on kind (`scripts/setup.sh` + `deploy/kind/`)
- [x] React UI (Vite): task console, approval queue, audit timeline
- [x] User guides: overview, support rep, approver (plain-language HTML)
- [x] **Gate: happy path works; all attacks blocked; approval flow demonstrated**

## Phase 2 — Production hardening

- [x] **TLS/mTLS everywhere** — SPIFFE mTLS on agent↔gateway, a Linkerd mesh for
      every other in-cluster hop (`docs/tls.md`, `scripts/tls-check.sh`)
- [~] **HA** — the app tier and Keycloak are replicated (`docs/ha.md`); still
      single-replica: SPIRE (its registry is in Postgres and its keys are on a PVC
      — S1 — but 2+ replicas also need a shared KeyManager, i.e. a cloud KMS),
      Postgres (one replica, though its data is on a persistent volume — S3), the
      sandbox (one replica, on its own volume — S9)
- [x] Persistent storage for Postgres and SPIRE (S3, S1) — PVC-backed volumes, so
      their data outlives the pod rather than the process (`docs/data-stores.md`)
- [x] Hardened Keycloak (S4) — production mode, an explicit hostname, a read-only
      root filesystem (no Trivy exception), and the realm imported by a Job
- [x] **Secrets out of git and manifests** — client secrets generated into a
      gitignored `.env`, the realm rendered from a template, values mounted as
      Kubernetes Secrets; the External Secrets Operator pattern is documented
      (`docs/secrets.md`)
- [x] **LLM gateway authenticated by SPIFFE identity** — the agent holds no
      model credential; it reaches the model only over mTLS (`app/gateway/`)
- [x] Observability — OpenTelemetry traces spanning agent → gateway → tools →
      policy, with identity attributes on the decision span; collector + Jaeger
      in-cluster. Platform metrics at `/metrics` (logins, policy decisions from
      the audit stream, approval backlog, request rates), scraped by Prometheus,
      with a provisioned Grafana dashboard (`docs/observability.md`)
- [x] Policy lifecycle — versioned OPA bundle (revision stamped into every
      decision, audit event, span and decision log), staged-rollout process
      (`docs/policy-lifecycle.md`)
- [x] **Rate and cost limits** at the LLM gateway (`docs/llm-gateway.md`)
- [x] Agent guardrails (task + decision) and an eval suite, stubbed in CI
      (`docs/guardrails-and-evals.md`)
- [x] Supply chain: SBOM + image scan (already in CI), **cosign (keyless
      Sigstore) signing + verification**, Kyverno admission policy
      (`docs/supply-chain.md`, ADR-0010)
- [x] **Enrollment + role administration** — self-service signup (toggleable),
      admin user management via a least-privilege Keycloak service account, real
      login, and server-side role enforcement (`docs/enrollment-and-roles.md`,
      ADR-0011)
- [x] **UI polish** — a per-run "what just happened" summary, the delegation
      chain (agent → user → tool), and inline approve/deny from the result card
      (with the requester resuming once a manager decides)
- [x] Operator user guide — bring-up, health checks, common operations,
      incident-response playbooks, alerting, troubleshooting and the Phase 2 gate
      checklist (`docs/operator-guide.md`)
- [x] **Gate:** threat model addressed (all ten threats, T9 tenancy included),
      traces + dashboards live, secret audit clean, all six attacks blocked

## Backlog / known gaps

The remaining work is tagged with stable IDs in
[`backlog.md`](backlog.md) (S1–S15) so it can be referenced directly. The
completed items are kept below for the record.

- [x] **Multi-tenant isolation (threat T9)** — the tenant is an identity
      attribute; policy denies an unscoped caller and every data accessor scopes
      by tenant (`docs/tenancy.md`, `scripts/tenancy-tests.sh`)
- [x] **TLS/mTLS everywhere** — SPIFFE mTLS on agent↔gateway, a service mesh
      (Linkerd) for every other in-cluster hop including Keycloak, OPA and the
      observability stack (`docs/tls.md`, `scripts/tls-check.sh`)
- [x] **Per-agent rate and cost limits** on the LLM gateway — keyed on the
      caller's JWT-SVID-proven SPIFFE ID; 429 + `Retry-After` on exceed; counters
      durable in Postgres when a database is configured (`docs/llm-gateway.md`)
- [x] **HA for the app tier** — api/tools/agent/gateway/opa run 2 replicas with
      soft anti-affinity and PodDisruptionBudgets; the kind cluster has worker
      nodes and `scripts/ha-check.sh` proves an eviction is survivable. SPIRE,
      Keycloak, Postgres and the sandbox are documented as single-replica, and
      why (`docs/ha.md`)
- [x] **Autoscaling** — api/tools/agent/gateway/opa scale 2→5; the api also on the
      **approval backlog** and per-pod request rate, via prometheus-adapter
      (`docs/autoscaling.md`)
- [x] **Self-healing** — every container carries a liveness probe, so a *hung*
      process is restarted rather than reported forever; the gateway's health
      listener exists because an mTLS-only service cannot be probed by a kubelet
      (S16)
- [x] **Tenancy depth** — approvals are scoped by tenant (create, list,
      decide, verify), keyed on the caller's identity; a manager sees only their
      own tenant's queue (`docs/tenancy.md`)
- [x] **Role -> tool matrix** — an explicit table in policy/authz.rego, with
      per-tenant overrides (S8); the agent offers only the permitted tools, the
      tool server enforces, and `scripts/role-tools.sh` shows it end to end,
      including the same role holding different power in two tenants
      (`docs/roles-and-tools.md`)
- The simulated systems keep their own data now (S9) — the sandbox snapshots
  refunds and drafts to its own volume, so a restart no longer resets the demo.

## Phase 3 — Deploy and adoption

- [x] Cloud-agnostic **Helm chart + values**; ingress/TLS via values
      (`deploy/helm/agent-platform`); SPIRE and Keycloak are documented
      prerequisites, the policy bundle a signed build artifact
- [x] Managed data stores — approvals, agent run checkpoints and (S9) the sandbox's
      own state are durable; the platform's are in Postgres when `DATABASE_URL` is
      set (`docs/data-stores.md`)
- [x] **CI/CD with approval gates** — release builds + signs images/bundle/chart;
      deploy verifies signatures, applies the chart behind a GitHub Environment
      approval gate, smoke-tests (incl. the attack suite) and rolls back
      (`docs/ci-cd.md`)
- [x] Real sandbox integrations behind the existing tool interfaces — a backend
      seam (simulator | HTTP) with a sandbox service exercising the REST path
      (`docs/integrations.md`)
- [x] Finalize `docs/real-world-adoption.md` (production checklist + doc map) and
      the runbook (`docs/operator-guide.md`)
- [x] **Gate:** the platform runs end to end; runbook + adoption guide complete
