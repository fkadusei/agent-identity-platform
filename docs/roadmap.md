# Roadmap

Living checklist. Updated at the end of every work session (see
[`../HANDOFF.md`](../HANDOFF.md)). A phase is done only when its gate passes.

Legend: `[x]` done · `[~]` in progress · `[ ]` not started

---

## Phase 0 — Foundations, security, documentation

- [x] Repo scaffolded at `agent-identity-platform/`
- [x] Security baseline: `.gitignore`, `.gitleaks.toml`, pre-commit hook,
      `scripts/install-hooks.sh`, `scripts/scan-secrets.sh`, `.env.example`,
      `SECURITY.md`
- [x] CI security workflow (`security.yml`) + repo checks (`ci.yml`)
- [x] Verified the hook blocks a test secret and gitleaks finds no leaks
- [x] ADRs 0001–0010 recorded
- [x] `docs/threat-model.md`, `docs/data-handling.md`, `docs/glossary.md`,
      `CONTRIBUTING.md`
- [x] `docs/real-world-adoption.md` (draft)
- [x] `docs/visualization/index.html` — interactive 3D architecture (light/dark)
- [x] `README.md`, `HANDOFF.md`, `LICENSE`
- [x] Cross-links with `enterprise-agent-nhi`
- [x] Git repo created and pushed
- [ ] **Gate:** security DoD met, plan + adoption doc reviewed by owner

## Phase 1 — Reusable core + realistic local app

- [x] Extract `sdk/agentnhi/` from the concepts demo (typed, unit-tested):
      SVID fetch, mTLS, token exchange, verification (`aud`+`azp`), OPA client
      (fail-closed), redaction-safe audit — 32 tests
- [x] OPA policy matrix (allow / deny / require-approval) + tests — 14 tests
- [x] Synthetic simulators: CRM, orders, payments, ticketing — 10 tests
- [x] Tool servers (FastAPI + MCP) behind one enforcement core — 11 tests
- [x] Approvals service (`app/api`): pending/decision/verify — 13 tests
- [x] LangGraph agent: planner + tool loop + **approval interrupts** — 4 tests
- [ ] FastAPI: sessions, tasks, audit query
- [ ] React UI: task console, approval queue, audit timeline
- [x] Extended attack suite (forwarding, out-of-policy, approval bypass, PII, rogue workload)
- [x] Local deployment on kind (`scripts/setup.sh` + `deploy/kind/`)
- [x] React UI (Vite): task console, approval queue, audit timeline
- [x] User guides: overview, support rep, approver (plain-language HTML)
- [x] **Gate: happy path works; all attacks blocked; approval flow demonstrated**

## Phase 2 — Production hardening

- [~] TLS/mTLS everywhere; HA SPIRE; persistent storage; hardened Keycloak
      (mTLS done for the agent↔gateway hop; the rest is plaintext in-cluster)
- [x] **Secrets out of git and manifests** — client secrets generated into a
      gitignored `.env`, the realm rendered from a template, values mounted as
      Kubernetes Secrets; the External Secrets Operator pattern is documented
      (`docs/secrets.md`)
- [x] **LLM gateway authenticated by SPIFFE identity** — the agent holds no
      model credential; it reaches the model only over mTLS (`app/gateway/`)
- [x] Observability — OpenTelemetry traces spanning agent → gateway → tools →
      policy, with identity attributes on the decision span; collector + Jaeger
      in-cluster and collector metrics for Prometheus (`docs/observability.md`)
- [x] Policy lifecycle — versioned OPA bundle (revision stamped into every
      decision, audit event, span and decision log), staged-rollout process
      (`docs/policy-lifecycle.md`)
- [ ] Agent guardrails + evals; rate and cost limits
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
- [ ] **Gate:** threat model addressed; dashboards live; secret audit clean

## Backlog / known gaps

- TLS for the remaining in-cluster hops (only agent↔gateway is mTLS today).
- Per-agent rate and cost limits on the gateway.
- The tools' in-memory simulator state resets on restart (fine for the demo).

## Phase 3 — Deploy and adoption

- [ ] Cloud-agnostic Helm chart + values; ingress/TLS; managed data stores
- [ ] CI/CD with approval gates
- [ ] Real sandbox integrations behind the existing tool interfaces
- [ ] Finalize `docs/real-world-adoption.md` and the runbook
- [ ] **Gate:** deployed end-to-end; runbook + adoption guide complete
